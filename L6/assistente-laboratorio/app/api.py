"""Servizio HTTP dell'agente (step 6): lo stesso grafo della CLI, esposto con FastAPI.

POST /chat riceve messaggio (o prompt), cronologia e riassunto e restituisce la risposta con la
cronologia aggiornata: l'agente e' senza stato. GET /prompts e GET /stato completano l'API;
la documentazione OpenAPI e' su /docs. Avvio: python -m app.api (AGENTE_HOST, AGENTE_PORTA).
"""
# librerie standard: log, ambiente, tempo della richiesta, gestione del ciclo di vita
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Callable

# libreria standard: lettura dei valori ammessi nei messaggi di Pydantic
import re

# FastAPI: applicazione, errori di validazione, risposte JSON; errori HTTP di Starlette (404, 405)
import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
# messaggi LangChain; errori del client OpenAI verso LM Studio
from langchain_core.messages import HumanMessage
from openai import (APIConnectionError, APIError, APIStatusError, APITimeoutError,
                    LengthFinishReasonError)

# parti del progetto: errori MCP, messaggi degli errori del modello, schemi
from app.adattatore_mcp import ErroreMCP, PromptNonValido
from app.errori import MSG_CONNESSIONE, messaggio_errore_generico, messaggio_errore_http
from app.schemi import (Errore, PromptPubblicato, RichiestaChat, RispostaChat, Stato,
                        StrumentoUsato, a_openai, da_info, da_openai)
from app.sse import con_ping, formatta

# logger del servizio: nel terminale compare come [api]
log = logging.getLogger("api")

HOST_PREDEFINITO = "127.0.0.1"
PORTA_PREDEFINITA = 8000
MSG_TIMEOUT = ("LM Studio non ha risposto in tempo: il modello è troppo lento o bloccato. "
               "Riprova o controlla LM Studio.")
MSG_INTERNO = "Errore interno dell'agente: dettagli nel log del servizio."
DESCRIZIONE = """Agente LangGraph dell'assistente di laboratorio, senza stato.

Errori (corpo sempre `{"errore", "messaggio"}`): 422 `richiesta_non_valida` o `prompt_non_valido`;
502 `errore_del_modello`; 503 `modello_non_raggiungibile` o `mcp_non_disponibile`;
504 `modello_in_timeout`; 500 `errore_interno`."""
# risposte d'errore documentate in OpenAPI per POST /chat
RISPOSTE_ERRORE = {codice: {"model": Errore} for codice in (422, 500, 502, 503, 504)}

# traduzione in italiano dei tipi di errore di Pydantic piu' comuni
PROBLEMI = {
    "missing": "campo obbligatorio mancante",
    "string_type": "deve essere un testo",
    "list_type": "deve essere una lista",
    "dict_type": "deve essere un oggetto",
    "model_type": "deve essere un oggetto",
    "extra_forbidden": "campo non previsto",
    "json_invalid": "il corpo non è JSON valido",
}


# un messaggio di cronologia che LangChain non riesce a convertire
class CronologiaNonValida(Exception):
    """La cronologia ha superato la validazione ma non si converte in messaggi LangChain."""


# eccezione -> (status HTTP, codice, messaggio): unica tabella per le risposte JSON e per l'evento
# "errore" dello stream; l'ordine conta (APITimeoutError e' una sottoclasse di APIConnectionError,
# LengthFinishReasonError non e' un APIError)
def errore_da_eccezione(e: Exception) -> tuple[int, str, str]:
    if isinstance(e, CronologiaNonValida):
        return 422, "richiesta_non_valida", str(e)
    if isinstance(e, PromptNonValido):
        return 422, "prompt_non_valido", str(e)
    if isinstance(e, ErroreMCP):
        return 503, "mcp_non_disponibile", str(e)
    if isinstance(e, APITimeoutError):
        return 504, "modello_in_timeout", MSG_TIMEOUT
    if isinstance(e, APIConnectionError):
        return 503, "modello_non_raggiungibile", MSG_CONNESSIONE
    if isinstance(e, APIStatusError):
        return 502, "errore_del_modello", messaggio_errore_http(e)
    if isinstance(e, (APIError, LengthFinishReasonError)):
        return 502, "errore_del_modello", messaggio_errore_generico(e)
    # tutto il resto: messaggio fisso, traceback solo nel log
    log.error("errore interno", exc_info=e)
    return 500, "errore_interno", MSG_INTERNO


# corpo d'errore uniforme
def _errore(codice_http: int, errore: str, messaggio: str) -> JSONResponse:
    log.info("→ %d %s: %s", codice_http, errore, messaggio)
    return JSONResponse(status_code=codice_http,
                        content=Errore(errore=errore, messaggio=messaggio).model_dump())


# primo errore di validazione in italiano: "campo cronologia.0.role: valore non ammesso"
def _testo_validazione(errore: RequestValidationError) -> str:
    primo = errore.errors()[0]
    # percorso senza "body" (dettaglio interno di FastAPI); indici come [n]: cronologia[0].role
    percorso = ""
    for parte in primo.get("loc", ()):
        if parte == "body":
            continue
        percorso += f"[{parte}]" if isinstance(parte, int) else (f".{parte}" if percorso else parte)
    tipo = primo.get("type", "")
    if tipo == "value_error":
        # errori scritti da noi negli schemi: si tiene il testo senza il prefisso di Pydantic
        problema = str(primo.get("msg", "")).removeprefix("Value error, ")
    elif tipo == "literal_error":
        # "'user', 'assistant' or 'tool'" -> "user, assistant o tool"
        ammessi = re.findall(r"'([^']*)'", str(primo.get("ctx", {}).get("expected", "")))
        elenco = ", ".join(ammessi[:-1]) + " o " + ammessi[-1] if len(ammessi) > 1 else             "".join(ammessi)
        problema = f"valore non ammesso (ammessi: {elenco})"
    else:
        problema = PROBLEMI.get(tipo, "valore non valido")
    # percorso numerico del JSON non valido (posizione nel testo): non e' un campo
    if tipo == "json_invalid" or not percorso:
        return problema
    return f"campo {percorso}: {problema}"


# registra la mappa degli errori sull'applicazione (FastAPI sceglie la classe piu' specifica)
def _registra_errori(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validazione(request: Request, e: RequestValidationError):
        return _errore(422, "richiesta_non_valida", _testo_validazione(e))

    # errori HTTP di Starlette (percorso inesistente, metodo sbagliato, corpo illeggibile): stesso
    # corpo {errore, messaggio} di tutti gli altri errori
    @app.exception_handler(StarletteHTTPException)
    async def _http_starlette(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            return _errore(404, "percorso_non_trovato",
                           f"Percorso non trovato: {request.url.path}. Percorsi: /chat, "
                           "/prompts, /stato, /docs.")
        if e.status_code == 405:
            return _errore(405, "metodo_non_ammesso",
                           f"Metodo {request.method} non ammesso su {request.url.path}.")
        return _errore(e.status_code, "richiesta_non_valida",
                       "Richiesta non leggibile: serve un corpo JSON in UTF-8.")

    # errori del turno (modello, MCP, prompt, cronologia) e tutto il resto: una sola tabella,
    # la stessa usata dallo stream per l'evento "errore"
    @app.exception_handler(CronologiaNonValida)
    @app.exception_handler(PromptNonValido)
    @app.exception_handler(ErroreMCP)
    @app.exception_handler(APIError)
    @app.exception_handler(LengthFinishReasonError)
    @app.exception_handler(Exception)
    async def _turno(request: Request, e: Exception):
        return _errore(*errore_da_eccezione(e))


# messaggi del turno dalla richiesta: cronologia convertita e messaggi nuovi (o del prompt MCP)
def _prepara_turno(agente, richiesta: RichiestaChat, percorso: str):
    tipo = (f"prompt {richiesta.prompt.nome}" if richiesta.prompt else "messaggio")
    log.info("%s %s, cronologia %d", percorso, tipo, len(richiesta.cronologia))
    # cronologia OpenAI -> messaggi LangChain (raro: un messaggio non convertibile)
    try:
        cronologia = da_openai(richiesta.cronologia)
    except Exception as errore:
        raise CronologiaNonValida(f"cronologia non convertibile: {errore}") from None
    if richiesta.prompt:
        nuovi = agente.messaggi_prompt(richiesta.prompt.nome, richiesta.prompt.argomenti)
    else:
        nuovi = [HumanMessage(richiesta.messaggio)]
    return nuovi, cronologia


# riga di log a turno completato
def _log_esito(esito, inizio: float) -> None:
    log.info("→ 200 categoria=%s argomento=%s strumenti=%s in %.1fs", esito.categoria,
             esito.argomento, [s["nome"] for s in esito.strumenti_usati],
             time.perf_counter() - inizio)


# corpo della risposta di POST /chat (e dell'evento "fine" dello stream)
def _risposta(esito) -> RispostaChat:
    return RispostaChat(risposta=esito.risposta,
                        strumenti_usati=[StrumentoUsato(**s) for s in esito.strumenti_usati],
                        categoria=esito.categoria, argomento=esito.argomento,
                        cronologia=a_openai(esito.messaggi), riassunto=esito.riassunto)


# chiude il generatore; se un next() e' ancora in corso in un altro thread (annullamento a meta'
# lettura) close() solleva ValueError: si riprova finche' finisce (al massimo un ping, ~5 s)
def _chiudi(generatore) -> None:
    for _ in range(200):
        try:
            generatore.close()
            return
        except ValueError:
            time.sleep(0.05)


# corpo asincrono di una StreamingResponse da un generatore sincrono: alla chiusura (anche per un
# client disconnesso) il generatore si chiude subito, cosi' smette di consumare il grafo
async def _corpo(generatore):
    try:
        async for parte in iterate_in_threadpool(generatore):
            yield parte
    finally:
        # scope protetto: con il client disconnesso il task e' annullato e senza protezione
        # l'await qui verrebbe annullato a sua volta (la chiusura resterebbe al garbage collector)
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(_chiudi, generatore)


# crea l'applicazione; `prepara_agente` costruisce l'agente all'avvio (i test passano un finto)
def crea_app(prepara_agente: Callable) -> FastAPI:
    # ciclo di vita: l'agente (server MCP, grafo) si prepara una volta all'avvio
    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI):
        agente = prepara_agente()
        app.state.agente = agente
        log.info("pronto: strumenti %s, prompt %s, documentazione su /docs",
                 ", ".join(agente.strumenti) or "nessuno",
                 ", ".join(p.nome for p in agente.prompts) or "nessuno")
        yield
        # sessioni MCP brevi: alla chiusura non resta niente di aperto
        log.info("chiuso")

    app = FastAPI(title="Assistente di laboratorio · Agente", description=DESCRIZIONE,
                  version="6.0", lifespan=ciclo_di_vita)
    _registra_errori(app)

    # exclude_none: niente campi null nella cronologia (formato OpenAI canonico)
    @app.post("/chat", response_model=RispostaChat, responses=RISPOSTE_ERRORE,
              response_model_exclude_none=True)
    def chat(richiesta: RichiestaChat, request: Request) -> RispostaChat:
        """Un turno della conversazione: messaggio (o prompt del server MCP), cronologia e
        riassunto del chiamante; restituisce la risposta e la cronologia aggiornata."""
        agente = request.app.state.agente
        inizio = time.perf_counter()
        nuovi, cronologia = _prepara_turno(agente, richiesta, "POST /chat")
        esito = agente.turno(nuovi, cronologia, richiesta.riassunto)
        _log_esito(esito, inizio)
        return _risposta(esito)

    # lo stesso turno in streaming (step 10): eventi SSE fase, bozza, testo, strumento,
    # revisione, fine (corpo di POST /chat) oppure errore; ": ping" ogni 5 s nei silenzi
    @app.post("/chat/stream", response_class=StreamingResponse, responses={
        **RISPOSTE_ERRORE, 200: {"description": "Eventi SSE del turno", "content": {
            "text/event-stream": {"schema": {"type": "string"}}}}})
    def chat_stream(richiesta: RichiestaChat, request: Request):
        """Come POST /chat, ma la risposta arriva a pezzi mentre il modello la scrive.
        Errori di validazione e del prompt in JSON prima dello stream; dopo, evento `errore`."""
        agente = request.app.state.agente
        inizio = time.perf_counter()
        nuovi, cronologia = _prepara_turno(agente, richiesta, "POST /chat/stream")

        def righe():
            try:
                for evento in agente.turno_in_flusso(nuovi, cronologia, richiesta.riassunto):
                    if evento.tipo == "fine":
                        _log_esito(evento.dati, inizio)
                        dati = _risposta(evento.dati).model_dump(mode="json", exclude_none=True)
                    else:
                        dati = evento.dati
                    yield formatta(evento.tipo, dati)
            except Exception as errore:
                status, codice, messaggio = errore_da_eccezione(errore)
                log.warning("stream interrotto: %d %s", status, codice)
                yield formatta("errore", {"errore": codice, "messaggio": messaggio})

        return StreamingResponse(_corpo(con_ping(righe())), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/prompts", response_model=list[PromptPubblicato])
    def prompts(request: Request) -> list[PromptPubblicato]:
        """Prompt del server MCP letti all'avvio (vuoto se il server non e' partito)."""
        return [da_info(p) for p in request.app.state.agente.prompts]

    @app.get("/stato", response_model=Stato, responses={503: {"model": Stato}})
    def stato(request: Request):
        """Stato dal vivo: LM Studio con il modello caricato e server MCP raggiungibile.
        200 se tutto e' pronto, 503 altrimenti (il corpo dice cosa manca)."""
        dati = request.app.state.agente.stato()
        pronto = dati.modello.stato == "ok" and dati.mcp.stato == "ok"
        log.info("GET /stato → modello %s, mcp %s", dati.modello.stato, dati.mcp.stato)
        return JSONResponse(status_code=200 if pronto else 503, content=dati.model_dump())

    return app


# legge AGENTE_PORTA: intero tra 1 e 65535
def _porta() -> int:
    grezzo = os.environ.get("AGENTE_PORTA", str(PORTA_PREDEFINITA)).strip()
    if not grezzo.isdigit() or not 1 <= int(grezzo) <= 65535:
        raise ValueError(f"AGENTE_PORTA deve essere un intero tra 1 e 65535, trovato: {grezzo!r}")
    return int(grezzo)


# avvio del servizio (python -m app.api): configurazione controllata PRIMA di uvicorn
def main() -> None:
    # import qui: servono solo all'avvio vero
    import uvicorn
    from app.agente import prepara
    from app.config import load_ambito, load_settings
    from app.log import LOG_GRAFO, LOG_HTTP, LOGGER_GRAFO, configura_log
    try:
        impostazioni = load_settings()
        ambito = load_ambito(impostazioni.ambito_file)
        host = os.environ.get("AGENTE_HOST", "").strip() or HOST_PREDEFINITO
        porta = _porta()
    except ValueError as errore:
        # SystemExit mostra solo il messaggio, senza traceback (un errore nel lifespan
        # farebbe stampare a uvicorn tutto il traceback)
        raise SystemExit(f"Configurazione non valida: {errore}")
    http = ("httpx", "httpx2")
    configura_log((LOGGER_GRAFO if LOG_GRAFO else ()) + (http if LOG_HTTP else ()),
                  spenti=() if LOG_HTTP else http)
    # log_config=None: uvicorn usa la configurazione dei log appena fatta
    uvicorn.run(crea_app(lambda: prepara(impostazioni, ambito)), host=host, port=porta,
                log_config=None)


if __name__ == "__main__":
    main()
