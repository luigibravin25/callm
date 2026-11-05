"""Agente unico: i 4 strumenti di prima (locali e HTTP) piu' i tool scoperti dal server MCP."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app import cli
from app.adattatore_mcp import carica_tutti_mcp
from app.config import Settings
from app.graph import build_graph
from app.llm import SYSTEM_PROMPT, build_llm
from app.tools import STRUMENTI

IMPOSTAZIONI = Settings(base_url="http://127.0.0.1:1234/v1", model="m", max_steps=5,
                        fuso_predefinito="Europe/Rome")
NOMI_LOCALI = ["tooltime", "toolconvert", "toolcalc", "tooldate"]


class ModelloCopione:
    """Modello finto: restituisce i messaggi in ordine e registra cosa riceve."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)
        self.chiamate = []

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)
        return self.messaggi[0].model_copy(update={"id": None})


def _stato(testo):
    return {"messages": [HumanMessage(testo)], "steps": 0}


def _chiamata(nome, args, id_):
    return AIMessage("", tool_calls=[{"name": nome, "args": args, "id": id_}])


@pytest.fixture(scope="module")
def tutti():
    return list(STRUMENTI) + carica_tutti_mcp()


def test_strumenti_locali_invariati():
    assert [t.name for t in STRUMENTI] == NOMI_LOCALI


def test_system_prompt_unico():
    # la regola dell'orologio resta, si aggiungono quelle del catalogo
    assert "chiama tooltime senza l'argomento fuso" in SYSTEM_PROMPT
    for parte in ("search_catalog", "get_item", "[]", "Mostrati N di M", "max_results=M",
                  "non dire mai che non puoi consultarlo"):
        assert parte in SYSTEM_PROMPT, parte


def test_system_prompt_conferma_del_programma():
    """Il modello non chiede lui la conferma: chiama delete_note e la chiede il programma
    (ritocco 2, autorizzato dall'utente il 2026-11-05)."""
    assert "Non chiedere tu la conferma: chiama subito delete_note" in SYSTEM_PROMPT


def test_system_prompt_ricerca_generica():
    """Domanda generica sul catalogo: cercare subito la parola principale, senza chiarimenti
    (ritocco 3, autorizzato dall'utente il 2026-11-05)."""
    assert "cerca subito con search_catalog la parola principale" in SYSTEM_PROMPT


def test_system_prompt_meteo():
    """Regole del meteo (esercizio 6, autorizzate dall'utente il 2026-11-05)."""
    for parte in ("get_weather", "senza city", "days=1", "days=2", "presentatore",
                  "regione o provincia", "solo l'Italia", "non è raggiungibile",
                  "riprova domani", "7 giorni", "Città non trovata", "controllare il nome",
                  "chiama sempre get_weather"):
        assert parte in SYSTEM_PROMPT, parte


def test_build_llm_8192_token(tutti):
    llm = build_llm(IMPOSTAZIONI, tutti)
    assert llm.bound.max_tokens == 8192
    assert [t["function"]["name"] for t in llm.kwargs["tools"]] == NOMI_LOCALI + [
        "search_catalog", "get_item", "add_note", "list_notes", "delete_note", "get_weather"]


def test_carica_strumenti_unisce_locali_e_mcp(tutti):
    assert [t.name for t in cli.carica_strumenti()] == [t.name for t in tutti]


def test_carica_strumenti_senza_server_mcp(monkeypatch):
    # nessun server MCP disponibile: restano i 4 strumenti locali e HTTP
    monkeypatch.setattr(cli, "carica_tutti_mcp", lambda: [])
    assert [t.name for t in cli.carica_strumenti()] == NOMI_LOCALI


def test_sequenza_catalogo_nell_agente_unico(tutti):
    copione = ModelloCopione([
        _chiamata("search_catalog", {"query": "smartphone"}, "c1"),
        _chiamata("get_item", {"code": "PRD001"}, "c2"),
        AIMessage("Costa 499,99 euro."),
    ])
    out = build_graph(copione, strumenti=tutti).invoke(_stato("Quanto costa lo smartphone?"))
    assert copione.chiamate[0][0] == SystemMessage(SYSTEM_PROMPT)
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in risultati] == ["search_catalog", "get_item"]
    assert "499.99" in risultati[1].content


def test_orologio_nell_agente_unico(tutti):
    copione = ModelloCopione([_chiamata("tooltime", {"parte": "data"}, "c1"), AIMessage("ok")])
    out = build_graph(copione, strumenti=tutti).invoke(_stato("Che giorno è?"))
    risultato = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert risultato.name == "tooltime" and risultato.status != "error"


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "m")
    monkeypatch.delenv("MAX_STEPS", raising=False)
    # imposta_log cambia i livelli dei logger per tutto il processo: altri test (test_attesa)
    # dipendono dallo stato iniziale, quindi qui non si tocca
    monkeypatch.setattr(cli, "imposta_log", lambda: None)


def test_avvia_usa_tutti_gli_strumenti(ambiente, monkeypatch, capsys):
    @tool
    def search_catalog(query: str) -> str:
        """finto"""
        return "[]"

    finti = list(STRUMENTI) + [search_catalog]
    ricevuto = {}
    monkeypatch.setattr(cli, "carica_strumenti", lambda: finti)
    monkeypatch.setattr("app.llm.build_llm",
                        lambda s, strumenti: ricevuto.update(llm_strumenti=strumenti) or "llm")
    monkeypatch.setattr(cli, "main", lambda **kw: ricevuto.update(kw))
    cli.avvia()
    assert "Strumenti: tooltime, toolconvert, toolcalc, tooldate, search_catalog" in \
        capsys.readouterr().out
    assert ricevuto["strumenti"] == finti and ricevuto["llm_strumenti"] == finti
    assert ricevuto["llm"] == "llm"
