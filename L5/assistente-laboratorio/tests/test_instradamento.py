import functools
import logging
import os
from datetime import datetime, timezone

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import tools
from app.cli import main
from app.config import load_settings
from app.graph import build_graph, instrada


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


@functools.cache
def _strumenti_agente():
    """Gli strumenti dell'agente vero (app.cli): 4 locali e HTTP + i tool del server MCP."""
    from app.cli import carica_strumenti
    return carica_strumenti()


def _grafo_reale(impostazioni):
    """Lo stesso agente di app.cli: tutti gli strumenti, SYSTEM_PROMPT, 8192 token."""
    from app.llm import build_llm
    strumenti = _strumenti_agente()
    return build_graph(build_llm(impostazioni, strumenti), impostazioni.max_steps,
                       strumenti=strumenti)


def _chiamata(nome="tooltime", args=None, id_="c1"):
    return AIMessage("", tool_calls=[
        {"name": nome, "args": args or {"fuso": "Asia/Tokyo"}, "id": id_}])


def _stato(testo="Che ore sono a Tokyo?"):
    return {"messages": [HumanMessage(testo)], "steps": 0}


@pytest.fixture(autouse=True)
def _orologio_fisso(monkeypatch):
    monkeypatch.setattr(
        tools, "_adesso",
        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))


def test_instrada_a_strumenti():
    con = {"messages": [_chiamata()], "steps": 0}
    senza = {"messages": [AIMessage("ciao")], "steps": 0}
    al_limite = {"messages": [_chiamata()], "steps": 5}
    assert instrada(con) == "strumenti"
    assert instrada(senza) == "__end__"
    assert instrada(al_limite) == "limite"


def test_risultato_torna_al_modello():
    llm = ModelloCopione([_chiamata(), AIMessage("A Tokyo sono le 20:00.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "A Tokyo sono le 20:00."
    ricevuto = llm.chiamate[1][-1]
    assert isinstance(ricevuto, ToolMessage)
    assert "ore 20 in punto" in ricevuto.content
    assert out["steps"] == 1


def test_limite_passaggi():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=3).invoke(_stato())
    assert out["steps"] == 3
    assert len(llm.chiamate) == 4
    ultimo = out["messages"][-1]
    assert isinstance(ultimo, AIMessage) and not ultimo.tool_calls
    assert "limite" in ultimo.content and "3" in ultimo.content


def test_limite_chiude_le_tool_calls_pendenti():
    llm = ModelloCopione([_chiamata(), _chiamata(id_="c2"), AIMessage("Ok, ripartiamo.")])
    grafo = build_graph(llm, max_steps=1)
    primo = grafo.invoke(_stato())
    # modello chiede lo strumento (eseguito), poi lo richiede: limite raggiunto
    secondo = grafo.invoke({"messages": primo["messages"] + [HumanMessage("e ora?")],
                            "steps": 0})
    assert secondo["messages"][-1].content == "Ok, ripartiamo."
    inviati = llm.chiamate[-1]
    richieste = {c["id"] for m in inviati if isinstance(m, AIMessage) for c in m.tool_calls}
    risposte = {m.tool_call_id for m in inviati if isinstance(m, ToolMessage)}
    assert richieste == {"c1", "c2"}
    assert richieste <= risposte  # nessuna tool_call senza ToolMessage


def test_log_chiamata_strumento(caplog):
    llm = ModelloCopione([_chiamata(), AIMessage("fatto")])
    with caplog.at_level(logging.INFO, logger="app.graph"):
        build_graph(llm).invoke(_stato())
    testo = [r.getMessage() for r in caplog.records]
    prima = next(i for i, t in enumerate(testo) if "tooltime" in t and "Asia/Tokyo" in t)
    dopo = next(i for i, t in enumerate(testo) if "ore 20 in punto" in t)
    assert prima < dopo


def test_parte_passata_dal_modello_arriva_allo_strumento():
    llm = ModelloCopione([_chiamata(args={"fuso": "Asia/Tokyo", "parte": "ora"}),
                          AIMessage("Sono le 20:00.")])
    build_graph(llm).invoke(_stato())
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "Tokyo: sono le ore 20 in punto"


def test_parte_non_valida_e_un_errore_gestito():
    llm = ModelloCopione([_chiamata(args={"fuso": "Asia/Tokyo", "parte": "minuti"}),
                          AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage) and errore.status == "error"
    assert out["messages"][-1].content == "Non posso."


def test_vecchio_nome_non_e_piu_uno_strumento():
    llm = ModelloCopione([_chiamata("ora_corrente"), AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage)
    assert errore.status == "error"
    assert out["messages"][-1].content == "Non posso."


def test_strumento_sconosciuto():
    llm = ModelloCopione([_chiamata("non_esiste", {"x": 1}), AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato())
    assert out["messages"][-1].content == "Non posso."
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage)
    assert errore.status == "error"


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_strumento_lm_studio():
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Che ore sono a Tokyo?"))
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "tooltime" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"


def test_cli_usa_max_steps():
    llm = ModelloCopione([_chiamata()])  # chiede sempre lo strumento
    righe = iter(["Che ore sono a Tokyo?", "exit"])
    uscite = []
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append,
         llm=llm, max_steps=1, stream=False)
    # un solo passaggio con lo strumento, poi il limite
    assert len(llm.chiamate) == 2
    assert any("limite di 1 passaggi" in u for u in uscite)


CONV = {"valore": 10, "da": "miglia", "a": "km"}


def test_convertitore_eseguito_dal_grafo():
    llm = ModelloCopione([_chiamata("toolconvert", CONV), AIMessage("Sono 16 km.")])
    out = build_graph(llm).invoke(_stato("Quanti km sono 10 miglia?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "10 miglia = 16,0934 chilometri"
    assert out["messages"][-1].content == "Sono 16 km." and out["steps"] == 1


def test_convertitore_argomenti_non_validi():
    llm = ModelloCopione([_chiamata("toolconvert", {"valore": "tanti", "da": "m", "a": "km"}),
                          AIMessage("Non posso.")])
    out = build_graph(llm).invoke(_stato("Converti tanti metri"))
    errore = llm.chiamate[1][-1]
    assert isinstance(errore, ToolMessage) and errore.status == "error"
    assert "valore" in errore.content and "valid number" in errore.content
    assert out["messages"][-1].content == "Non posso."


def test_convertitore_rispetta_max_steps():
    llm = ModelloCopione([_chiamata("toolconvert", CONV)])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=2).invoke(_stato("Quanti km sono 10 miglia?"))
    assert out["steps"] == 2
    assert llm.chiamate[1][-1].content == "10 miglia = 16,0934 chilometri"
    assert "limite di 2 passaggi" in out["messages"][-1].content


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_convertitore_lm_studio():
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quanti chilometri sono 10 miglia?"))
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "toolconvert" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    assert any("16,0934" in r for r in risultati), risultati
    finale = out["messages"][-1].content
    assert any(x in finale for x in ("16,0934", "16.0934", "16,09", "16.09")), finale


# --- calcolatrice sicura: il wrapper HTTP passa dal grafo come gli altri strumenti ---

CALC = {"espressione": "(3+4)^2/7"}


def _servizio_finto(monkeypatch, handler):
    monkeypatch.setattr(tools, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def test_calcolatrice_eseguita_dal_grafo(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(
        200, json={"espressione": "(3+4)^2/7", "risultato": 7}))
    llm = ModelloCopione([_chiamata("toolcalc", CALC), AIMessage("Fa 7.")])
    out = build_graph(llm).invoke(_stato("Quanto fa (3+4)^2/7?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content == "(3+4)^2/7 = 7"
    assert out["messages"][-1].content == "Fa 7." and out["steps"] == 1


def test_calcolatrice_spenta_non_blocca_il_grafo(monkeypatch):
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


def test_calcolatrice_rispetta_max_steps(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(
        200, json={"espressione": "(3+4)^2/7", "risultato": 7}))
    llm = ModelloCopione([_chiamata("toolcalc", CALC)])  # chiede sempre lo strumento
    out = build_graph(llm, max_steps=2).invoke(_stato("Quanto fa (3+4)^2/7?"))
    assert out["steps"] == 2
    assert "limite di 2 passaggi" in out["messages"][-1].content


@pytest.fixture
def servizio_vero(monkeypatch):
    """Servizio calcolatrice vero (uvicorn) in un thread, su una porta libera."""
    import socket
    import threading
    import time

    import uvicorn

    from servizio.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < limite, "il servizio non si e' avviato entro 10 secondi"
        time.sleep(0.05)
    monkeypatch.setenv("CALC_BASE_URL", f"http://127.0.0.1:{porta}")
    yield
    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_calcolatrice_lm_studio(servizio_vero):
    from app.llm import build_llm

    impostazioni = load_settings()
    out = _grafo_reale(impostazioni).invoke(
        _stato("Quanto fa (3+4)^2 / 7?"))
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    assert "toolcalc" in richieste, f"nessuna chiamata allo strumento: {out['messages']}"
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    assert any("= 7" in r for r in risultati), risultati
    finale = out["messages"][-1].content
    assert "7" in finale, finale
    assert "$" not in finale, f"risposta in LaTeX: {finale}"


# --- giorni e scadenze: il wrapper HTTP tooldate passa dal grafo come gli altri ---

GIORNO_NATALE = {
    "operazione": "giorno", "data": "2026-12-25", "giorno_settimana": "venerdì",
    "lavorativo": False, "fine_settimana": False, "festivita": ["Natale"],
    "avviso": "Calcolo indicativo, non ha valore legale."}


def test_date_eseguito_dal_grafo(monkeypatch):
    _servizio_finto(monkeypatch, lambda r: httpx.Response(200, json=GIORNO_NATALE))
    llm = ModelloCopione([_chiamata("tooldate", {"operazione": "giorno", "data": "natale"}),
                          AIMessage("Natale e' festivo.")])
    out = build_graph(llm).invoke(_stato("Natale e' lavorativo?"))
    risultato = llm.chiamate[1][-1]
    assert isinstance(risultato, ToolMessage)
    assert risultato.content.startswith("2026-12-25 (venerdì): festivo (Natale).")
    assert out["messages"][-1].content == "Natale e' festivo." and out["steps"] == 1


def test_date_servizio_spento_non_blocca_il_grafo(monkeypatch):
    def spento(request):
        raise httpx.ConnectError("rifiutata", request=request)
    _servizio_finto(monkeypatch, spento)
    llm = ModelloCopione([_chiamata("tooldate", {"operazione": "giorno", "data": "natale"}),
                          AIMessage("Servizio spento.")])
    out = build_graph(llm).invoke(_stato("Natale e' lavorativo?"))
    assert "non raggiungibile" in llm.chiamate[1][-1].content
    assert out["messages"][-1].content == "Servizio spento."


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


def _richieste_e_risultati(out):
    richieste = [c["name"] for m in out["messages"]
                 if isinstance(m, AIMessage) for c in m.tool_calls]
    risultati = [m.content for m in out["messages"] if isinstance(m, ToolMessage)]
    return richieste, risultati


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

@pytest.fixture(scope="module")
def tools_mcp():
    return _strumenti_agente()


def _agente_mcp(tools_mcp, domanda):
    out = _grafo_reale(load_settings()).invoke(_stato(domanda))
    finale = out["messages"][-1].content
    assert finale.strip(), f"risposta vuota: {out['messages']}"
    assert "$" not in finale, f"risposta in LaTeX: {finale}"
    return out, finale


def _argomenti(out, nome):
    return [c["args"] for m in out["messages"] if isinstance(m, AIMessage)
            for c in m.tool_calls if c["name"] == nome]


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_ricerca(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Avete qualcosa per il nuoto?")
    richieste, _ = _richieste_e_risultati(out)
    assert "search_catalog" in richieste, out["messages"]
    # il modello puo' parafrasare il nome ("occhialini da nuoto"): basta il codice o il nome
    assert "prd030" in finale.lower() or "occhialini" in finale.lower(), finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_sequenza(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Quanto costa lo smartphone?")
    richieste, _ = _richieste_e_risultati(out)
    assert "search_catalog" in richieste and "get_item" in richieste, out["messages"]
    assert richieste.index("search_catalog") < richieste.index("get_item"), richieste
    assert any(a.get("code", "").strip().upper() == "PRD001"
               for a in _argomenti(out, "get_item")), out["messages"]
    assert "499,99" in finale or "499.99" in finale, finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_vuoto(tools_mcp):
    from mcp_catalogo.catalogo import carica_catalogo

    out, finale = _agente_mcp(tools_mcp, "Avete dei pattini a rotelle?")
    richieste, risultati = _richieste_e_risultati(out)
    assert "search_catalog" in richieste, out["messages"]
    assert "[]" in risultati, risultati
    nomi = [p["nome"].lower() for p in carica_catalogo()]
    assert not [n for n in nomi if n in finale.lower()], finale


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_mcp_dettaglio(tools_mcp):
    out, finale = _agente_mcp(tools_mcp, "Dammi i dettagli di PRD004")
    richieste, _ = _richieste_e_risultati(out)
    assert "get_item" in richieste, out["messages"]
    assert "search_catalog" not in richieste, richieste
    assert "jeans" in finale.lower() and "esaurit" in finale.lower(), finale


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


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_ricordami(monkeypatch, tmp_path):
    from mcp_note.archivio import elenca
    archivio = tmp_path / "note.sqlite"
    out = _grafo_note(monkeypatch, archivio).invoke(
        _stato("Ricordami di consegnare il report venerdì"))
    assert len(_chiamate_a(out, "add_note")) == 1, out["messages"]  # una sola chiamata
    note, totale = elenca(10, archivio)
    assert totale == 1 and "report" in note[0]["testo"].lower(), note


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_id_inesistente(monkeypatch, tmp_path):
    from mcp_note.archivio import aggiungi, elenca
    archivio = tmp_path / "note.sqlite"
    aggiungi("nota da tenere", archivio)
    out = _grafo_note(monkeypatch, archivio, conferma=lambda *_: True).invoke(
        _stato("Elimina la nota 99"))
    _, risultati = _richieste_e_risultati(out)
    assert any("non esiste" in r for r in risultati), out["messages"]
    assert elenca(10, archivio)[1] == 1  # nessuna eliminazione


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
@pytest.mark.parametrize("risposta, resta", [(False, True), (True, False)])
def test_prova_reale_note_conferma(monkeypatch, tmp_path, risposta, resta):
    from mcp_note.archivio import aggiungi, elenca
    archivio = tmp_path / "note.sqlite"
    nota = aggiungi("comprare il latte", archivio)
    chiesto = []
    out = _grafo_note(monkeypatch, archivio,
                      conferma=lambda nome, args: chiesto.append(args) or risposta).invoke(
        _stato(f"Elimina la nota {nota['id']}"))
    assert chiesto, f"conferma mai chiesta: {out['messages']}"
    ancora = [n["id"] for n in elenca(10, archivio)[0]]
    assert (nota["id"] in ancora) is resta, ancora


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


@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_note_riavvio(monkeypatch, tmp_path):
    archivio = tmp_path / "note.sqlite"
    _grafo_note(monkeypatch, archivio).invoke(_stato("Ricordami di comprare il latte"))
    # "riavvio": strumenti e grafo nuovi, stesso archivio
    out = _grafo_note(monkeypatch, archivio).invoke(_stato("Quali note ho?"))
    assert "latte" in out["messages"][-1].content.lower(), out["messages"]


NOMI_STRUMENTI = ("tooltime", "toolconvert", "toolcalc", "tooldate", "search_catalog",
                  "get_item", "add_note", "list_notes", "delete_note")


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
