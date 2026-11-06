"""Agente unico: i 4 strumenti di prima (locali e HTTP) piu' i tool scoperti dal server MCP."""
# pytest, messaggi e decoratore @tool di LangChain
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

# il codice da verificare: CLI, adattatore MCP, configurazione, grafo, modello, strumenti
from app import cli
from app.adattatore_mcp import carica_tutti_mcp
from app.config import Settings
from app.graph import build_graph
from app.llm import SYSTEM_PROMPT, build_llm
from app.tools import STRUMENTI

# impostazioni finte: nessun LM Studio viene contattato in questi test
IMPOSTAZIONI = Settings(base_url="http://127.0.0.1:1234/v1", model="m", max_steps=5,
                        fuso_predefinito="Europe/Rome")
# i 4 strumenti non MCP, nell'ordine di STRUMENTI
NOMI_LOCALI = ["tooltime", "toolconvert", "toolcalc", "tooldate"]


# sostituisce il modello vero: risposte gia' scritte, nessuna rete
class ModelloCopione:
    """Modello finto: restituisce i messaggi in ordine e registra cosa riceve."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)  # le risposte del copione, in ordine
        self.chiamate = []  # i messaggi ricevuti a ogni chiamata, per i controlli

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)  # la prossima risposta del copione
        # l'ultima risposta si ripete (senza id, come un messaggio nuovo)
        return self.messaggi[0].model_copy(update={"id": None})


# stato iniziale del grafo con la sola domanda dell'utente
def _stato(testo):
    return {"messages": [HumanMessage(testo)], "steps": 0}


# risposta del modello che chiede di eseguire uno strumento
def _chiamata(nome, args, id_):
    return AIMessage("", tool_calls=[{"name": nome, "args": args, "id": id_}])


# tutti gli strumenti dell'agente (locali e MCP veri), caricati una volta per il modulo
@pytest.fixture(scope="module")
def tutti():
    return list(STRUMENTI) + carica_tutti_mcp()


# aggiungere MCP non cambia gli strumenti degli esercizi precedenti
def test_strumenti_locali_invariati():
    assert [t.name for t in STRUMENTI] == NOMI_LOCALI


# un solo SYSTEM_PROMPT con la regola dell'orologio e le regole del catalogo
def test_system_prompt_unico():
    # la regola dell'orologio resta, si aggiungono quelle del catalogo
    assert "chiama tooltime senza l'argomento fuso" in SYSTEM_PROMPT
    for parte in ("search_catalog", "get_item", "[]", "Mostrati N di M", "max_results=M",
                  "non dire mai che non puoi consultarlo"):
        assert parte in SYSTEM_PROMPT, parte


# la conferma della cancellazione la chiede il programma, non il modello
def test_system_prompt_conferma_del_programma():
    """Il modello non chiede lui la conferma: chiama delete_note e la chiede il programma
    (ritocco 2, autorizzato dall'utente il 2026-11-05)."""
    assert "Non chiedere tu la conferma: chiama subito delete_note" in SYSTEM_PROMPT


# per una domanda generica il modello cerca subito invece di chiedere chiarimenti
def test_system_prompt_ricerca_generica():
    """Domanda generica sul catalogo: cercare subito la parola principale, senza chiarimenti
    (ritocco 3, autorizzato dall'utente il 2026-11-05)."""
    assert "cerca subito con search_catalog la parola principale" in SYSTEM_PROMPT


# il prompt contiene tutte le regole del meteo: ogni frase cercata e' un pezzo di regola
def test_system_prompt_meteo():
    """Regole del meteo (esercizio 6, autorizzate dall'utente il 2026-11-05)."""
    # 2026-11-06: "domani" passa da days=2 a date="domani" e "tra/fra N giorni" va in date
    # (ritocchi autorizzati dall'utente: il modello usava days=N per "tra N giorni")
    for parte in ("get_weather", "senza city", "days=1", "date=\"domani\"",
                  "NON usare days", "date=\"tra 3 giorni\"", "presentatore",
                  "regione o provincia", "solo l'Italia", "non è raggiungibile",
                  "riprova domani", "7 giorni", "Città non trovata", "controllare il nome",
                  "chiama sempre get_weather"):
        assert parte in SYSTEM_PROMPT, parte


# il modello riceve 8192 token (contro le risposte vuote del ragionamento) e tutti i 10 tool
def test_build_llm_8192_token(tutti):
    llm = build_llm(IMPOSTAZIONI, tutti)  # nessuna chiamata: si costruisce solo l'oggetto
    assert llm.bound.max_tokens == 8192  # bound e' il modello, kwargs i tool collegati
    assert [t["function"]["name"] for t in llm.kwargs["tools"]] == NOMI_LOCALI + [
        "search_catalog", "get_item", "add_note", "list_notes", "delete_note", "get_weather"]


# carica_strumenti della CLI unisce strumenti locali e tool MCP, nello stesso ordine
def test_carica_strumenti_unisce_locali_e_mcp(tutti):
    assert [t.name for t in cli.carica_strumenti()] == [t.name for t in tutti]


# senza server MCP l'assistente parte lo stesso con i 4 strumenti di base
def test_carica_strumenti_senza_server_mcp(monkeypatch):
    # nessun server MCP disponibile: restano i 4 strumenti locali e HTTP
    monkeypatch.setattr(cli, "carica_tutti_mcp", lambda: [])
    assert [t.name for t in cli.carica_strumenti()] == NOMI_LOCALI


# il grafo esegue davvero search_catalog e poi get_item sul server MCP del catalogo
def test_sequenza_catalogo_nell_agente_unico(tutti):
    # copione: cerca, poi legge il dettaglio, poi risponde
    copione = ModelloCopione([
        _chiamata("search_catalog", {"query": "smartphone"}, "c1"),
        _chiamata("get_item", {"code": "PRD001"}, "c2"),
        AIMessage("Costa 499,99 euro."),
    ])
    out = build_graph(copione, strumenti=tutti).invoke(_stato("Quanto costa lo smartphone?"))
    # il primo messaggio mandato al modello e' il SYSTEM_PROMPT
    assert copione.chiamate[0][0] == SystemMessage(SYSTEM_PROMPT)
    # i risultati dei due tool sono nella conversazione; get_item porta il prezzo vero
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in risultati] == ["search_catalog", "get_item"]
    assert "499.99" in risultati[1].content


# nello stesso grafo funziona ancora l'orologio locale
def test_orologio_nell_agente_unico(tutti):
    copione = ModelloCopione([_chiamata("tooltime", {"parte": "data"}, "c1"), AIMessage("ok")])
    out = build_graph(copione, strumenti=tutti).invoke(_stato("Che giorno è?"))
    risultato = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert risultato.name == "tooltime" and risultato.status != "error"  # eseguito senza errori


# variabili d'ambiente minime per avviare la CLI senza un .env
@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "m")
    monkeypatch.delenv("MAX_STEPS", raising=False)
    # imposta_log cambia i livelli dei logger per tutto il processo: altri test (test_attesa)
    # dipendono dallo stato iniziale, quindi qui non si tocca
    monkeypatch.setattr(cli, "imposta_log", lambda: None)


# avvia() passa gli stessi strumenti al modello e al grafo e li elenca all'utente
def test_avvia_usa_tutti_gli_strumenti(ambiente, monkeypatch, capsys):
    # un tool MCP finto, per non avviare i server
    @tool
    def search_catalog(query: str) -> str:
        """finto"""
        return "[]"

    finti = list(STRUMENTI) + [search_catalog]
    ricevuto = {}  # raccoglie quello che avvia() passa a build_llm e a main
    # monkeypatch: strumenti finti, build_llm e main sostituiti da funzioni che registrano
    monkeypatch.setattr(cli, "carica_strumenti", lambda: finti)
    monkeypatch.setattr("app.llm.build_llm",
                        lambda s, strumenti: ricevuto.update(llm_strumenti=strumenti) or "llm")
    monkeypatch.setattr(cli, "main", lambda **kw: ricevuto.update(kw))
    cli.avvia()  # azione
    # controlli: elenco stampato, stessi strumenti a modello e grafo, modello passato a main
    assert "Strumenti: tooltime, toolconvert, toolcalc, tooldate, search_catalog" in \
        capsys.readouterr().out
    assert ricevuto["strumenti"] == finti and ricevuto["llm_strumenti"] == finti
    assert ricevuto["llm"] == "llm"
