"""Adattatore MCP (come L5): collega l'host al server mcp_assistente (trasporto stdio).

All'avvio: discovery dei tool (tools/list) e lettura della resource delle preferenze
(resources/read), una volta. Ogni chiamata di un tool (tools/call) apre una sessione nuova.
Il grafo resta sincrono: il codice asincrono del client MCP passa da _esegui (asyncio.run).
"""
# librerie standard: codice asincrono, log, ambiente, interprete in uso, thread, percorsi
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# classi degli strumenti LangChain e client MCP
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient

# logger delle operazioni MCP: nel terminale compare come [mcp]
log = logging.getLogger("mcp")

CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent  # contiene app/ e mcp_assistente/
MODULO_SERVER = "mcp_assistente.server"  # server avviato con "python -m"
URI_PREFERENZE = "utente://preferenze"  # resource delle preferenze dell'utente
TIMEOUT_S = 30  # discovery, lettura o chiamata bloccata: meglio un errore che un'attesa infinita
# variabili da passare al server (il client stdio inoltra solo un elenco ristretto di variabili)
VARIABILI_SERVER = ("PREFERENZE_FILE", "FUSO_PREDEFINITO")


# errore proprio dell'adattatore: il server non parte o non pubblica tool utilizzabili
class ErroreMCP(Exception):
    """Il server MCP non parte o non pubblica tool utilizzabili."""


# descrive come avviare il server: comando, argomenti, cartella, variabili d'ambiente
def configurazione_server(modulo: str = MODULO_SERVER) -> dict:
    """Voce di MultiServerMCPClient: il server e' un processo figlio con lo stesso interprete."""
    # FASTMCP_LOG_LEVEL=CRITICAL: niente righe di FastMCP nel terminale della chat;
    # PYTHONIOENCODING=utf-8: accenti leggibili anche con stderr rediretto (Windows: cp1252)
    env = {"FASTMCP_LOG_LEVEL": "CRITICAL", "PYTHONIOENCODING": "utf-8"}
    # solo le variabili impostate e non vuote
    env.update({v: os.environ[v] for v in VARIABILI_SERVER if os.environ.get(v, "").strip()})
    # sys.executable: lo stesso Python del programma (quello del venv)
    return {"command": sys.executable, "args": ["-m", modulo], "transport": "stdio",
            "cwd": str(CARTELLA_PROGETTO), "env": env}


# controlla che lo schema del tool sia accettato da gemma in LM Studio
def schema_valido(tool: BaseTool) -> bool:
    """Ogni argomento ha "type" e nessun "anyOf" (il template di gemma lo richiede)."""
    proprieta = (tool.args_schema or {}).get("properties") or {}
    return all(isinstance(s, dict) and "type" in s and "anyOf" not in s
               for s in proprieta.values())


# ponte tra il client MCP asincrono e il programma sincrono
def _esegui(fabbrica):
    """Esegue la coroutine creata da `fabbrica` con un timeout. Se nel thread c'e' gia' un event
    loop attivo (asyncio.run non si puo' annidare) la esegue in un thread separato."""
    async def corpo():
        return await asyncio.wait_for(fabbrica(), TIMEOUT_S)

    # get_running_loop solleva RuntimeError se non c'e' un event loop: caso normale
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corpo())
    with ThreadPoolExecutor(max_workers=1) as esecutore:
        return esecutore.submit(lambda: asyncio.run(corpo())).result()


# messaggio leggibile da un errore, anche da un gruppo di errori del trasporto
def _motivo(errore: BaseException) -> str:
    # un gruppo puo' contenere altri gruppi: si scende fino al primo errore vero
    while isinstance(errore, BaseExceptionGroup) and errore.exceptions:
        errore = errore.exceptions[0]
    return str(errore) or type(errore).__name__


# trasforma il contenuto di un risultato MCP in una sola stringa
def _testo(contenuto) -> str:
    if isinstance(contenuto, str):
        return contenuto
    # elenco di blocchi: si uniscono i testi
    if isinstance(contenuto, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in contenuto)
    return str(contenuto)


# avvolge un tool MCP asincrono in un tool LangChain sincrono, usabile dal ToolNode del grafo
def _sincrono(tool_async: BaseTool) -> StructuredTool:
    """Stesso nome, descrizione e schema; esecuzione sincrona; errori come ToolException."""
    def esegui(**argomenti) -> str:
        # evidenza dello step 4: la chiamata del modello passa da tools/call
        log.info("tools/call %s %s", tool_async.name, argomenti)
        try:
            # la coroutine restituisce (contenuto, artefatti): gli artefatti non servono
            contenuto, _ = _esegui(lambda: tool_async.coroutine(**argomenti))
        except ToolException as errore:
            # errore del tool: il messaggio del server arriva al modello
            raise ToolException(_testo(errore.args[0] if errore.args else "")) from None
        except Exception as errore:  # trasporto: server caduto, non avviabile, bloccato
            raise ToolException(f"Server MCP non disponibile: {_motivo(errore)}") from None
        return _testo(contenuto)

    # handle_tool_error=True: l'errore diventa un ToolMessage per il modello, non un crash
    return StructuredTool(name=tool_async.name, description=tool_async.description,
                          args_schema=tool_async.args_schema, func=esegui,
                          metadata=tool_async.metadata, handle_tool_error=True)


# client MCP con il solo server dell'assistente, chiamato "server"
def _client(modulo: str) -> MultiServerMCPClient:
    return MultiServerMCPClient({"server": configurazione_server(modulo)})


# discovery (tools/list): tool del server pronti per il grafo
def carica_strumenti(modulo: str = MODULO_SERVER) -> list[BaseTool]:
    """Avvia il server e chiede i suoi tool; scarta con un avviso quelli con schema non valido."""
    try:
        scoperti = _esegui(_client(modulo).get_tools)
    except Exception as errore:
        raise ErroreMCP(f"{modulo}: {_motivo(errore)}") from None
    validi = []
    for tool in scoperti:
        if schema_valido(tool):
            validi.append(_sincrono(tool))
        else:
            log.warning("tool %s scartato: schema con anyOf o senza type", tool.name)
    if not validi:
        raise ErroreMCP(f"il server {modulo} non pubblica tool utilizzabili")
    log.info("tools/list: %s", ", ".join(t.name for t in validi))
    return validi


# lettura della resource delle preferenze (resources/read): testo del file oppure None
def leggi_preferenze(modulo: str = MODULO_SERVER) -> str | None:
    """Una sessione MCP breve; ogni errore (server, file mancante) diventa None con un avviso."""
    client = _client(modulo)

    # apre una sessione con il server e legge la resource
    async def leggi():
        async with client.session("server") as sessione:
            risultato = await sessione.read_resource(URI_PREFERENZE)
            return risultato.contents[0].text

    # evidenza dello step 4: la lettura e' dell'host, prima di chiamare il modello
    log.info("resources/read %s", URI_PREFERENZE)
    try:
        return _esegui(leggi)
    except Exception as errore:
        log.warning("resources/read %s non riuscita: %s", URI_PREFERENZE, _motivo(errore))
        return None
