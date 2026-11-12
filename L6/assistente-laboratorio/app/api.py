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

# FastAPI: applicazione, errori di validazione, risposte JSON
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
# messaggi LangChain; errori del client OpenAI verso LM Studio
from langchain_core.messages import HumanMessage
from openai import (APIConnectionError, APIError, APIStatusError, APITimeoutError,
                    LengthFinishReasonError)

# parti del progetto: errori MCP, messaggi degli errori del modello, schemi
from app.adattatore_mcp import ErroreMCP, PromptNonValido
from app.errori import MSG_CONNESSIONE, messaggio_errore_generico, messaggio_errore_http
from app.schemi import (Errore, PromptPubblicato, RichiestaChat, RispostaChat, Stato,
                        StrumentoUsato, a_openai, da_info, da_openai)

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


# corpo d'errore uniforme
def _errore(codice_http: int, errore: str, messaggio: str) -> JSONResponse:
    log.info("→ %d %s: %s", codice_http, errore, messaggio)
    return JSONResponse(status_code=codice_http,
                        content=Errore(errore=errore, messaggio=messaggio).model_dump())


# primo errore di validazione in italiano: "campo cronologia.0.role: valore non ammesso"
def _testo_validazione(errore: RequestValidationError) -> str:
    primo = errore.errors()[0]
    # percorso senza "body" (dettaglio interno di FastAPI)
    percorso = ".".join(str(p) for p in primo.get("loc", ()) if p != "body")
    tipo = primo.get("type", "")
    if tipo == "value_error":
        # errori scritti da noi negli schemi: si tiene il testo senza il prefisso di Pydantic
        problema = str(primo.get("msg", "")).removeprefix("Value error, ")
    elif tipo == "literal_error":
        problema = f"valore non ammesso (ammessi: {primo.get('ctx', {}).get('expected', '')})"
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

    @app.exception_handler(CronologiaNonValida)
    async def _cronologia(request: Request, e: CronologiaNonValida):
        return _errore(422, "richiesta_non_valida", str(e))

    @app.exception_handler(PromptNonValido)
    async def _prompt(request: Request, e: PromptNonValido):
        return _errore(422, "prompt_non_valido", str(e))

    @app.exception_handler(ErroreMCP)
    async def _mcp(request: Request, e: ErroreMCP):
        return _errore(503, "mcp_non_disponibile", str(e))

    # APITimeoutError e' una sottoclasse di APIConnectionError: ha il suo gestore
    @app.exception_handler(APITimeoutError)
    async def _timeout(request: Request, e: APITimeoutError):
        return _errore(504, "modello_in_timeout", MSG_TIMEOUT)

    @app.exception_handler(APIConnectionError)
    async def _connessione(request: Request, e: APIConnectionError):
        return _errore(503, "modello_non_raggiungibile", MSG_CONNESSIONE)

    @app.exception_handler(APIStatusError)
    async def _http(request: Request, e: APIStatusError):
        return _errore(502, "errore_del_modello", messaggio_errore_http(e))

    # LengthFinishReasonError non e' un APIError: gestore a parte
    @app.exception_handler(APIError)
    @app.exception_handler(LengthFinishReasonError)
    async def _modello(request: Request, e):
        return _errore(502, "errore_del_modello", messaggio_errore_generico(e))

    # tutto il resto: 500 con un messaggio fisso, traceback solo nel log
    @app.exception_handler(Exception)
    async def _interno(request: Request, e: Exception):
        log.exception("errore interno")
        return _errore(500, "errore_interno", MSG_INTERNO)


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

    @app.post("/chat", response_model=RispostaChat, responses=RISPOSTE_ERRORE)
    def chat(richiesta: RichiestaChat, request: Request) -> RispostaChat:
        """Un turno della conversazione: messaggio (o prompt del server MCP), cronologia e
        riassunto del chiamante; restituisce la risposta e la cronologia aggiornata."""
        agente = request.app.state.agente
        inizio = time.perf_counter()
        tipo = (f"prompt {richiesta.prompt.nome}" if richiesta.prompt else "messaggio")
        log.info("POST /chat %s, cronologia %d", tipo, len(richiesta.cronologia))
        # cronologia OpenAI -> messaggi LangChain (raro: un messaggio non convertibile)
        try:
            cronologia = da_openai(richiesta.cronologia)
        except Exception as errore:
            raise CronologiaNonValida(f"cronologia non convertibile: {errore}") from None
        if richiesta.prompt:
            nuovi = agente.messaggi_prompt(richiesta.prompt.nome, richiesta.prompt.argomenti)
        else:
            nuovi = [HumanMessage(richiesta.messaggio)]
        esito = agente.turno(nuovi, cronologia, richiesta.riassunto)
        log.info("→ 200 categoria=%s argomento=%s strumenti=%s in %.1fs", esito.categoria,
                 esito.argomento, [s["nome"] for s in esito.strumenti_usati],
                 time.perf_counter() - inizio)
        return RispostaChat(risposta=esito.risposta,
                            strumenti_usati=[StrumentoUsato(**s) for s in esito.strumenti_usati],
                            categoria=esito.categoria, argomento=esito.argomento,
                            cronologia=a_openai(esito.messaggi), riassunto=esito.riassunto)

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
