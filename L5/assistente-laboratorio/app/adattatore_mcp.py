"""Adattatore MCP: scopre i tool dei server MCP e li rende tool LangChain sincroni.

Server (SERVER_MCP): catalogo prodotti (mcp_catalogo/), note (mcp_note/) e meteo (mcp_meteo/),
ognuno avviato come sottoprocesso (trasporto stdio). La discovery (tools/list) avviene una volta, all'avvio, un
server alla volta; ogni chiamata (tools/call) apre una sessione nuova. Il grafo resta
sincrono: ogni tool asincrono dell'adattatore e' eseguito con asyncio.run. Le annotazioni MCP
(es. destructiveHint) restano nei metadata del tool.
"""
# librerie standard: codice asincrono, ambiente, interprete in uso, thread, percorsi
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# classi degli strumenti LangChain e client MCP che parla con piu' server
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient

# cartella che contiene app/ e mcp_catalogo/
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent
MODULO_SERVER = "mcp_catalogo.server"  # server predefinito delle funzioni qui sotto
TIMEOUT_S = 30  # discovery o chiamata bloccata: meglio un errore che un'attesa infinita
# server MCP dell'agente: nome -> modulo da avviare, etichetta per i messaggi, variabili da
# passare (il client stdio di mcp inoltra solo un elenco ristretto di variabili d'ambiente)
SERVER_MCP = {
    "catalogo": {"modulo": "mcp_catalogo.server", "etichetta": "del catalogo", "variabili": []},
    "note": {"modulo": "mcp_note.server", "etichetta": "delle note", "variabili": ["NOTE_DB"]},
    # meteo (esercizio 6): citta' predefinita, limite giornaliero e file del contatore
    "meteo": {"modulo": "mcp_meteo.server", "etichetta": "del meteo",
              "variabili": ["CITTA_PREDEFINITA", "METEO_LIMITE_GIORNALIERO", "METEO_CONTATORE"]},
}


# errore proprio dell'adattatore: app.cli lo cattura e mostra un avviso
class ErroreMCP(Exception):
    """Il server MCP non parte o non pubblica tool utilizzabili."""


# descrive come avviare un server MCP: comando, argomenti, cartella, variabili d'ambiente
def configurazione_server(modulo: str = MODULO_SERVER, cartella: Path = CARTELLA_PROGETTO,
                          env: dict | None = None) -> dict:
    """Voce di MultiServerMCPClient: il server e' un processo figlio con lo stesso interprete."""
    # il server riparte a ogni chiamata e scrive su stderr (il terminale della chat):
    # - FASTMCP_LOG_LEVEL=CRITICAL: niente righe di FastMCP ("Starting...", "Error calling
    #   tool ..."): gli errori arrivano gia' al modello come risultato del tool, e il log delle
    #   modifiche delle note e' scritto dal server con print, non dal logger di FastMCP;
    # - PYTHONIOENCODING=utf-8: accenti ed emoji leggibili nel log anche con stderr rediretto
    #   (su Windows altrimenti cp1252).
    # mcp unisce env alle variabili predefinite
    # sys.executable: lo stesso Python del programma (quello del venv), con "-m modulo"
    return {"command": sys.executable, "args": ["-m", modulo], "transport": "stdio",
            "cwd": str(cartella),
            "env": {"FASTMCP_LOG_LEVEL": "CRITICAL", "PYTHONIOENCODING": "utf-8", **(env or {})}}


# usato dal grafo per sapere se prima di eseguire il tool serve il si' dell'utente
def è_distruttivo(tool: BaseTool) -> bool:
    """Il tool ha l'annotazione MCP destructiveHint (es. delete_note): serve una conferma."""
    # i tool locali non hanno metadata (None): "or {}" evita l'errore
    return bool((tool.metadata or {}).get("destructiveHint"))


# controlla che lo schema del tool sia accettato da gemma in LM Studio
def schema_valido(tool: BaseTool) -> bool:
    """Ogni argomento ha "type" e nessun "anyOf" (il template di gemma lo richiede).
    Un tool senza argomenti (nessuna "properties") e' valido."""
    # i tool MCP hanno lo schema come dizionario JSON
    if isinstance(tool.args_schema, dict):
        proprieta = tool.args_schema.get("properties") or {}
    else:
        proprieta = tool.args  # schema Pydantic: gia' l'elenco degli argomenti
    # valido solo se tutti gli argomenti rispettano la regola (all() di un elenco vuoto e' True)
    return all(isinstance(s, dict) and "type" in s and "anyOf" not in s
               for s in proprieta.values())


# ponte tra il mondo asincrono dell'adattatore MCP e il nostro programma sincrono
def _esegui(fabbrica):
    """Esegue la coroutine creata da `fabbrica` con un timeout. Se nel thread c'e' gia' un event
    loop attivo (asyncio.run non si puo' annidare) la esegue in un thread separato."""
    # wait_for interrompe l'attesa dopo TIMEOUT_S secondi
    async def corpo():
        return await asyncio.wait_for(fabbrica(), TIMEOUT_S)

    # get_running_loop solleva RuntimeError se non c'e' un event loop: caso normale
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corpo())
    # c'e' gia' un event loop: si usa un thread a parte, con un event loop tutto suo
    with ThreadPoolExecutor(max_workers=1) as esecutore:
        return esecutore.submit(lambda: asyncio.run(corpo())).result()


# estrae dall'errore un messaggio comprensibile per l'utente
def _motivo(errore: BaseException) -> str:
    """Messaggio leggibile, anche da un ExceptionGroup del trasporto."""
    # un gruppo di errori puo' contenere altri gruppi: si scende fino al primo errore vero
    while isinstance(errore, BaseExceptionGroup) and errore.exceptions:
        errore = errore.exceptions[0]
    # se l'errore non ha messaggio si usa il nome della sua classe
    return str(errore) or type(errore).__name__


# trasforma il risultato di un tool MCP in una sola stringa
def _testo(contenuto) -> str:
    """Contenuto MCP (stringa o blocchi) come testo semplice per il ToolMessage."""
    if isinstance(contenuto, str):
        return contenuto
    # elenco di blocchi: si uniscono i testi (i blocchi senza "text" contano come vuoti)
    if isinstance(contenuto, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in contenuto)
    return str(contenuto)


# avvolge un tool MCP asincrono in un tool LangChain sincrono, usabile dal ToolNode del grafo
def _sincrono(tool_async: BaseTool, etichetta: str = "del catalogo") -> StructuredTool:
    """Stesso nome, descrizione, schema e metadata (annotazioni MCP); esecuzione sincrona;
    errori come ToolException."""
    # funzione eseguita a ogni chiamata del tool: riceve gli argomenti scelti dal modello
    def esegui(**argomenti) -> str:
        try:
            # la coroutine restituisce (contenuto, artefatti): gli artefatti non servono
            contenuto, _ = _esegui(lambda: tool_async.coroutine(**argomenti))
        except ToolException as errore:
            # errore del tool (isError): il messaggio del server arriva al modello
            raise ToolException(_testo(errore.args[0] if errore.args else "")) from None
        except Exception as errore:  # trasporto: server caduto, non avviabile, bloccato
            raise ToolException(
                f"Server MCP {etichetta} non disponibile: {_motivo(errore)}") from None
        return _testo(contenuto)

    # handle_tool_error=True: una ToolException diventa un ToolMessage d'errore per il modello,
    # invece di fermare il programma
    return StructuredTool(name=tool_async.name, description=tool_async.description,
                          args_schema=tool_async.args_schema, func=esegui,
                          metadata=tool_async.metadata, handle_tool_error=True)


# avvia un server MCP, chiede l'elenco dei suoi tool e li prepara per il grafo
def carica_strumenti_mcp(modulo: str = MODULO_SERVER, cartella: Path = CARTELLA_PROGETTO,
                         etichetta: str = "del catalogo",
                         env: dict | None = None) -> list[BaseTool]:
    """Discovery (tools/list) di UN server; scarta con un avviso i tool con schema non valido."""
    # un client con un solo server, chiamato semplicemente "server"
    client = MultiServerMCPClient({"server": configurazione_server(modulo, cartella, env)})
    try:
        # get_tools avvia il server e fa la discovery (tools/list)
        scoperti = _esegui(client.get_tools)
    except Exception as errore:
        # il contesto ("catalogo MCP non disponibile") lo aggiunge app.cli.carica_strumenti
        raise ErroreMCP(f"{modulo}: {_motivo(errore)}") from None
    # tiene solo i tool con uno schema accettato da gemma, resi sincroni
    validi = []
    for tool in scoperti:
        if schema_valido(tool):
            validi.append(_sincrono(tool, etichetta))
        else:
            # l'avviso va su stderr, separato dalla conversazione
            print(f"Avviso: tool MCP {tool.name} scartato, schema con anyOf o senza type.",
                  file=sys.stderr)
    # un server senza nessun tool utilizzabile conta come server non disponibile
    if not validi:
        raise ErroreMCP(f"il server {modulo} non pubblica tool utilizzabili.")
    return validi


# carica i tool di tutti i server MCP dell'agente (chiamata da app.cli all'avvio)
def carica_tutti_mcp() -> list[BaseTool]:
    """Tutti i server di SERVER_MCP, uno alla volta: se uno non parte, gli altri restano."""
    strumenti = []
    for nome, server in SERVER_MCP.items():  # un server alla volta, nell'ordine di SERVER_MCP
        # variabili da passare al processo del server (es. NOTE_DB), solo se impostate
        env = {v: os.environ[v] for v in server["variabili"] if os.environ.get(v)}
        try:
            strumenti += carica_strumenti_mcp(server["modulo"], CARTELLA_PROGETTO,
                                              server["etichetta"], env)
        except ErroreMCP as errore:  # questo server non parte: avviso e si passa al prossimo
            print(f"Avviso: server MCP {nome} non disponibile ({errore}): i suoi tool non ci "
                  "sono.", file=sys.stderr)
    return strumenti
