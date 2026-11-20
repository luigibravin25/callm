"""Adattatore MCP (come L5): collega l'host al server mcp_assistente (trasporto stdio).

All'avvio: discovery dei tool (tools/list), lettura della resource delle preferenze
(resources/read) ed elenco dei prompt (prompts/list), una volta. Ogni chiamata di un tool
(tools/call) e ogni prompt richiamato dall'utente con /prompt (prompts/get) apre una sessione nuova.
Il grafo resta sincrono: il codice asincrono del client MCP passa da _esegui (asyncio.run).
"""
# librerie standard: codice asincrono, log, ambiente, interprete in uso, thread, percorsi
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# classi dei messaggi e degli strumenti LangChain, client MCP, conversione dei prompt in messaggi
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.prompts import load_mcp_prompt

# tipi dei prompt senza dipendenze da MCP (riesportati: i test e i moduli vecchi li prendono da qui)
from app.info_prompt import InfoArgomento, InfoPrompt  # noqa: F401
# errore restituito dal server MCP (per esempio il PromptError di un valore non ammesso)
from mcp.shared.exceptions import McpError
# codice di McpError quando il processo del server si chiude (non parte o cade)
from mcp.types import CONNECTION_CLOSED

# logger delle operazioni MCP: nel terminale compare come [mcp]
log = logging.getLogger("mcp")

CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent  # contiene app/ e mcp_assistente/
MODULO_SERVER = "mcp_assistente.server"  # server avviato con "python -m"
URI_PREFERENZE = "utente://preferenze"  # resource delle preferenze dell'utente
# discovery, lettura o chiamata bloccata: meglio un errore che un'attesa infinita; 60 s perché una ricerca in
# modalità entrambe (riscrittura + reranking con gemma) dura fino a ~28 s più l'avvio del server (lezione 8, es. 3)
TIMEOUT_S = 60
# variabili da passare al server (il client stdio inoltra solo un elenco ristretto di variabili)
VARIABILI_SERVER = ("PREFERENZE_FILE", "FUSO_PREDEFINITO")
# lezione 8: server di ricerca della cartella ricerca/ accanto a questo progetto, avviato con "python -m"
CARTELLA_RICERCA = CARTELLA_PROGETTO.parent / "ricerca"
MODULO_RICERCA = "mcp_ricerca.server"
# variabili della ricerca da passare al suo server (le CHUNK_* le controlla la sua configurazione;
# dall'esercizio 3 anche modello di chat, modalità, candidati e tetto del reranking; dall'esercizio 4 le soglie)
VARIABILI_RICERCA = ("EMBEDDING_MODEL", "LM_BASE_URL", "QDRANT_URL", "QDRANT_COLLEZIONE",
                     "CHUNK_STRATEGIA", "CHUNK_DIMENSIONE", "CHUNK_OVERLAP",
                     "LM_MODEL", "RICERCA_MODALITA", "RICERCA_CANDIDATI", "RERANK_TETTO",
                     "SOGLIA_ALTA", "SOGLIA_BASSA")


# errore proprio dell'adattatore: il server non parte o non pubblica tool utilizzabili
class ErroreMCP(Exception):
    """Il server MCP non parte o non pubblica tool utilizzabili."""


# il server ha risposto ma ha rifiutato il prompt (nome sconosciuto o valore non ammesso)
class PromptNonValido(ErroreMCP):
    """Prompt rifiutato dal server o dal controllo degli argomenti: errore di chi lo chiede."""


# primo errore vero dentro un gruppo di eccezioni (anyio raccoglie gli errori in gruppi)
def _radice(errore: BaseException) -> BaseException:
    while isinstance(errore, BaseExceptionGroup) and errore.exceptions:
        errore = errore.exceptions[0]
    return errore


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


# descrive come avviare il server di ricerca (lezione 8): stesso schema del server dell'assistente
def configurazione_ricerca(cartella: Path = CARTELLA_RICERCA) -> dict:
    """Voce di MultiServerMCPClient per mcp_ricerca.server, avviato dalla cartella della ricerca."""
    # stesse variabili fisse dell'altro server: FastMCP silenzioso, accenti leggibili su stderr
    env = {"FASTMCP_LOG_LEVEL": "CRITICAL", "PYTHONIOENCODING": "utf-8"}
    # solo le variabili della ricerca impostate e non vuote
    env.update({v: os.environ[v] for v in VARIABILI_RICERCA if os.environ.get(v, "").strip()})
    return {"command": sys.executable, "args": ["-m", MODULO_RICERCA], "transport": "stdio",
            "cwd": str(cartella), "env": env}


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


# discovery del server di ricerca (lezione 8): se non parte l'agente resta senza ricerca
def carica_strumenti_ricerca(cartella: Path = CARTELLA_RICERCA) -> list[BaseTool]:
    """tools/list del solo server di ricerca; ogni errore diventa un elenco vuoto con un avviso."""
    client = MultiServerMCPClient({"ricerca": configurazione_ricerca(cartella)})
    try:
        scoperti = _esegui(client.get_tools)
    except Exception as errore:
        log.warning("server ricerca non disponibile (%s): nessuna ricerca", _motivo(errore))
        return []
    # stesso filtro dello schema e stessi tool sincroni del server dell'assistente
    validi = [_sincrono(t) for t in scoperti if schema_valido(t)]
    for tool in scoperti:
        if not schema_valido(tool):
            log.warning("tool %s scartato: schema con anyOf o senza type", tool.name)
    # server partito ma senza tool utilizzabili: per l'agente è come se non ci fosse
    if not validi:
        log.warning("server ricerca non disponibile (nessun tool utilizzabile): nessuna ricerca")
        return []
    log.info("tools/list ricerca: %s", ", ".join(t.name for t in validi))
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


# --- prompt (step 5) ---

# tipi dei prompt (InfoPrompt, InfoArgomento): stanno in app/info_prompt.py, importati in cima


# elenco dei prompt (prompts/list), chiesto una volta all'avvio della sessione
def elenca_prompt(modulo: str = MODULO_SERVER) -> list[InfoPrompt]:
    """Una sessione MCP breve; ogni errore diventa un elenco vuoto con un avviso."""
    client = _client(modulo)

    # apre una sessione con il server e chiede l'elenco
    async def elenca():
        async with client.session("server") as sessione:
            return (await sessione.list_prompts()).prompts

    try:
        pubblicati = _esegui(elenca)
    except Exception as errore:
        log.warning("prompts/list non riuscita: %s", _motivo(errore))
        return []
    # descrizione o "required" assenti: stringa vuota e argomento facoltativo
    prompts = [InfoPrompt(p.name, p.description or "",
                          tuple(InfoArgomento(a.name, bool(a.required))
                                for a in (p.arguments or [])))
               for p in pubblicati]
    log.info("prompts/list: %s", ", ".join(p.nome for p in prompts))
    return prompts


# un prompt richiamato dall'utente (prompts/get): messaggi LangChain pronti per la cronologia
def ottieni_prompt(nome: str, argomenti: dict[str, str],
                   modulo: str = MODULO_SERVER) -> list[BaseMessage]:
    """Sessione nuova; ogni errore (valore rifiutato, server non disponibile) diventa ErroreMCP
    con il motivo."""
    client = _client(modulo)

    # apre una sessione e converte i messaggi del prompt in messaggi LangChain
    async def ottieni():
        async with client.session("server") as sessione:
            return await load_mcp_prompt(sessione, nome, arguments=argomenti)

    # evidenza dello step 5: prompt richiamato e argomenti
    log.info("prompts/get %s %s", nome, argomenti)
    try:
        messaggi = _esegui(ottieni)
    except Exception as errore:
        motivo = _motivo(errore)
        log.warning("prompts/get %s non riuscita: %s", nome, motivo)
        # McpError = il server ha risposto con un errore (valore rifiutato, prompt sconosciuto):
        # colpa della richiesta; con CONNECTION_CLOSED invece il server non e' partito o e'
        # caduto, come ogni altro errore (timeout): colpa del server
        radice = _radice(errore)
        if isinstance(radice, McpError) and radice.error.code != CONNECTION_CLOSED:
            raise PromptNonValido(motivo) from None
        raise ErroreMCP(motivo) from None
    # evidenza dello step 5: messaggi ottenuti dal server, con tipo e testo
    parola = "messaggio" if len(messaggi) == 1 else "messaggi"
    testi = " | ".join(f"{m.type}: {m.content}" for m in messaggi)
    log.info("prompts/get %s: %d %s: %s", nome, len(messaggi), parola, testi)
    return messaggi
