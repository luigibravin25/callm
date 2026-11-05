"""Adattatore MCP: scopre i tool del server del catalogo e li rende tool LangChain sincroni.

Il server (mcp_catalogo/server.py) si avvia come sottoprocesso (trasporto stdio). La discovery
(tools/list) avviene una volta, all'avvio; ogni chiamata (tools/call) apre una sessione nuova.
Il grafo resta sincrono: ogni tool asincrono dell'adattatore e' eseguito con asyncio.run.
"""
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient

# cartella che contiene app/ e mcp_catalogo/
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent
MODULO_SERVER = "mcp_catalogo.server"
TIMEOUT_S = 30  # discovery o chiamata bloccata: meglio un errore che un'attesa infinita
MSG_NON_DISPONIBILE = "Server MCP del catalogo non disponibile"


class ErroreMCP(Exception):
    """Il server MCP non parte o non pubblica tool utilizzabili."""


def configurazione_server(modulo: str = MODULO_SERVER, cartella: Path = CARTELLA_PROGETTO) -> dict:
    """Voce di MultiServerMCPClient: il server e' un processo figlio con lo stesso interprete."""
    # il server riparte a ogni chiamata e scrive su stderr (il terminale della chat): solo
    # avvisi ed errori, niente righe INFO; mcp unisce env alle variabili predefinite
    return {"command": sys.executable, "args": ["-m", modulo], "transport": "stdio",
            "cwd": str(cartella), "env": {"FASTMCP_LOG_LEVEL": "WARNING"}}


def schema_valido(tool: BaseTool) -> bool:
    """Ogni argomento ha "type" e nessun "anyOf" (il template di gemma lo richiede).
    Un tool senza argomenti (nessuna "properties") e' valido."""
    if isinstance(tool.args_schema, dict):
        proprieta = tool.args_schema.get("properties") or {}
    else:
        proprieta = tool.args  # schema Pydantic: gia' l'elenco degli argomenti
    return all(isinstance(s, dict) and "type" in s and "anyOf" not in s
               for s in proprieta.values())


def _esegui(fabbrica):
    """Esegue la coroutine creata da `fabbrica` con un timeout. Se nel thread c'e' gia' un event
    loop attivo (asyncio.run non si puo' annidare) la esegue in un thread separato."""
    async def corpo():
        return await asyncio.wait_for(fabbrica(), TIMEOUT_S)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corpo())
    with ThreadPoolExecutor(max_workers=1) as esecutore:
        return esecutore.submit(lambda: asyncio.run(corpo())).result()


def _motivo(errore: BaseException) -> str:
    """Messaggio leggibile, anche da un ExceptionGroup del trasporto."""
    while isinstance(errore, BaseExceptionGroup) and errore.exceptions:
        errore = errore.exceptions[0]
    return str(errore) or type(errore).__name__


def _testo(contenuto) -> str:
    """Contenuto MCP (stringa o blocchi) come testo semplice per il ToolMessage."""
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in contenuto)
    return str(contenuto)


def _sincrono(tool_async: BaseTool) -> StructuredTool:
    """Stesso nome, descrizione e schema; esecuzione sincrona; errori come ToolException."""
    def esegui(**argomenti) -> str:
        try:
            contenuto, _ = _esegui(lambda: tool_async.coroutine(**argomenti))
        except ToolException as errore:
            # errore del tool (isError): il messaggio del server arriva al modello
            raise ToolException(_testo(errore.args[0] if errore.args else "")) from None
        except Exception as errore:  # trasporto: server caduto, non avviabile, bloccato
            raise ToolException(f"{MSG_NON_DISPONIBILE}: {_motivo(errore)}") from None
        return _testo(contenuto)

    return StructuredTool(name=tool_async.name, description=tool_async.description,
                          args_schema=tool_async.args_schema, func=esegui,
                          handle_tool_error=True)


def carica_strumenti_mcp(modulo: str = MODULO_SERVER,
                         cartella: Path = CARTELLA_PROGETTO) -> list[BaseTool]:
    """Discovery (tools/list) una volta; scarta con un avviso i tool con schema non valido."""
    client = MultiServerMCPClient({"catalogo": configurazione_server(modulo, cartella)})
    try:
        scoperti = _esegui(client.get_tools)
    except Exception as errore:
        # il contesto ("catalogo MCP non disponibile") lo aggiunge app.cli.carica_strumenti
        raise ErroreMCP(f"{modulo}: {_motivo(errore)}") from None
    validi = []
    for tool in scoperti:
        if schema_valido(tool):
            validi.append(_sincrono(tool))
        else:
            print(f"Avviso: tool MCP {tool.name} scartato, schema con anyOf o senza type.",
                  file=sys.stderr)
    if not validi:
        raise ErroreMCP(f"il server {modulo} non pubblica tool utilizzabili.")
    return validi
