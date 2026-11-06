# Test dell'instradamento del grafo: quando il modello chiede uno strumento, il grafo lo
# esegue e gli restituisce il risultato. Quasi tutti usano un modello finto con un copione;
# le prove reali con LM Studio (RUN_LM_STUDIO=1) sono in fondo a ogni gruppo.
# libreria standard: cache, log, variabili d'ambiente, istanti fissi
import functools
import logging
import os
from datetime import datetime, timezone

# httpx per il servizio HTTP finto; messaggi di LangChain per scrivere il copione del modello
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# parti dell'app da provare
from app import tools
from app.cli import main
from app.config import load_settings
from app.graph import build_graph, instrada


# Supporto: modello finto che segue un copione di risposte gia' scritte e registra in
# self.chiamate i messaggi ricevuti a ogni chiamata (per controllare cosa ha visto il modello).
class ModelloCopione:
    """Modello finto: restituisce messaggi gia' pronti, in ordine.
    Finiti i messaggi, ripete l'ultimo (utile per il modello che chiede sempre lo strumento)."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)
        self.chiamate = []

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)
        # copia senza id, altrimenti add_messages la scambia per lo stesso messaggio
        return self.messaggi[0].model_copy(update={"id": None})


# Supporto per le prove reali: carica una volta sola (cache) gli strumenti dell'agente,
# avviando anche i server MCP.
@functools.cache
def _strumenti_agente():
    """Gli strumenti dell'agente vero (app.cli): 4 locali e HTTP + i tool del server MCP."""
    from app.cli import carica_strumenti
    return carica_strumenti()


# Supporto per le prove reali: grafo con il modello vero di LM Studio.
def _grafo_reale(impostazioni):
    """Lo stesso agente di app.cli: tutti gli strumenti, SYSTEM_PROMPT, 8192 token."""
    from app.llm import build_llm
    strumenti = _strumenti_agente()
    return build_graph(build_llm(impostazioni, strumenti), impostazioni.max_steps,
                       strumenti=strumenti)


# Supporto: messaggio del modello che chiede uno strumento (di base tooltime per Tokyo).
def _chiamata(nome="tooltime", args=None, id_="c1"):
    return AIMessage("", tool_calls=[
        {"name": nome, "args": args or {"fuso": "Asia/Tokyo"}, "id": id_}])


# Supporto: stato iniziale del grafo con una sola domanda dell'utente e zero passaggi.
def _stato(testo="Che ore sono a Tokyo?"):
    return {"messages": [HumanMessage(testo)], "steps": 0}


# Fixture automatica: in ogni test l'orologio e' fisso al 1 marzo 2026 11:00 UTC.
@pytest.fixture(autouse=True)
def _orologio_fisso(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


# Verifica la funzione di instradamento: con una chiamata a strumento va al nodo "strumenti",
# senza chiamate termina, al limite dei passaggi (5) va al nodo "limite".
def test_instrada_a_strumenti():
    con = {"messages": [_chiamata()], "steps": 0}
    senza = {"messages": [AIMessage("ciao")], "steps": 0}
    al_limite = {"messages": [_chiamata()], "steps": 5}
    assert instrada(con) == "strumenti"
    assert instrada(senza) == "__end__"
    assert instrada(al_limite) == "limite"


# Verifica il giro completo: lo strumento e' eseguito davvero e il suo risultato
# (ToolMessage) torna al modello, che poi da' la risposta finale. Un passaggio contato.
def test_risultato_torna_al_modello():
    llm = ModelloCopione([_chiamata(), AIMessage("A Tokyo sono le 20:00.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "A Tokyo sono le 20:00."
    # ultimo messaggio ricevuto dal modello alla seconda chiamata
    ricevuto = llm.chiamate[1][-1]
    assert isinstance(ricevuto, ToolMessage)
    assert "ore 20 in punto" in ricevuto.content
    assert out["steps"] == 1


# Verifica il limite di passaggi: un modello che chiede sempre lo strumento non fa girare il
# grafo all'infinito; dopo 3 passaggi arriva un messaggio finale che spiega il limite.
def test_limite_passaggi():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=3).invoke(_stato())
    # controllo: 3 passaggi con lo strumento, 4 chiamate al modello
    assert out["steps"] == 3
    assert len(llm.chiamate) == 4
    # l'ultimo messaggio e' testo, senza altre chiamate a strumenti
    ultimo = out["messages"][-1]
    assert isinstance(ultimo, AIMessage) and not ultimo.tool_calls
    assert "limite" in ultimo.content and "3" in ultimo.content


# Verifica che al limite ogni tool_call rimasta senza risposta riceva comunque un ToolMessage:
# altrimenti al turno dopo il server rifiuta la cronologia incompleta.
def test_limite_chiude_le_tool_calls_pendenti():
    llm = ModelloCopione([_chiamata(), _chiamata(id_="c2"), AIMessage("Ok, ripartiamo.")])
    grafo = build_graph(llm, max_steps=1)
    primo = grafo.invoke(_stato())
    # modello chiede lo strumento (eseguito), poi lo richiede: limite raggiunto
    secondo = grafo.invoke({"messages": primo["messages"] + [HumanMessage("e ora?")],
                            "steps": 0})
    assert secondo["messages"][-1].content == "Ok, ripartiamo."
    # messaggi dell'ultima chiamata: id delle tool_call chieste e id a cui si e' risposto
    inviati = llm.chiamate[-1]
    richieste = {c["id"] for m in inviati if isinstance(m, AIMessage) for c in m.tool_calls}
    risposte = {m.tool_call_id for m in inviati if isinstance(m, ToolMessage)}
    assert richieste == {"c1", "c2"}
    assert richieste <= risposte  # nessuna tool_call senza ToolMessage


# Verifica il log del grafo: prima la chiamata (nome e argomenti), poi il risultato.
def test_log_chiamata_strumento(caplog):
    llm = ModelloCopione([_chiamata(), AIMessage("fatto")])
    # caplog (fixture di pytest) raccoglie i log di livello INFO del logger "app.graph"
    with caplog.at_level(logging.INFO, logger="app.graph"):
        build_graph(llm).invoke(_stato())
    # posizione della riga con la chiamata e di quella con il risultato
    testo = [r.getMessage() for r in caplog.records]
    prima = next(i for i, t in enumerate(testo) if "tooltime" in t and "Asia/Tokyo" in t)
    dopo = next(i for i, t in enumerate(testo) if "ore 20 in punto" in t)
    assert prima < dopo


# Verifica che gli argomenti scelti dal modello (qui parte="ora") arrivino allo strumento.
def test_parte_passata_dal_modello_arriva_allo_strumento():
    llm = ModelloCopione([_chiamata(args={"fuso": "Asia/Tokyo", "parte": "ora"}),
                          AIMessage("Sono le 20:00.")])
    build_graph(llm).invoke(_stato())
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "Tokyo: sono le ore 20 in punto"


# Verifica che un argomento fuori dai valori ammessi diventi un ToolMessage di errore
# (status "error") rimandato al modello, senza far cadere il grafo.
def test_parte_non_valida_e_un_errore_gestito():
    llm = ModelloCopione([_chiamata(args={"fuso": "Asia/Tokyo", "parte": "minuti"}),
                          AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage) and errore.status == "error"
    assert out["messages"][-1].content == "Non posso."


# Verifica che il vecchio nome "ora_corrente" (ora "tooltime") sia trattato come sconosciuto.
def test_vecchio_nome_non_e_piu_uno_strumento():
    llm = ModelloCopione([_chiamata("ora_corrente"), AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage)
    assert errore.status == "error"
    assert out["messages"][-1].content == "Non posso."


# Verifica che uno strumento inventato dal modello dia un errore gestito e il grafo prosegua.
def test_strumento_sconosciuto():
    llm = ModelloCopione([_chiamata("non_esiste", {"x": 1}), AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "Non posso."
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage)
    assert errore.status == "error"


# Prova reale (saltata senza LM Studio attivo e RUN_LM_STUDIO=1): il modello vero deve
# chiedere tooltime per "Che ore sono a Tokyo?". Una risposta simulata non lo dimostra.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_strumento_lm_studio():
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Che ore sono a Tokyo?"))
    # nomi di tutti gli strumenti chiesti dal modello durante la risposta
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "tooltime" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"


# Verifica che la CLI passi max_steps al grafo e mostri all'utente il messaggio del limite.
def test_cli_usa_max_steps():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    righe = iter(["Che ore sono a Tokyo?", "exit"])
    uscite = []
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append,
         llm=llm, max_steps=1, stream=False)
    # un solo passaggio con lo strumento, poi il limite
    assert len(llm.chiamate) == 2
    assert any("limite di 1 passaggi" in u for u in uscite)


# argomenti di esempio per toolconvert: 10 miglia in chilometri
CONV = {"valore": 10, "da": "miglia", "a": "km"}


# Verifica che toolconvert passi dal grafo come tooltime: eseguito, risultato al modello.
def test_convertitore_eseguito_dal_grafo():
    llm = ModelloCopione([_chiamata("toolconvert", CONV), AIMessage("Sono 16 km.")])
    out = build_graph(llm).invoke(_stato("Quanti km sono 10 miglia?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "10 miglia = 16,0934 chilometri"
    assert out["messages"][-1].content == "Sono 16 km." and out["steps"] == 1


# Verifica che un valore non numerico sia fermato dalla validazione degli argomenti:
# ToolMessage di errore che nomina "valore", e il modello risponde comunque.
def test_convertitore_argomenti_non_validi():
    llm = ModelloCopione([_chiamata("toolconvert", {"valore": "tanti", "da": "m", "a": "km"}),
                          AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato("Converti tanti metri"))
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage) and errore.status == "error"
    assert "valore" in errore.content and "valid number" in errore.content
    assert out["messages"][-1].content == "Non posso."


# Verifica il limite di passaggi anche con toolconvert.
def test_convertitore_rispetta_max_steps():
    llm = ModelloCopione([_chiamata("toolconvert", CONV)])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=2).invoke(_stato("Quanti km sono 10 miglia?"))
    assert out["steps"] == 2
    assert llm.chiamate[1][-1].content == "10 miglia = 16,0934 chilometri"
    assert "limite di 2 passaggi" in out["messages"][-1].content


# Prova reale (saltata senza LM Studio attivo e RUN_LM_STUDIO=1): il modello vero deve
# usare toolconvert e riportare il risultato giusto nella risposta finale.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_convertitore_lm_studio():
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quanti chilometri sono 10 miglia?"))
    # controllo 1: lo strumento e' stato chiesto
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "toolconvert" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    # controllo 2: lo strumento ha dato il valore atteso
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    assert any("16,0934" in r for r in risultati), risultati
    # controllo 3: la risposta finale riporta il numero (virgola o punto, anche arrotondato)
    finale = out["messages"][-1].content
    assert any(x in finale for x in ("16,0934", "16.0934", "16,09", "16.09")), finale


# --- calcolatrice sicura: il wrapper HTTP passa dal grafo come gli altri strumenti ---

# argomenti di esempio per toolcalc
CALC = {"espressione": "(3+4)^2/7"}


# Supporto: sostituisce il servizio HTTP con uno finto; l'handler decide la risposta.
def _servizio_finto(monkeypatch, handler):
    monkeypatch.setattr(tools, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))


# Verifica che toolcalc passi dal grafo: il servizio finto risponde 7, il modello lo riceve.
def test_calcolatrice_eseguita_dal_grafo(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(
        200, json={"espressione": "(3+4)^2/7", "risultato": 7}))
    llm = ModelloCopione([_chiamata("toolcalc", CALC), AIMessage("Fa 7.")])
    out = build_graph(llm).invoke(_stato("Quanto fa (3+4)^2/7?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "(3+4)^2/7 = 7"
    assert out["messages"][-1].content == "Fa 7." and out["steps"] == 1


# Verifica che il servizio spento non blocchi il grafo: il modello riceve un messaggio
# leggibile ("non raggiungibile", nessun Traceback) e risponde all'utente.
def test_calcolatrice_spenta_non_blocca_il_grafo(monkeypatch):
    # handler che simula la connessione rifiutata
    def spento(request):
        raise httpx.ConnectError("rifiutata", request=request)
    _servizio_finto(monkeypatch, spento)
    llm = ModelloCopione([_chiamata("toolcalc", CALC), AIMessage("Il servizio e' spento.")])
    out = build_graph(llm).invoke(_stato("Quanto fa (3+4)^2/7?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert "non raggiungibile" in risultato.content
    assert "Traceback" not in risultato.content
    assert out["messages"][-1].content == "Il servizio e' spento."


# Verifica il limite di passaggi anche con toolcalc.
def test_calcolatrice_rispetta_max_steps(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(
        200, json={"espressione": "(3+4)^2/7", "risultato": 7}))
    llm = ModelloCopione([_chiamata("toolcalc", CALC)])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=2).invoke(_stato("Quanto fa (3+4)^2/7?"))
    assert out["steps"] == 2
    assert "limite di 2 passaggi" in out["messages"][-1].content


# Fixture per le prove reali: avvia il servizio FastAPI vero e lo ferma alla fine del test.
@pytest.fixture
def servizio_vero(monkeypatch):
    """Servizio calcolatrice vero (uvicorn) in un thread, su una porta libera."""
    import socket
    import threading
    import time

    import uvicorn

    from servizio.main import app

    # porta 0: il sistema operativo sceglie una porta libera, che poi si legge
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    # uvicorn gira in un thread separato (daemon: si chiude con il processo dei test)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # attende al massimo 10 secondi che il servizio sia partito
    limite = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < limite, "il servizio non si e' avviato entro 10 secondi"
        time.sleep(0.05)
    # il wrapper chiamera' questo servizio
    monkeypatch.setenv("CALC_BASE_URL", f"http://127.0.0.1:{porta}")
    # qui gira il test; dopo yield si ferma il servizio
    yield
    server.should_exit = True
    thread.join(timeout=10)


# Prova reale (saltata senza LM Studio attivo e RUN_LM_STUDIO=1), con il servizio vero:
# il modello deve usare toolcalc, rispondere 7 e non scrivere in LaTeX.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_calcolatrice_lm_studio(servizio_vero):
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quanto fa (3+4)^2 / 7?"))
    # controlli: strumento chiesto, risultato "= 7", risposta finale con 7 e senza "$"
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "toolcalc" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    assert any("= 7" in r for r in risultati), risultati
    finale = out["messages"][-1].content
    assert "7" in finale, finale
    assert "$" not in finale, f"risposta in LaTeX: {finale}"


# --- giorni e scadenze: il wrapper HTTP tooldate passa dal grafo come gli altri ---

# risposta finta del servizio a "Natale e' lavorativo?"
GIORNO_NATALE = {
    "operazione": "giorno", "data": "2026-12-25", "giorno_settimana": "venerdì",
    "lavorativo": False, "fine_settimana": False, "festivita": ["Natale"],
    "avviso": "Calcolo indicativo, non ha valore legale."}


# Verifica che tooldate passi dal grafo: il modello riceve la frase gia' pronta sul giorno.
def test_date_eseguito_dal_grafo(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(200, json=GIORNO_NATALE))
    llm = ModelloCopione([_chiamata("tooldate", {"operazione": "giorno", "data": "natale"}),
                          AIMessage("Natale e' festivo.")])
    out = build_graph(llm).invoke(_stato("Natale e' lavorativo?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content.startswith("2026-12-25 (venerdì): festivo (Natale).")
    assert out["messages"][-1].content == "Natale e' festivo." and out["steps"] == 1


# Verifica che con il servizio spento tooldate dia un messaggio e il grafo prosegua.
def test_date_servizio_spento_non_blocca_il_grafo(monkeypatch):
    def spento(request):
        raise httpx.ConnectError("rifiutata", request=request)
    _servizio_finto(monkeypatch, spento)
    llm = ModelloCopione([_chiamata("tooldate", {"operazione": "giorno", "data": "natale"}),
                          AIMessage("Servizio spento.")])
    out = build_graph(llm).invoke(_stato("Natale e' lavorativo?"))
    assert "non raggiungibile" in llm.chiamate[1][-1].content
    assert out["messages"][-1].content == "Servizio spento."


# Verifica che un "tipo" non ammesso ("lavorativo" invece di "lavorativi") sia fermato dalla
# validazione: ToolMessage di errore che nomina "tipo", il servizio non viene nemmeno usato.
def test_date_tipo_non_valido_e_un_errore_gestito(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(200, json=GIORNO_NATALE))
    llm = ModelloCopione([_chiamata("tooldate", {"operazione": "scadenza", "giorni": 3,
                                                 "tipo": "lavorativo"}),
                          AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato("Scadenza tra 3 giorni lavorativi?"))
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage) and errore.status == "error"
    assert "tipo" in errore.content
    assert out["messages"][-1].content == "Non posso."


# Supporto per le prove reali: nomi degli strumenti chiesti dal modello, in ordine, e testi
# dei risultati restituiti dagli strumenti.
def _richieste_e_risultati(out):
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    return richieste, risultati


# Prova reale (saltata senza LM Studio attivo e RUN_LM_STUDIO=1), con il servizio vero:
# giorni lavorativi di dicembre 2026 (21), avviso "indicativo" riportato, niente LaTeX.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_date_lm_studio(servizio_vero):
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quanti giorni lavorativi ci sono dal 1 dicembre 2026 al 31 dicembre 2026?"))
    richieste, risultati = _richieste_e_risultati(out)
    assert "tooldate" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    assert any("giorni lavorativi 21" in r for r in risultati), risultati
    finale = out["messages"][-1].content
    assert "21" in finale, finale
    assert "indicativ" in finale.lower() or "valore legale" in finale.lower(), finale
    assert "$" not in finale, f"risposta in LaTeX: {finale}"


# Prova reale (saltata senza LM Studio attivo): data di Pasqua 2027 con tooldate.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_pasqua_lm_studio(servizio_vero):
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quando è Pasqua nel 2027?"))
    richieste, risultati = _richieste_e_risultati(out)
    assert "tooldate" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    assert any("2027-03-28" in r for r in risultati), risultati
    finale = out["messages"][-1].content
    assert "2027-03-28" in finale or "28 marzo" in finale.lower(), finale
    assert "$" not in finale, f"risposta in LaTeX: {finale}"


# --- prove reali del catalogo MCP, con l'agente unico (6 strumenti) ---

# Le prove di questa sezione sono tutte reali: saltate senza LM Studio attivo e RUN_LM_STUDIO=1.

# Fixture di modulo: carica gli strumenti (con i server MCP) una volta per tutto il file.
@pytest.fixture(scope="module")
def tools_mcp():
    return _strumenti_agente()


# Supporto: fa una domanda all'agente vero e controlla che la risposta non sia vuota
# e non sia in LaTeX; restituisce lo stato finale e il testo della risposta.
def _agente_mcp(tools_mcp, domanda):
    out = _grafo_reale(load_settings()).invoke(_stato(domanda))
    finale = out["messages"][-1].content
    assert finale.strip(), f"risposta vuota: {out['messages']}"
    assert "$" not in finale, f"risposta in LaTeX: {finale}"
    return out, finale


# Supporto: argomenti di ogni chiamata del modello allo strumento `nome`.
def _argomenti(out, nome):
    return [c["args"] for m in out["messages"] if isinstance(m, AIMessage)
            for c in m.tool_calls if c["name"] == nome]


# Ricerca generica nel catalogo: il modello usa search_catalog e cita gli occhialini (PRD030).
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_ricerca(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Avete qualcosa per il nuoto?")
    richieste, _ = _richieste_e_risultati(out)
    assert "search_catalog" in richieste, out["messages"]
    # il modello puo' parafrasare il nome ("occhialini da nuoto"): basta il codice o il nome
    assert "prd030" in finale.lower() or "occhialini" in finale.lower(), finale


# Due strumenti in sequenza: prima search_catalog per trovare il codice, poi get_item("PRD001")
# per il prezzo, che deve comparire nella risposta.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_sequenza(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Quanto costa lo smartphone?")
    richieste, _ = _richieste_e_risultati(out)
    assert "search_catalog" in richieste and "get_item" in richieste, out["messages"]
    # controllo dell'ordine: la ricerca viene prima del dettaglio
    assert richieste.index("search_catalog") < richieste.index("get_item"), richieste
    assert any(a.get("code", "").strip().upper() == "PRD001"
               for a in _argomenti(out, "get_item")), out["messages"]
    assert "499,99" in finale or "499.99" in finale, finale


# Ricerca senza risultati: il tool restituisce "[]" e il modello non deve inventare prodotti.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_vuoto(tools_mcp):
    from mcp_catalogo.catalogo import carica_catalogo

    out, finale = _agente_mcp(tools_mcp, "Avete dei pattini a rotelle?")
    richieste, risultati = _richieste_e_risultati(out)
    assert "search_catalog" in richieste, out["messages"]
    assert "[]" in risultati, risultati
    # controllo: nessun nome di prodotto del catalogo compare nella risposta
    nomi = [p["nome"].lower() for p in carica_catalogo()]
    assert not [n for n in nomi if n in finale.lower()], finale


# Codice gia' noto: il modello usa direttamente get_item, senza cercare, e dice che e' esaurito.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_dettaglio(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Dammi i dettagli di PRD004")
    richieste, _ = _richieste_e_risultati(out)
    assert "get_item" in richieste, out["messages"]
    assert "search_catalog" not in richieste, richieste
    assert "jeans" in finale.lower() and "esaurit" in finale.lower(), finale


# Elenco completo di una categoria: il modello richiama search_catalog con max_results >= 10
# e nella risposta compaiono tutti i 10 prodotti (per codice o per nome).
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_elenco_completo(tools_mcp):
    # 10 prodotti Casa & Cucina, predefinito 5: l'avviso "Mostrati 5 di 10" fa richiamare il tool
    out, finale = _agente_mcp(tools_mcp, "Che prodotti avete per casa e cucina?")
    assert any(a.get("max_results", 0) >= 10 for a in _argomenti(out, "search_catalog")), \
        out["messages"]
    codici = ["PRD005", "PRD006", "PRD015", "PRD016", "PRD025", "PRD026", "PRD035", "PRD036",
              "PRD045", "PRD046"]
    nomi = ["Moka", "Frullatore", "Coltelli", "Bollitore", "Padella", "Tostapane", "Panni",
            "Bilancia", "Contenitori", "Macchina"]
    assert all(c in finale or n in finale for c, n in zip(codici, nomi)), finale


# --- prove reali delle note persistenti (server MCP mcp_note), agente unico ---

# Anche queste prove sono reali: saltate senza LM Studio attivo e RUN_LM_STUDIO=1.
# Ognuna usa un archivio SQLite nuovo in tmp_path, mai quello vero dell'utente.

# Supporto: agente vero con l'archivio indicato; "conferma" decide la risposta alla domanda
# di conferma prima di un'eliminazione (al posto dell'utente).
def _grafo_note(monkeypatch, archivio, conferma=None):
    """Agente vero con un archivio delle note temporaneo (strumenti caricati di nuovo, non in
    cache, perche' NOTE_DB va passato al processo del server note)."""
    from app.cli import carica_strumenti
    from app.llm import build_llm
    monkeypatch.setenv("NOTE_DB", str(archivio))
    impostazioni = load_settings()
    strumenti = carica_strumenti()
    return build_graph(build_llm(impostazioni, strumenti), impostazioni.max_steps,
                       strumenti=strumenti, conferma=conferma)


def _chiamate_a(out, nome):
    """Argomenti di ogni chiamata del modello al tool `nome`."""
    return [c["args"] for m in out["messages"] if isinstance(m, AIMessage)
            for c in m.tool_calls if c["name"] == nome]


# "Ricordami di...": il modello chiama add_note una volta sola e la nota finisce nell'archivio.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_ricordami(monkeypatch, tmp_path):
    from mcp_note.archivio import elenca
    archivio = tmp_path / "note.sqlite"
    out = _grafo_note(monkeypatch, archivio).invoke(
        _stato("Ricordami di consegnare il report venerdì"))
    assert len(_chiamate_a(out, "add_note")) == 1, out["messages"]  # una sola chiamata
    # controllo diretto sull'archivio: una nota che parla del report
    note, totale = elenca(10, archivio)
    assert totale == 1 and "report" in note[0]["testo"].lower(), note


# Eliminare una nota che non esiste: il tool lo dice e nessuna nota viene cancellata.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_id_inesistente(monkeypatch, tmp_path):
    from mcp_note.archivio import aggiungi, elenca
    archivio = tmp_path / "note.sqlite"
    # preparazione: una nota vera nell'archivio, con conferma sempre "si'"
    aggiungi("nota da tenere", archivio)
    out = _grafo_note(monkeypatch, archivio, conferma=lambda *_: True).invoke(
        _stato("Elimina la nota 99"))
    _, risultati = _richieste_e_risultati(out)
    assert any("non esiste" in r for r in risultati), out["messages"]
    assert elenca(10, archivio)[1] == 1  # nessuna eliminazione


# Conferma prima di eliminare: con "no" la nota resta, con "si'" sparisce. Due casi:
# (risposta alla conferma, la nota resta?).
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
@pytest.mark.parametrize("risposta, resta", [(False, True), (True, False)])
def test_prova_reale_note_conferma(monkeypatch, tmp_path, risposta, resta):
    from mcp_note.archivio import aggiungi, elenca
    archivio = tmp_path / "note.sqlite"
    nota = aggiungi("comprare il latte", archivio)
    # la conferma finta registra cosa le e' stato chiesto e restituisce la risposta del caso
    chiesto = []
    out = _grafo_note(monkeypatch, archivio,
                      conferma=lambda nome, args: chiesto.append(args) or risposta).invoke(
        _stato(f"Elimina la nota {nota['id']}"))
    assert chiesto, f"conferma mai chiesta: {out['messages']}"
    ancora = [n["id"] for n in elenca(10, archivio)[0]]
    assert (nota["id"] in ancora) is resta, ancora


# "Quali note ho?": il modello chiama list_notes e riporta entrambe le note.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_elenco(monkeypatch, tmp_path):
    from mcp_note.archivio import aggiungi
    archivio = tmp_path / "note.sqlite"
    aggiungi("pagare la bolletta", archivio)
    aggiungi("chiamare il dentista", archivio)
    out = _grafo_note(monkeypatch, archivio).invoke(_stato("Quali note ho?"))
    assert _chiamate_a(out, "list_notes"), out["messages"]
    finale = out["messages"][-1].content.lower()
    assert "bolletta" in finale and "dentista" in finale, finale


# Persistenza: una nota salvata si ritrova dopo un "riavvio" (agente nuovo, stesso archivio).
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_riavvio(monkeypatch, tmp_path):
    archivio = tmp_path / "note.sqlite"
    _grafo_note(monkeypatch, archivio).invoke(_stato("Ricordami di comprare il latte"))
    # "riavvio": strumenti e grafo nuovi, stesso archivio
    out = _grafo_note(monkeypatch, archivio).invoke(_stato("Quali note ho?"))
    assert "latte" in out["messages"][-1].content.lower(), out["messages"]


# nomi tecnici degli strumenti: non devono comparire nelle risposte all'utente
NOMI_STRUMENTI = ("tooltime", "toolconvert", "toolcalc", "tooldate", "search_catalog",
                  "get_item", "add_note", "list_notes", "delete_note")


# Richiesta di eliminare senza dire quale nota: il modello legge l'elenco, chiede in modo
# naturale (senza nomi di tool) e non elimina nulla.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
@pytest.mark.parametrize("domanda", ["Voglio cancellare una nota", "Elimina una nota"])
def test_prova_reale_note_senza_id_risposta_naturale(monkeypatch, tmp_path, domanda):
    from mcp_note.archivio import aggiungi, elenca
    archivio = tmp_path / "note.sqlite"
    aggiungi("comprare il latte", archivio)
    aggiungi("consegnare il report venerdì", archivio)
    out = _grafo_note(monkeypatch, archivio, conferma=lambda *_: False).invoke(_stato(domanda))
    finale = out["messages"][-1].content
    assert _chiamate_a(out, "list_notes"), out["messages"]  # l'elenco lo legge l'assistente
    assert not [n for n in NOMI_STRUMENTI if n in finale], finale  # nessun nome di tool
    assert elenca(10, archivio)[1] == 2  # niente eliminato senza ID e conferma


# --- prove reali del meteo (esercizio 6): servono LM Studio E la rete (Open-Meteo) ---
# I dati meteo cambiano: si controllano forma e contenuti, non i valori.

# tutti i 10 nomi di strumenti, compreso il meteo
NOMI_STRUMENTI_METEO = NOMI_STRUMENTI + ("get_weather",)


# Supporto: fa la domanda all'agente vero e restituisce lo stato e il testo visto dall'utente.
def _agente_meteo(monkeypatch, tmp_path, domanda):
    """Agente vero (10 strumenti) con un contatore del meteo temporaneo; risposta non vuota,
    senza asterischi, senza LaTeX e senza nomi dei tool."""
    from app.cli import FiltroMarkdown, carica_strumenti
    from app.llm import build_llm
    monkeypatch.setenv("METEO_CONTATORE", str(tmp_path / "meteo.sqlite"))  # limite vero intatto
    monkeypatch.delenv("CITTA_PREDEFINITA", raising=False)  # citta' predefinita: Roma
    impostazioni = load_settings()
    strumenti = carica_strumenti()
    grafo = build_graph(build_llm(impostazioni, strumenti), impostazioni.max_steps,
                        strumenti=strumenti)
    out = grafo.invoke(_stato(domanda))
    finale = out["messages"][-1].content
    # controlli comuni a tutte le prove del meteo
    assert finale.strip(), f"risposta vuota: {out['messages']}"
    filtro = FiltroMarkdown()  # come la CLI: l'utente vede il testo dopo il filtro
    visto = filtro.aggiungi(finale) + filtro.fine()
    assert "*" not in visto and "$" not in visto, visto
    assert not [n for n in NOMI_STRUMENTI_METEO if n in visto], visto
    return out, visto


# Le prove seguenti sono saltate senza LM Studio attivo e RUN_LM_STUDIO=1; servono anche
# la rete. Ognuna: domanda, controllo degli argomenti di get_weather e della risposta.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_citta(monkeypatch, tmp_path):
    """Meteo attuale di una citta': get_weather chiamato, temperatura con unita'."""
    out, finale = _agente_meteo(monkeypatch, tmp_path, "Che tempo fa a Milano?")
    chiamate = _chiamate_a(out, "get_weather")
    assert chiamate and "milano" in chiamate[0].get("city", "").lower(), out["messages"]
    assert "°C" in finale or "gradi" in finale.lower(), finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_oggi_predefinita(monkeypatch, tmp_path):
    """"Che meteo è oggi?" senza citta': citta' predefinita (Roma) e days=1."""
    out, finale = _agente_meteo(monkeypatch, tmp_path, "Che meteo è oggi?")
    chiamate = _chiamate_a(out, "get_weather")
    assert chiamate, out["messages"]
    assert chiamate[0].get("city", "") in ("", "Roma"), chiamate
    assert chiamate[0].get("days") == 1 or chiamate[0].get("date", "").lower() == "oggi", chiamate
    assert "roma" in finale.lower(), finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_prossimi_giorni(monkeypatch, tmp_path):
    """"Prossimi 3 giorni": days 3 o 4 (oggi compreso o no), previsioni nella risposta."""
    out, finale = _agente_meteo(monkeypatch, tmp_path,
                                "Quali sono le previsioni dei prossimi 3 giorni a Torino?")
    chiamate = _chiamate_a(out, "get_weather")
    assert chiamate and chiamate[0].get("days") in (3, 4), chiamate
    assert "torino" in finale.lower(), finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_oltre_sette_giorni(monkeypatch, tmp_path):
    """Oltre 7 giorni: lo dice (con o senza chiamare il tool) e non inventa temperature."""
    out, finale = _agente_meteo(monkeypatch, tmp_path,
                                "Che tempo farà a Napoli tra 30 giorni?")
    _, risultati = _richieste_e_risultati(out)
    # il modello puo' rispondere da solo grazie alla regola dei 7 giorni nel prompt
    assert (any("Nessuna previsione affidabile" in r for r in risultati)
            or "7 giorni" in finale), out["messages"]
    assert "°C" not in finale, finale  # nessun valore inventato


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_citta_ambigua(monkeypatch, tmp_path):
    """San Giovanni e' ambigua: la risposta dichiara le alternative o chiede quale."""
    out, finale = _agente_meteo(monkeypatch, tmp_path, "Che tempo fa a San Giovanni?")
    assert _chiamate_a(out, "get_weather"), out["messages"]
    assert any(p in finale.lower() for p in ("pordenone", "quale", "altre")), finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_citta_estera(monkeypatch, tmp_path):
    """Londra: il meteo copre solo l'Italia, nessuna temperatura inventata."""
    out, finale = _agente_meteo(monkeypatch, tmp_path, "Che tempo fa a Londra?")
    # con o senza chiamata al tool: conta che dica che il meteo copre solo l'Italia
    assert "ital" in finale.lower(), finale  # "solo l'Italia", "città italiane"
    assert "°C" not in finale, finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo, la rete e RUN_LM_STUDIO=1")
def test_prova_reale_meteo_citta_inesistente(monkeypatch, tmp_path):
    """Citta' inesistente: la risposta dice che non e' stata trovata."""
    out, finale = _agente_meteo(monkeypatch, tmp_path, "Che tempo fa a Xyzqwk?")
    _, risultati = _richieste_e_risultati(out)
    assert any("Città non trovata" in r for r in risultati), out["messages"]
    assert any(p in finale.lower() for p in ("trov", "esiste", "conosc")), finale
