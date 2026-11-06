# Test dell'adattatore MCP (app/adattatore_mcp.py): avvia i server MCP veri via stdio,
# scopre i loro tool e li rende strumenti LangChain usabili dal grafo.

# librerie standard: asincronia, ambiente, copie di file, processi, tempi, percorsi
import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# pytest, messaggi e strumenti di LangChain, pezzi di LangGraph per un grafo minimo
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

# il codice da verificare
from app.adattatore_mcp import (CARTELLA_PROGETTO, ErroreMCP, carica_strumenti_mcp,
                                configurazione_server, schema_valido)

# cartella tests/: contiene anche il server di prova server_mcp_anyof.py
CARTELLA_TEST = Path(__file__).resolve().parent


# tool del catalogo scoperti una sola volta per tutto il modulo (avviare il server costa)
@pytest.fixture(scope="module")
def tools():
    return carica_strumenti_mcp()


# cerca un tool per nome nell'elenco scoperto
def _per_nome(tools, nome):
    return next(t for t in tools if t.name == nome)


# esegue un tool come fa il grafo vero: un messaggio del modello con una tool call finta
# passa dal ToolNode, che restituisce il ToolMessage (con status "error" se fallisce)
def _esegui_con_toolnode(tools, nome, args):
    # ToolNode fuori da un grafo non ha il runtime: grafo minimo con il solo nodo strumenti
    g = StateGraph(MessagesState)
    g.add_node("strumenti", ToolNode(tools))
    g.add_edge(START, "strumenti")
    g.add_edge("strumenti", END)
    stato = {"messages": [AIMessage("", tool_calls=[{"name": nome, "args": args, "id": "c1"}])]}
    return g.compile().invoke(stato)["messages"][-1]  # l'ultimo messaggio e' il ToolMessage


# la configurazione avvia il server del catalogo via stdio dalla cartella del progetto
def test_configurazione_stdio():
    conf = configurazione_server()
    # trasporto stdio, modulo giusto, cartella di lavoro e file del server esistente
    assert conf["transport"] == "stdio"
    assert conf["args"] == ["-m", "mcp_catalogo.server"]
    assert Path(conf["cwd"]) == CARTELLA_PROGETTO
    assert (CARTELLA_PROGETTO / "mcp_catalogo" / "server.py").exists()


# discovery automatica: i due tool nell'ordine atteso, con schemi accettati da gemma
def test_discovery(tools):
    assert [t.name for t in tools] == ["search_catalog", "get_item"]
    assert all(schema_valido(t) for t in tools)  # nessun anyOf, ogni argomento con type
    # la descrizione arriva dal server e suggerisce al modello di usare poi get_item
    assert "get_item" in _per_nome(tools, "search_catalog").description


# il tool asincrono si usa anche da codice sincrono; una ricerca senza risultati da' "[]"
def test_invoke_sincrono_vuoto(tools):
    assert _per_nome(tools, "search_catalog").invoke({"query": "pattini a rotelle"}) == "[]"


# get_item restituisce un testo (non un oggetto) con il prezzo del prodotto
def test_invoke_sincrono_dettaglio(tools):
    testo = _per_nome(tools, "get_item").invoke({"code": "PRD001"})
    assert isinstance(testo, str) and "499.99" in testo


# un errore del server non blocca il grafo: diventa un ToolMessage con status "error"
def test_errore_server_diventa_tool_message(tools):
    m = _esegui_con_toolnode(tools, "get_item", {"code": "PRD999"})  # codice inesistente
    assert m.status == "error"
    assert "PRD999 non presente" in m.content  # il messaggio del server arriva al modello


# un argomento fuori intervallo produce il messaggio esatto del server, non un'eccezione
def test_max_results_fuori_intervallo_via_toolnode(tools):
    m = _esegui_con_toolnode(tools, "search_catalog", {"query": "libri", "max_results": 21})
    assert m.status == "error"
    assert m.content == "max_results deve essere tra 1 e 20, ricevuto 21."


# un tool con schema "anyOf" farebbe fallire LM Studio: si scarta con un avviso
def test_schema_anyof_scartato(capsys):
    # server di prova con un tool "buono" e uno "cattivo" (argomento int | None)
    tools = carica_strumenti_mcp("server_mcp_anyof", CARTELLA_TEST)
    assert [t.name for t in tools] == ["buono"]
    assert "cattivo" in capsys.readouterr().err  # l'avviso su stderr nomina il tool scartato


# un server che non parte da' ErroreMCP con un messaggio non vuoto
def test_server_non_avviabile():
    with pytest.raises(ErroreMCP) as e:
        carica_strumenti_mcp("modulo_che_non_esiste")
    assert str(e.value)


# il server sparisce dopo la discovery: la chiamata fallisce con un messaggio chiaro
def test_server_caduto_durante_la_chiamata(tmp_path):
    # preparazione: copia temporanea del server di prova, scoperta e poi cancellata
    shutil.copy(CARTELLA_TEST / "server_mcp_anyof.py", tmp_path / "server_temporaneo.py")
    tools = carica_strumenti_mcp("server_temporaneo", tmp_path)
    (tmp_path / "server_temporaneo.py").unlink()
    # azione: il server riparte a ogni chiamata, ma il file non c'e' piu'
    m = _esegui_con_toolnode(tools, "buono", {"x": "ciao"})
    assert m.status == "error"
    assert m.content.startswith("Server MCP del catalogo non disponibile")


# i log informativi di FastMCP ("Starting MCP server") non devono sporcare la chat
def test_nessun_log_info_del_server_nella_chat():
    # il server riparte a ogni chiamata e scrive su stderr, ereditato dal terminale della chat;
    # dentro pytest capfd non vede lo stderr del nipote: si usa un processo separato
    codice = ("from app.adattatore_mcp import carica_strumenti_mcp; "
              "t = carica_strumenti_mcp(); print(t[1].invoke({'code': 'PRD001'})[:20])")
    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True, text=True,
                           cwd=CARTELLA_PROGETTO, timeout=120)
    # la chiamata funziona e su stderr non compare la riga di avvio del server
    assert "PRD001" in esito.stdout, esito.stderr
    assert "Starting MCP server" not in esito.stderr, esito.stderr


# non e' un controllo: stampa quanto dura una chiamata (il server riparte ogni volta)
# si vede con pytest -s
def test_latenza(tools):
    inizio = time.perf_counter()
    _per_nome(tools, "get_item").invoke({"code": "PRD001"})
    print(f"\nlatenza get_item: {time.perf_counter() - inizio:.2f} s")


# --- minori della revisione finale ---

# invoke sincrono anche quando un event loop asyncio e' gia' in esecuzione
def test_invoke_da_event_loop_attivo(tools):
    # chiamato dentro un loop gia' attivo (es. codice asincrono): funziona lo stesso
    async def corpo():
        return _per_nome(tools, "search_catalog").invoke({"query": "pattini a rotelle"})
    assert asyncio.run(corpo()) == "[]"


# strumento minimo con lo schema dato, per provare schema_valido senza un server
def _tool_con_schema(schema):
    return StructuredTool(name="t", description="d", args_schema=schema, func=lambda **k: "")


# schema_valido accetta schemi senza argomenti o con "type"; rifiuta anyOf e argomenti senza type
@pytest.mark.parametrize("schema, atteso", [
    # validi: nessun argomento, properties vuote, argomento con type
    ({"type": "object"}, True),
    ({"type": "object", "properties": {}}, True),
    ({"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False},
     True),
    # non validi: argomento con anyOf (int | None) e argomento senza type
    ({"type": "object", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}},
     False),
    ({"type": "object", "properties": {"x": {"description": "senza type"}}}, False),
])
def test_schema_valido_casi(schema, atteso):
    assert schema_valido(_tool_con_schema(schema)) is atteso


# il messaggio d'errore dell'avvio nomina il modulo, senza ripetere "non disponibile"
def test_errore_avvio_senza_prefisso_ripetuto():
    with pytest.raises(ErroreMCP) as e:
        carica_strumenti_mcp("modulo_che_non_esiste")
    # il contesto ("catalogo MCP non disponibile") lo aggiunge solo app.cli
    assert "non disponibile" not in str(e.value)
    assert "modulo_che_non_esiste" in str(e.value)


# --- piu' server MCP (esercizio 5: note) ---

# elenco dei server, caricamento di tutti i server, riconoscimento dei tool distruttivi
from app.adattatore_mcp import SERVER_MCP, carica_tutti_mcp, è_distruttivo  # noqa: E402

# i tool di tutti i server MCP, nell'ordine dei server: catalogo, note, meteo
NOMI_MCP = ["search_catalog", "get_item", "add_note", "list_notes", "delete_note", "get_weather"]


# archivio delle note in una cartella temporanea: i test non toccano le note vere
@pytest.fixture
def note_db(monkeypatch, tmp_path):
    percorso = tmp_path / "note.sqlite"
    monkeypatch.setenv("NOTE_DB", str(percorso))  # variabile letta dal server delle note
    return percorso


# tutti i server MCP vengono scoperti: i 6 tool nell'ordine atteso
def test_due_server_scoperti(note_db):
    assert [t.name for t in carica_tutti_mcp()] == NOMI_MCP


# le annotazioni MCP restano sui tool: solo delete_note chiede conferma nel grafo
def test_annotazioni_conservate(note_db):
    tools = {t.name: t for t in carica_tutti_mcp()}
    assert è_distruttivo(tools["delete_note"])
    assert not è_distruttivo(tools["add_note"])
    assert not è_distruttivo(tools["list_notes"])
    assert not è_distruttivo(tools["search_catalog"])


# NOTE_DB arriva al processo del server: la nota finisce nell'archivio temporaneo
def test_note_db_passato_al_server(note_db):
    from mcp_note.archivio import elenca
    tools = {t.name: t for t in carica_tutti_mcp()}
    # azione: si crea una nota passando dal server MCP
    assert tools["add_note"].invoke({"text": "comprare il latte"}).startswith("Nota 1 creata")
    # controllo: la nota si legge direttamente dall'archivio indicato da NOTE_DB
    assert elenca(10, note_db)[0][0]["testo"] == "comprare il latte"


# se un server non parte, gli altri restano disponibili e compare un avviso
def test_un_server_giu_non_toglie_l_altro(note_db, monkeypatch, capsys):
    # preparazione: il server delle note punta a un modulo inesistente
    rotti = dict(SERVER_MCP, note=dict(SERVER_MCP["note"], modulo="modulo_che_non_esiste"))
    monkeypatch.setattr("app.adattatore_mcp.SERVER_MCP", rotti)
    # restano catalogo e meteo
    assert [t.name for t in carica_tutti_mcp()] == ["search_catalog", "get_item", "get_weather"]
    err = capsys.readouterr().err
    assert "server MCP note non disponibile" in err  # avviso per l'utente


# --- server MCP del meteo (esercizio 6) ---

# il meteo e' registrato con modulo, etichetta e variabili d'ambiente da passargli
def test_server_meteo_in_server_mcp():
    """Il meteo e' il terzo server; riceve citta' predefinita, limite e file del contatore."""
    meteo = SERVER_MCP["meteo"]
    assert meteo["modulo"] == "mcp_meteo.server" and meteo["etichetta"] == "del meteo"
    assert meteo["variabili"] == ["CITTA_PREDEFINITA", "METEO_LIMITE_GIORNALIERO",
                                  "METEO_CONTATORE"]


# l'annotazione readOnlyHint del meteo arriva al grafo: nessuna richiesta di conferma
def test_meteo_annotazioni_non_distruttivo(note_db):
    """get_weather e' di sola lettura: nessuna conferma nel grafo."""
    tools = {t.name: t for t in carica_tutti_mcp()}
    assert tools["get_weather"].metadata.get("readOnlyHint") is True
    assert not è_distruttivo(tools["get_weather"])


# le variabili del meteo arrivano davvero al server: lo dimostra il limite gia' raggiunto
def test_variabili_del_meteo_passate_al_server(note_db, monkeypatch, tmp_path):
    """Limite e contatore arrivano al processo del server: con il limite gia' raggiunto la
    chiamata si ferma prima di usare la rete ("riprova domani")."""
    from datetime import datetime, timezone
    from mcp_meteo.contatore import Contatore
    # preparazione: contatore temporaneo con una richiesta gia' registrata e limite 1
    contatore = tmp_path / "meteo.sqlite"
    Contatore(contatore, 1, lambda: datetime.now(timezone.utc)).registra()  # 1 richiesta oggi
    monkeypatch.setenv("METEO_CONTATORE", str(contatore))
    monkeypatch.setenv("METEO_LIMITE_GIORNALIERO", "1")
    # azione: chiamata a get_weather attraverso il ToolNode
    tools = {t.name: t for t in carica_tutti_mcp()}
    m = _esegui_con_toolnode(tools.values(), "get_weather", {"city": "Roma"})
    # controllo: errore del limite giornaliero, senza nessuna richiesta in rete
    assert m.status == "error" and "riprova domani" in m.content


# se il meteo non parte restano catalogo e note, con un avviso
def test_server_meteo_giu_restano_gli_altri(note_db, monkeypatch, capsys):
    """Se il server meteo non parte restano i 5 tool di catalogo e note, con un avviso."""
    # preparazione: il server meteo punta a un modulo inesistente
    rotti = dict(SERVER_MCP, meteo=dict(SERVER_MCP["meteo"], modulo="modulo_che_non_esiste"))
    monkeypatch.setattr("app.adattatore_mcp.SERVER_MCP", rotti)
    assert [t.name for t in carica_tutti_mcp()] == NOMI_MCP[:5]  # tutti tranne get_weather
    assert "server MCP meteo non disponibile" in capsys.readouterr().err


# il messaggio di server caduto usa l'etichetta del server ("delle note")
def test_messaggio_server_note_caduto(tmp_path):
    # come test_server_caduto_durante_la_chiamata, ma con l'etichetta delle note
    shutil.copy(CARTELLA_TEST / "server_mcp_anyof.py", tmp_path / "server_temporaneo.py")
    tools = carica_strumenti_mcp("server_temporaneo", tmp_path, etichetta="delle note")
    (tmp_path / "server_temporaneo.py").unlink()
    m = _esegui_con_toolnode(tools, "buono", {"x": "ciao"})
    assert m.status == "error"
    assert m.content.startswith("Server MCP delle note non disponibile")


# processo separato con stderr catturato: serve a leggere i log scritti dal server
def _stderr_del_server(codice, note_db):
    """Esegue `codice` (che usa gli strumenti MCP) in un processo separato con stderr rediretto,
    come in un IDE o in una pipe, e restituisce lo stderr decodificato in UTF-8."""
    esito = subprocess.run([sys.executable, "-c", codice], capture_output=True, cwd=CARTELLA_PROGETTO,
                           env=dict(os.environ, NOTE_DB=str(note_db)), timeout=120)
    return esito.stdout.decode("utf-8", "replace"), esito.stderr.decode("utf-8", "replace")


# il log del server delle note resta leggibile (accenti, virgolette, emoji) anche in una pipe
def test_log_delle_note_in_utf8_anche_con_stderr_rediretto(tmp_path):
    # codice del processo figlio: crea una nota con caratteri non ASCII
    codice = ("from app.adattatore_mcp import carica_tutti_mcp; "
              "t = {x.name: x for x in carica_tutti_mcp()}; "
              "print(t['add_note'].invoke({'text': \"l'esame è \\\"lunedì\\\" 🎓\"}))")
    _, err = _stderr_del_server(codice, tmp_path / "note.sqlite")
    # la riga di log contiene il testo intatto, decodificato in UTF-8
    assert "[note] creata nota 1: l'esame è \"lunedì\" 🎓" in err, err


# gli errori dei tool arrivano al modello, ma FastMCP non stampa "Error calling tool" nel terminale
def test_nessuna_riga_error_calling_tool(tmp_path):
    # codice del processo figlio: due chiamate che falliscono (nota e prodotto inesistenti)
    codice = ("from app.adattatore_mcp import carica_tutti_mcp; "
              "t = {x.name: x for x in carica_tutti_mcp()}; "
              "print(t['delete_note'].invoke({'note_id': 99})); "
              "print(t['get_item'].invoke({'code': 'PRD999'}))")
    out, err = _stderr_del_server(codice, tmp_path / "note.sqlite")
    # i messaggi d'errore sono nella risposta (stdout), non come righe di log su stderr
    assert "non esiste" in out and "PRD999" in out, out
    assert "Error calling tool" not in err, err
