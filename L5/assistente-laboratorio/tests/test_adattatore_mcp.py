import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.adattatore_mcp import (CARTELLA_PROGETTO, ErroreMCP, carica_strumenti_mcp,
                                configurazione_server, schema_valido)

CARTELLA_TEST = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def tools():
    return carica_strumenti_mcp()


def _per_nome(tools, nome):
    return next(t for t in tools if t.name == nome)


def _esegui_con_toolnode(tools, nome, args):
    # ToolNode fuori da un grafo non ha il runtime: grafo minimo con il solo nodo strumenti
    g = StateGraph(MessagesState)
    g.add_node("strumenti", ToolNode(tools))
    g.add_edge(START, "strumenti")
    g.add_edge("strumenti", END)
    stato = {"messages": [AIMessage("", tool_calls=[{"name": nome, "args": args, "id": "c1"}])]}
    return g.compile().invoke(stato)["messages"][-1]


def test_configurazione_stdio():
    conf = configurazione_server()
    assert conf["transport"] == "stdio"
    assert conf["args"] == ["-m", "mcp_catalogo.server"]
    assert Path(conf["cwd"]) == CARTELLA_PROGETTO
    assert (CARTELLA_PROGETTO / "mcp_catalogo" / "server.py").exists()


def test_discovery(tools):
    assert [t.name for t in tools] == ["search_catalog", "get_item"]
    assert all(schema_valido(t) for t in tools)
    assert "get_item" in _per_nome(tools, "search_catalog").description


def test_invoke_sincrono_vuoto(tools):
    assert _per_nome(tools, "search_catalog").invoke({"query": "pattini a rotelle"}) == "[]"


def test_invoke_sincrono_dettaglio(tools):
    testo = _per_nome(tools, "get_item").invoke({"code": "PRD001"})
    assert isinstance(testo, str) and "499.99" in testo


def test_errore_server_diventa_tool_message(tools):
    m = _esegui_con_toolnode(tools, "get_item", {"code": "PRD999"})
    assert m.status == "error"
    assert "PRD999 non presente" in m.content


def test_max_results_fuori_intervallo_via_toolnode(tools):
    m = _esegui_con_toolnode(tools, "search_catalog", {"query": "libri", "max_results": 21})
    assert m.status == "error"
    assert m.content == "max_results deve essere tra 1 e 20, ricevuto 21."


def test_schema_anyof_scartato(capsys):
    tools = carica_strumenti_mcp("server_mcp_anyof", CARTELLA_TEST)
    assert [t.name for t in tools] == ["buono"]
    assert "cattivo" in capsys.readouterr().err


def test_server_non_avviabile():
    with pytest.raises(ErroreMCP) as e:
        carica_strumenti_mcp("modulo_che_non_esiste")
    assert str(e.value)


def test_server_caduto_durante_la_chiamata(tmp_path):
    shutil.copy(CARTELLA_TEST / "server_mcp_anyof.py", tmp_path / "server_temporaneo.py")
    tools = carica_strumenti_mcp("server_temporaneo", tmp_path)
    (tmp_path / "server_temporaneo.py").unlink()
    m = _esegui_con_toolnode(tools, "buono", {"x": "ciao"})
    assert m.status == "error"
    assert m.content.startswith("Server MCP del catalogo non disponibile")


def test_nessun_log_info_del_server_nella_chat():
    # il server riparte a ogni chiamata e scrive su stderr, ereditato dal terminale della chat;
    # dentro pytest capfd non vede lo stderr del nipote: si usa un processo separato
    codice = ("from app.adattatore_mcp import carica_strumenti_mcp; "
              "t = carica_strumenti_mcp(); print(t[1].invoke({'code': 'PRD001'})[:20])")
    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True, text=True,
                           cwd=CARTELLA_PROGETTO, timeout=120)
    assert "PRD001" in esito.stdout, esito.stderr
    assert "Starting MCP server" not in esito.stderr, esito.stderr


def test_latenza(tools):
    inizio = time.perf_counter()
    _per_nome(tools, "get_item").invoke({"code": "PRD001"})
    print(f"\nlatenza get_item: {time.perf_counter() - inizio:.2f} s")


# --- minori della revisione finale ---

def test_invoke_da_event_loop_attivo(tools):
    # chiamato dentro un loop gia' attivo (es. codice asincrono): funziona lo stesso
    async def corpo():
        return _per_nome(tools, "search_catalog").invoke({"query": "pattini a rotelle"})
    assert asyncio.run(corpo()) == "[]"


def _tool_con_schema(schema):
    return StructuredTool(name="t", description="d", args_schema=schema, func=lambda **k: "")


@pytest.mark.parametrize("schema, atteso", [
    ({"type": "object"}, True),
    ({"type": "object", "properties": {}}, True),
    ({"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False},
     True),
    ({"type": "object", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}},
     False),
    ({"type": "object", "properties": {"x": {"description": "senza type"}}}, False),
])
def test_schema_valido_casi(schema, atteso):
    assert schema_valido(_tool_con_schema(schema)) is atteso


def test_errore_avvio_senza_prefisso_ripetuto():
    with pytest.raises(ErroreMCP) as e:
        carica_strumenti_mcp("modulo_che_non_esiste")
    # il contesto ("catalogo MCP non disponibile") lo aggiunge solo app.cli
    assert "non disponibile" not in str(e.value)
    assert "modulo_che_non_esiste" in str(e.value)


# --- piu' server MCP (esercizio 5: note) ---

from app.adattatore_mcp import SERVER_MCP, carica_tutti_mcp, è_distruttivo  # noqa: E402

NOMI_MCP = ["search_catalog", "get_item", "add_note", "list_notes", "delete_note", "get_weather"]


@pytest.fixture
def note_db(monkeypatch, tmp_path):
    percorso = tmp_path / "note.sqlite"
    monkeypatch.setenv("NOTE_DB", str(percorso))
    return percorso


def test_due_server_scoperti(note_db):
    assert [t.name for t in carica_tutti_mcp()] == NOMI_MCP


def test_annotazioni_conservate(note_db):
    tools = {t.name: t for t in carica_tutti_mcp()}
    assert è_distruttivo(tools["delete_note"])
    assert not è_distruttivo(tools["add_note"])
    assert not è_distruttivo(tools["list_notes"])
    assert not è_distruttivo(tools["search_catalog"])


def test_note_db_passato_al_server(note_db):
    from mcp_note.archivio import elenca
    tools = {t.name: t for t in carica_tutti_mcp()}
    assert tools["add_note"].invoke({"text": "comprare il latte"}).startswith("Nota 1 creata")
    assert elenca(10, note_db)[0][0]["testo"] == "comprare il latte"


def test_un_server_giu_non_toglie_l_altro(note_db, monkeypatch, capsys):
    rotti = dict(SERVER_MCP, note=dict(SERVER_MCP["note"], modulo="modulo_che_non_esiste"))
    monkeypatch.setattr("app.adattatore_mcp.SERVER_MCP", rotti)
    assert [t.name for t in carica_tutti_mcp()] == ["search_catalog", "get_item", "get_weather"]
    err = capsys.readouterr().err
    assert "server MCP note non disponibile" in err


# --- server MCP del meteo (esercizio 6) ---

def test_server_meteo_in_server_mcp():
    """Il meteo e' il terzo server; riceve citta' predefinita, limite e file del contatore."""
    meteo = SERVER_MCP["meteo"]
    assert meteo["modulo"] == "mcp_meteo.server" and meteo["etichetta"] == "del meteo"
    assert meteo["variabili"] == ["CITTA_PREDEFINITA", "METEO_LIMITE_GIORNALIERO",
                                  "METEO_CONTATORE"]


def test_meteo_annotazioni_non_distruttivo(note_db):
    """get_weather e' di sola lettura: nessuna conferma nel grafo."""
    tools = {t.name: t for t in carica_tutti_mcp()}
    assert tools["get_weather"].metadata.get("readOnlyHint") is True
    assert not è_distruttivo(tools["get_weather"])


def test_variabili_del_meteo_passate_al_server(note_db, monkeypatch, tmp_path):
    """Limite e contatore arrivano al processo del server: con il limite gia' raggiunto la
    chiamata si ferma prima di usare la rete ("riprova domani")."""
    from datetime import datetime, timezone
    from mcp_meteo.contatore import Contatore
    contatore = tmp_path / "meteo.sqlite"
    Contatore(contatore, 1, lambda: datetime.now(timezone.utc)).registra()  # 1 richiesta oggi
    monkeypatch.setenv("METEO_CONTATORE", str(contatore))
    monkeypatch.setenv("METEO_LIMITE_GIORNALIERO", "1")
    tools = {t.name: t for t in carica_tutti_mcp()}
    m = _esegui_con_toolnode(tools.values(), "get_weather", {"city": "Roma"})
    assert m.status == "error" and "riprova domani" in m.content


def test_server_meteo_giu_restano_gli_altri(note_db, monkeypatch, capsys):
    """Se il server meteo non parte restano i 5 tool di catalogo e note, con un avviso."""
    rotti = dict(SERVER_MCP, meteo=dict(SERVER_MCP["meteo"], modulo="modulo_che_non_esiste"))
    monkeypatch.setattr("app.adattatore_mcp.SERVER_MCP", rotti)
    assert [t.name for t in carica_tutti_mcp()] == NOMI_MCP[:5]
    assert "server MCP meteo non disponibile" in capsys.readouterr().err


def test_messaggio_server_note_caduto(tmp_path):
    shutil.copy(CARTELLA_TEST / "server_mcp_anyof.py", tmp_path / "server_temporaneo.py")
    tools = carica_strumenti_mcp("server_temporaneo", tmp_path, etichetta="delle note")
    (tmp_path / "server_temporaneo.py").unlink()
    m = _esegui_con_toolnode(tools, "buono", {"x": "ciao"})
    assert m.status == "error"
    assert m.content.startswith("Server MCP delle note non disponibile")


def _stderr_del_server(codice, note_db):
    """Esegue `codice` (che usa gli strumenti MCP) in un processo separato con stderr rediretto,
    come in un IDE o in una pipe, e restituisce lo stderr decodificato in UTF-8."""
    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True, cwd=CARTELLA_PROGETTO,
                           env=dict(os.environ, NOTE_DB=str(note_db)), timeout=120)
    return esito.stdout.decode("utf-8", "replace"), esito.stderr.decode("utf-8", "replace")


def test_log_delle_note_in_utf8_anche_con_stderr_rediretto(tmp_path):
    codice = ("from app.adattatore_mcp import carica_tutti_mcp; "
              "t = {x.name: x for x in carica_tutti_mcp()}; "
              "print(t['add_note'].invoke({'text': \"l'esame è \\\"lunedì\\\" 🎓\"}))")
    _, err = _stderr_del_server(codice, tmp_path / "note.sqlite")
    assert "[note] creata nota 1: l'esame è \"lunedì\" 🎓" in err, err


def test_nessuna_riga_error_calling_tool(tmp_path):
    codice = ("from app.adattatore_mcp import carica_tutti_mcp; "
              "t = {x.name: x for x in carica_tutti_mcp()}; "
              "print(t['delete_note'].invoke({'note_id': 99})); "
              "print(t['get_item'].invoke({'code': 'PRD999'}))")
    out, err = _stderr_del_server(codice, tmp_path / "note.sqlite")
    assert "non esiste" in out and "PRD999" in out, out
    assert "Error calling tool" not in err, err
