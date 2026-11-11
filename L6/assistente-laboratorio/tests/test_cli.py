# test della CLI: chat da terminale con grafo reale e modelli finti
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError

from app import cli
from app.adattatore_mcp import ErroreMCP, InfoArgomento, InfoPrompt
from app.cli import MSG_CONNESSIONE, main
from app.comandi import MSG_ERRORE_PROMPT, MSG_NESSUN_PROMPT, elenco_prompt
from app.config import Ambito
from app.graph import build_graph
from app.router import DecisioneRouter
from app.revisore import DecisioneRevisore
from tests.finti import ModelloFinto, RevisoreFinto, RiassuntoFinto, RouterFinto

AMBITO = Ambito(descrizione="Solo ora.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="ora")
FUORI = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
OK = DecisioneRevisore(motivo="risponde", coerente=True)
# prompt pubblicato dal server finto e testo che il server restituirebbe
SPIEGA = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                          InfoArgomento("livello", False)))
TESTO_SPIEGA = "Spiegami MCP. Livello base: parole semplici."
elenchi = []  # chiamate dell'elenco finto dei prompt (avvio)


# finto prompts/get: registra le richieste e restituisce i messaggi preparati (o solleva l'errore)
class OttieniFinto:
    def __init__(self, risultato=None):
        self.risultato = risultato if risultato is not None else [HumanMessage(TESTO_SPIEGA)]
        self.chiamate = []

    def __call__(self, nome, argomenti):
        self.chiamate.append((nome, argomenti))
        if isinstance(self.risultato, Exception):
            raise self.risultato
        return [m.model_copy() for m in self.risultato]


# esegue la chat con le righe date e restituisce cio' che e' stato stampato
def _chat(righe, agente, router, revisore=None, grafo=None, prompts=None, ottieni=None):
    input_righe = iter(righe)

    # finto input(): restituisce le righe in ordine, poi EOF come Ctrl+Z
    def leggi(_prompt=""):
        try:
            return next(input_righe)
        except StopIteration:
            raise EOFError

    stampato = []
    revisore = revisore or RevisoreFinto([OK])
    # grafo gia' costruito dal test (per esempio con una soglia del riassunto bassa)
    if grafo is None:
        grafo = build_graph(agente, router, revisore, RiassuntoFinto(["riassunto"]), AMBITO)
    main(grafo, input_fn=leggi, output_fn=stampato.append, prompts=prompts, ottieni=ottieni)
    return "\n".join(stampato)


# Verifica che la CLI mostri la risposta dell'agente a una domanda in ambito.
def test_domanda_in_ambito_e_risposta():
    out = _chat(["Che ore sono?", "esci"], ModelloFinto([AIMessage("Sono le 10")]),
                RouterFinto([IN_AMBITO]))
    assert "Assistente: Sono le 10" in out


# Verifica che la CLI mostri la frase di rifiuto del file dell'ambito.
def test_domanda_fuori_ambito_rifiutata():
    out = _chat(["Carbonara?", "esci"], ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]))
    assert "Assistente: " + AMBITO.rifiuto in out


# Verifica che il secondo turno riceva la cronologia del primo.
def test_cronologia_passata_al_turno_successivo():
    agente = ModelloFinto([AIMessage("Sono le 10"), AIMessage("Prego")])
    _chat(["Che ore sono?", "grazie", "esci"], agente, RouterFinto([IN_AMBITO]))
    testi = [m.content for m in agente.chiamate[1]]
    assert "Che ore sono?" in testi and "Sono le 10" in testi and "grazie" in testi


# Verifica LM Studio spento durante il router: messaggio, domanda fuori dalla cronologia,
# chat aperta.
def test_connessione_assente_durante_il_router():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    agente = ModelloFinto([AIMessage("Risposta a b")])
    out = _chat(["a", "b", "esci"], agente, RouterFinto([errore, IN_AMBITO]))
    assert MSG_CONNESSIONE in out
    assert "Assistente: Risposta a b" in out
    # la domanda fallita non entra nella cronologia
    assert "a" not in [m.content for m in agente.chiamate[0]]


# Verifica l'uscita con EXIT (maiuscole indifferenti) e con la fine dell'input.
@pytest.mark.parametrize("righe", [["EXIT"], []])
def test_uscita_con_exit_e_eof(righe):
    agente = ModelloFinto([AIMessage("x")])
    _chat(righe, agente, RouterFinto([IN_AMBITO]))  # [] = EOF subito
    assert agente.chiamate == []


# Verifica che LOG_HTTP spento zittisca sia httpx sia httpx2.
def test_log_http_spegne_httpx_e_httpx2():
    # il client OpenAI scrive le richieste dal logger httpx2 (visto con LM Studio vero)
    import logging
    cli.imposta_log(log_http=False, log_grafo=True)
    assert logging.getLogger("httpx").level == logging.CRITICAL
    assert logging.getLogger("httpx2").level == logging.CRITICAL
    cli.imposta_log()  # rimette i valori predefiniti


# Verifica che l'avvio con configurazione mancante si fermi con un messaggio chiaro.
def test_configurazione_non_valida(monkeypatch):
    monkeypatch.delenv("LM_BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="Configurazione non valida"):
        cli.avvia()


# Verifica che dopo un rifiuto del revisore l'utente veda solo la risposta finale e che il turno
# successivo non riceva il messaggio [Revisore] ne' la bozza.
def test_turno_successivo_senza_revisore():
    no = DecisioneRevisore(motivo="parziale", coerente=False)
    agente = ModelloFinto([AIMessage("bozza"), AIMessage("completa"), AIMessage("prego")])
    out = _chat(["domanda", "grazie", "esci"], agente, RouterFinto([IN_AMBITO]),
                RevisoreFinto([no, OK, OK]))
    assert "Assistente: completa" in out
    assert "[Revisore]" not in out and "bozza" not in out
    secondo_turno = agente.chiamate[2]
    assert all(getattr(m, "name", None) != "revisore" for m in secondo_turno)
    assert "bozza" not in [m.content for m in secondo_turno]


# Verifica che i log del revisore siano accesi con LOG_GRAFO.
def test_imposta_log_accende_il_revisore():
    import logging
    cli.imposta_log()
    assert logging.getLogger("revisore").level == logging.INFO


# Verifica che il riassunto passi da un turno al successivo: al quarto turno non si riassume, ma
# l'agente deve ancora ricevere il riassunto fatto al terzo.
def test_riassunto_passato_al_turno_successivo():
    agente = ModelloFinto([AIMessage("r1"), AIMessage("r2"), AIMessage("r3"), AIMessage("r4")])
    grafo = build_graph(agente, RouterFinto([IN_AMBITO]), RevisoreFinto([OK]),
                        RiassuntoFinto(["Si chiama Luigi."]), AMBITO, soglia_riassunto=3,
                        messaggi_recenti=1)
    _chat(["Mi chiamo Luigi", "d2", "d3", "d4", "esci"], agente, None, grafo=grafo)
    sistema_quarto_turno = agente.chiamate[3][0].content
    assert "Riassunto della conversazione precedente: Si chiama Luigi." in sistema_quarto_turno


# Verifica che i log del riassunto siano accesi con LOG_GRAFO.
def test_imposta_log_accende_il_riassunto():
    import logging
    cli.imposta_log()
    assert logging.getLogger("riassunto").level == logging.INFO


# sostituisce server MCP e modelli di LM Studio per provare avvia() e prepara_agente();
# restituisce il contatore delle letture della resource
def _finti_per_avvio(monkeypatch, testo='{"lingua": "inglese", "fuso": "America/New_York"}',
                     server_ok=True):
    from app import adattatore_mcp, llm
    from tests.finti import tooltime_finto
    letture = []
    elenchi.clear()

    # discovery finta: un tooltime finto, oppure il server che non parte
    def carica():
        if not server_ok:
            raise adattatore_mcp.ErroreMCP("mcp_assistente.server: non parte")
        return [tooltime_finto([])]

    # lettura finta della resource: conta le chiamate
    def leggi():
        letture.append(1)
        return testo

    monkeypatch.setattr(adattatore_mcp, "carica_strumenti", carica)
    monkeypatch.setattr(adattatore_mcp, "leggi_preferenze", leggi)

    # elenco finto dei prompt (prompts/list): conta le chiamate
    def elenca():
        elenchi.append(1)
        return [SPIEGA]

    monkeypatch.setattr(adattatore_mcp, "elenca_prompt", elenca)
    monkeypatch.setattr(llm, "build_llm", lambda s, strumenti: ModelloFinto([AIMessage("ok")]))
    monkeypatch.setattr(llm, "build_router_llm", lambda s, a: RouterFinto([IN_AMBITO]))
    monkeypatch.setattr(llm, "build_revisore_llm", lambda s: RevisoreFinto([OK]))
    monkeypatch.setattr(llm, "build_riassunto_llm", lambda s: RiassuntoFinto(["riassunto"]))
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "google/gemma-4-e2b")
    return letture


# Verifica che prepara_agente legga la resource una volta e restituisca strumenti e preferenze.
def test_prepara_agente_legge_le_preferenze_una_volta(monkeypatch):
    letture = _finti_per_avvio(monkeypatch)
    strumenti, preferenze, prompts = cli.prepara_agente("Europe/Rome")
    assert [t.name for t in strumenti] == ["tooltime"]
    assert prompts == [SPIEGA] and len(elenchi) == 1
    assert (preferenze.lingua, preferenze.fuso) == ("inglese", "America/New_York")
    assert len(letture) == 1


# Verifica che senza server MCP la chat parta con zero strumenti, predefiniti e 2 avvisi.
def test_prepara_agente_server_non_disponibile(monkeypatch, caplog):
    import logging
    from app.preferenze import predefinite
    letture = _finti_per_avvio(monkeypatch, server_ok=False)
    with caplog.at_level(logging.WARNING):
        strumenti, preferenze, prompts = cli.prepara_agente("Europe/Rome")
    assert strumenti == [] and preferenze == predefinite("Europe/Rome") and prompts == []
    assert elenchi == []  # il server non parte: nessun prompts/list
    avvisi = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("nessuno strumento" in a for a in avvisi)
    assert any("preferenze predefinite" in a for a in avvisi)
    assert letture == []  # il server non parte: la resource non si legge


# Verifica che in una sessione con piu' turni la resource si legga una sola volta.
def test_una_lettura_in_piu_turni(monkeypatch):
    letture = _finti_per_avvio(monkeypatch)
    righe = iter(["Che ore sono?", "E adesso?", "Grazie", "esci"])
    stampato = []
    cli.avvia(input_fn=lambda _p="": next(righe), output_fn=stampato.append)
    assert len(letture) == 1
    assert stampato.count("Assistente: ok") == 3


# Verifica che i log di MCP e delle preferenze siano accesi con LOG_GRAFO.
def test_imposta_log_accende_mcp_e_preferenze():
    import logging
    cli.imposta_log()
    assert logging.getLogger("mcp").level == logging.INFO
    assert logging.getLogger("preferenze").level == logging.INFO


# --- comandi dei prompt (step 5) ---

# Verifica che /prompts mostri l'elenco senza chiedere prompt al server ne' chiamare il modello.
def test_prompts_mostra_l_elenco_senza_chiamate():
    agente, ottieni = ModelloFinto([AIMessage("x")]), OttieniFinto()
    out = _chat(["/prompts", "esci"], agente, RouterFinto([IN_AMBITO]), prompts=[SPIEGA],
                ottieni=ottieni)
    assert elenco_prompt([SPIEGA]) in out
    assert ottieni.chiamate == [] and agente.chiamate == []


# Verifica che un /prompt valido chieda il prompt al server e passi i messaggi al grafo.
def test_prompt_valido_va_al_grafo():
    agente, ottieni = ModelloFinto([AIMessage("ok")]), OttieniFinto()
    out = _chat(['/prompt spiega argomento=MCP livello=base', "esci"], agente,
                RouterFinto([IN_AMBITO]), prompts=[SPIEGA], ottieni=ottieni)
    assert ottieni.chiamate == [("spiega", {"argomento": "MCP", "livello": "base"})]
    assert "(prompt spiega: 1 messaggio dal server)" in out
    assert "Assistente: ok" in out
    domande = [m for m in agente.chiamate[0] if isinstance(m, HumanMessage)]
    assert domande[-1].content == TESTO_SPIEGA


# Verifica che dopo un prompt il turno successivo veda il messaggio del prompt e la risposta.
def test_prompt_poi_domanda_cronologia_completa():
    agente = ModelloFinto([AIMessage("spiegazione"), AIMessage("prego")])
    _chat(["/prompt spiega argomento=MCP", "grazie", "esci"], agente, RouterFinto([IN_AMBITO]),
          prompts=[SPIEGA], ottieni=OttieniFinto())
    testi = [m.content for m in agente.chiamate[1]]
    assert TESTO_SPIEGA in testi and "spiegazione" in testi and "grazie" in testi


# Verifica che ogni comando sbagliato dia un messaggio senza server ne' modello, e che la chat
# continui (la domanda dopo riceve risposta).
@pytest.mark.parametrize("riga", ["/xyz", "/prompt", "/prompt spiega livello=base",
                                  "/prompt spiega x"])
def test_errori_senza_grafo_ne_server(riga):
    agente, ottieni = ModelloFinto([AIMessage("ok")]), OttieniFinto()
    out = _chat([riga, "Che ore sono?", "esci"], agente, RouterFinto([IN_AMBITO]),
                prompts=[SPIEGA], ottieni=ottieni)
    assert ottieni.chiamate == [] and len(agente.chiamate) == 1
    assert riga not in [m.content for m in agente.chiamate[0]]
    assert "Assistente: ok" in out


# Verifica che un errore del server su prompts/get dia il messaggio fisso con il motivo.
def test_errore_del_server_sul_prompt():
    agente = ModelloFinto([AIMessage("x")])
    ottieni = OttieniFinto(ErroreMCP("livello non valido: 'pippo'"))
    out = _chat(["/prompt spiega argomento=MCP livello=pippo", "esci"], agente,
                RouterFinto([IN_AMBITO]), prompts=[SPIEGA], ottieni=ottieni)
    assert MSG_ERRORE_PROMPT.format(motivo="livello non valido: 'pippo'") in out
    assert agente.chiamate == []


# Verifica che con LM Studio spento durante il turno del prompt i suoi messaggi non entrino nella
# cronologia.
def test_errore_lm_studio_dopo_prompt_cronologia_invariata():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    agente = ModelloFinto([AIMessage("ok")])
    out = _chat(["/prompt spiega argomento=MCP", "Che ore sono?", "esci"], agente,
                RouterFinto([errore, IN_AMBITO]), prompts=[SPIEGA], ottieni=OttieniFinto())
    assert MSG_CONNESSIONE in out
    assert TESTO_SPIEGA not in [m.content for m in agente.chiamate[0]]


# Verifica che senza server (elenco vuoto) i comandi lo dicano.
def test_server_non_avviato_nessun_prompt():
    out = _chat(["/prompts", "esci"], ModelloFinto([AIMessage("x")]), RouterFinto([IN_AMBITO]),
                prompts=[], ottieni=OttieniFinto())
    assert MSG_NESSUN_PROMPT in out


# Verifica che il BOM della pipe di PowerShell non cambi le righe: /prompts resta un comando,
# esci chiude la chat senza chiamare il modello.
def test_bom_iniziale():
    agente = ModelloFinto([AIMessage("x")])
    out = _chat(["\ufeff\ufeff/prompts", "\ufeffesci", "Che ore sono?"], agente,
                RouterFinto([IN_AMBITO]), prompts=[SPIEGA], ottieni=OttieniFinto())
    assert elenco_prompt([SPIEGA]) in out
    assert agente.chiamate == []



# Verifica la pipe di PowerShell senza PYTHONIOENCODING: stdin letto in cp1252 con il BOM in
# testa. avvia legge la pipe in UTF-8, cosi' il BOM si riconosce e /prompts resta un comando.
def test_pipe_in_cp1252_con_bom(monkeypatch):
    import io
    import sys
    _finti_per_avvio(monkeypatch)
    pipe = io.TextIOWrapper(io.BytesIO("\ufeff/prompts\nesci\n".encode("utf-8")),
                            encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", pipe)
    stampato = []
    cli.avvia(output_fn=stampato.append)
    assert elenco_prompt([SPIEGA]) in stampato
    assert not any(s.startswith("Assistente:") for s in stampato)  # nessuna domanda al grafo
