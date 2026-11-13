"""Servizio HTTP del back-end (step 7): chat salvate in PostgreSQL, domande inoltrate all'agente.

Unico punto di contatto del front-end: il front-end non conosce l'agente. Cinque operazioni
(creare, elencare, leggere, inviare un messaggio, eliminare); documentazione OpenAPI su /docs.
Avvio: python -m app.api (DATABASE_URL, AGENTE_URL, AGENTE_TIMEOUT, BACKEND_HOST, BACKEND_PORTA).
"""
# librerie standard: log, valori ammessi nei messaggi di Pydantic, ciclo di vita del servizio
import logging
import re
from contextlib import asynccontextmanager

# FastAPI: applicazione, percorsi, errori di validazione, risposte; errori HTTP di Starlette
from fastapi import FastAPI, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as AttesaPool
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

# parti del back-end: operazioni, client dell'agente, schemi
from app import servizio
from app.client_agente import ClientAgente, ErroreAgente
from app.schemi import (ChatCompleta, ChatCreata, ChatInElenco, Errore, NuovoMessaggio, Turno)
from app.servizio import ChatNonTrovata

# logger del back-end: nel terminale compare come [backend]
log = logging.getLogger("backend")

ID_MASSIMO = 2_147_483_647  # limite della colonna integer di PostgreSQL
MSG_DATABASE = "Il database non è raggiungibile: dettagli nel log del back-end."
MSG_INTERNO = "Errore interno del back-end: dettagli nel log."
DESCRIZIONE = """Back-end dell'assistente di laboratorio: chat salvate in PostgreSQL, domande
inoltrate all'agente. Il front-end parla solo con questo servizio.

Errori (corpo sempre `{"errore", "messaggio"}`).

Del back-end: 404 `chat_non_trovata`, `percorso_non_trovato`; 405 `metodo_non_ammesso`;
422 `richiesta_non_valida` (400 se il corpo non è UTF-8); 503 `agente_non_raggiungibile`,
`database_non_disponibile`; 504 `agente_in_timeout`; 502 `risposta_agente_non_valida`;
500 `errore_interno`.

Inoltrati dall'agente con lo stesso status e corpo (solo per l'invio di un messaggio):
422 `richiesta_non_valida`; 502 `errore_del_modello`; 503 `modello_non_raggiungibile`,
`mcp_non_disponibile`; 504 `modello_in_timeout`; 500 `errore_interno`.

Se l'agente fallisce la domanda non viene salvata: il client può riprovare con lo stesso testo."""

# risposte d'errore documentate in OpenAPI
_ERR = {"model": Errore}
ERRORI_LETTURA = {404: _ERR, 422: _ERR, 500: _ERR, 503: _ERR}
ERRORI_INVIO = {c: _ERR for c in (400, 404, 422, 500, 502, 503, 504)}

# traduzione in italiano dei tipi di errore di Pydantic piu' comuni
PROBLEMI = {
    "missing": "campo obbligatorio mancante",
    "string_type": "deve essere un testo",
    "dict_type": "deve essere un oggetto",
    "model_attributes_type": "deve essere un oggetto",
    "extra_forbidden": "campo non previsto",
    "json_invalid": "il corpo non è JSON valido",
    "int_parsing": "deve essere un intero",
    "greater_than_equal": "valore fuori intervallo",
    "less_than_equal": "valore fuori intervallo",
}

# parametro di percorso: intero positivo entro il limite della colonna (oltre: 422, non 500)
ChatId = Path(ge=1, le=ID_MASSIMO, description="identificativo della chat")


# prima riga del messaggio del driver (psycopg non vi mette la password): dice perche' il
# database non risponde (porta chiusa, password sbagliata, timeout)
def motivo_database(e: Exception) -> str:
    origine = getattr(e, "orig", None) or e
    righe = str(origine).strip().splitlines()
    return righe[0] if righe else type(origine).__name__


# corpo d'errore uniforme
def _errore(codice_http: int, errore: str, messaggio: str) -> JSONResponse:
    log.info("→ %d %s: %s", codice_http, errore, messaggio)
    return JSONResponse(status_code=codice_http,
                        content=Errore(errore=errore, messaggio=messaggio).model_dump())


# primo errore di validazione in italiano: "campo testo: testo vuoto"
def _testo_validazione(errore: RequestValidationError) -> str:
    primo = errore.errors()[0]
    # percorso senza "body"/"path" (dettagli interni di FastAPI); indici come [n]
    percorso = ""
    for parte in primo.get("loc", ()):
        if parte in ("body", "path", "query"):
            continue
        percorso += f"[{parte}]" if isinstance(parte, int) else (f".{parte}" if percorso else parte)
    tipo = primo.get("type", "")
    if tipo == "value_error":
        # errori scritti da noi negli schemi: si tiene il testo senza il prefisso di Pydantic
        problema = str(primo.get("msg", "")).removeprefix("Value error, ")
    elif tipo == "literal_error":
        ammessi = re.findall(r"'([^']*)'", str(primo.get("ctx", {}).get("expected", "")))
        problema = f"valore non ammesso (ammessi: {', '.join(ammessi)})"
    else:
        problema = PROBLEMI.get(tipo, "valore non valido")
    # JSON non valido: il percorso e' una posizione nel testo, non un campo
    if tipo == "json_invalid" or not percorso:
        return problema
    return f"campo {percorso}: {problema}"


# registra la mappa degli errori sull'applicazione (FastAPI sceglie la classe piu' specifica)
def _registra_errori(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validazione(request: Request, e: RequestValidationError):
        return _errore(422, "richiesta_non_valida", _testo_validazione(e))

    # errori HTTP di Starlette (percorso inesistente, metodo sbagliato, corpo illeggibile)
    @app.exception_handler(StarletteHTTPException)
    async def _http_starlette(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            return _errore(404, "percorso_non_trovato",
                           f"Percorso non trovato: {request.url.path}. Percorsi: /chat, "
                           "/chat/{id}, /chat/{id}/messaggi, /docs.")
        if e.status_code == 405:
            return _errore(405, "metodo_non_ammesso",
                           f"Metodo {request.method} non ammesso su {request.url.path}.")
        return _errore(e.status_code, "richiesta_non_valida",
                       "Richiesta non leggibile: serve un corpo JSON in UTF-8.")

    @app.exception_handler(ChatNonTrovata)
    async def _non_trovata(request: Request, e: ChatNonTrovata):
        return _errore(404, "chat_non_trovata", str(e))

    # errori dell'agente: gia' con status, codice e messaggio della risposta
    @app.exception_handler(ErroreAgente)
    async def _agente(request: Request, e: ErroreAgente):
        return _errore(e.status, e.errore, e.messaggio)

    # database spento o caduto, o nessuna connessione libera: il motivo (senza password) nel log
    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    @app.exception_handler(AttesaPool)
    async def _database(request: Request, e: Exception):
        log.error("database non disponibile: %s", motivo_database(e))
        return _errore(503, "database_non_disponibile", MSG_DATABASE)

    # tutto il resto: 500 con un messaggio fisso, traceback solo nel log
    @app.exception_handler(Exception)
    async def _interno(request: Request, e: Exception):
        log.exception("errore interno")
        return _errore(500, "errore_interno", MSG_INTERNO)


# crea l'applicazione; i test passano un database di prova e un agente finto
def crea_app(fabbrica: sessionmaker, client: ClientAgente) -> FastAPI:
    # ciclo di vita: alla chiusura del servizio si chiudono le connessioni verso l'agente
    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI):
        yield
        client.chiudi()
        log.info("chiuso")

    app = FastAPI(title="Assistente di laboratorio · Back-end", description=DESCRIZIONE,
                  version="7.0", lifespan=ciclo_di_vita)
    _registra_errori(app)

    @app.post("/chat", response_model=ChatCreata, status_code=201, tags=["chat"],
              responses={500: _ERR, 503: _ERR})
    def crea() -> ChatCreata:
        """Crea una chat vuota (titolo «Nuova chat») e restituisce il suo identificativo."""
        with fabbrica() as s:
            return ChatCreata.model_validate(servizio.crea_chat(s))

    @app.get("/chat", response_model=list[ChatInElenco], tags=["chat"],
             responses={500: _ERR, 503: _ERR})
    def elenca() -> list[ChatInElenco]:
        """Elenco delle chat con titolo e data dell'ultimo messaggio, le più recenti prima."""
        with fabbrica() as s:
            return [ChatInElenco.model_validate(c) for c in servizio.elenca_chat(s)]

    @app.get("/chat/{chat_id}", response_model=ChatCompleta, tags=["chat"],
             responses=ERRORI_LETTURA)
    def leggi(chat_id: int = ChatId) -> ChatCompleta:
        """Una chat con i messaggi in ordine cronologico."""
        with fabbrica() as s:
            return ChatCompleta.model_validate(servizio.leggi_chat(s, chat_id))

    @app.post("/chat/{chat_id}/messaggi", response_model=Turno, tags=["chat"],
              responses=ERRORI_INVIO)
    def invia(corpo: NuovoMessaggio, chat_id: int = ChatId) -> Turno:
        """Salva la domanda, chiama l'agente, salva e restituisce la risposta. Se l'agente
        fallisce la domanda non resta salvata e arriva l'errore (riprovare con lo stesso testo)."""
        domanda, risposta = servizio.invia_messaggio(fabbrica, client, chat_id, corpo.testo)
        return Turno(domanda=domanda, risposta=risposta)

    @app.delete("/chat/{chat_id}", status_code=204, response_class=Response, tags=["chat"],
                responses=ERRORI_LETTURA)
    def elimina(chat_id: int = ChatId) -> Response:
        """Elimina la chat e tutti i suoi messaggi."""
        with fabbrica() as s:
            servizio.elimina_chat(s, chat_id)
        return Response(status_code=204)

    return app


# avvio del servizio (python -m app.api): configurazione e database controllati PRIMA di uvicorn
def main() -> None:
    # import qui: servono solo all'avvio vero
    import uvicorn
    from app.config import leggi_impostazioni, maschera_url
    from app.db import crea_motore, crea_tabelle, fabbrica_sessioni
    from app.log import LOG_HTTP, configura_log
    try:
        impostazioni = leggi_impostazioni()
    except ValueError as errore:
        # SystemExit mostra solo il messaggio, senza traceback
        raise SystemExit(f"Configurazione non valida: {errore}")
    configura_log(("backend",) + (("httpx",) if LOG_HTTP else ()),
                  spenti=("httpcore",) if LOG_HTTP else ("httpx", "httpcore"))
    url = maschera_url(impostazioni.database_url)
    motore = crea_motore(impostazioni.database_url)
    try:
        crea_tabelle(motore)
    except (OperationalError, InterfaceError) as errore:
        motore.dispose()
        # motivo del driver: porta chiusa (container spento) o password sbagliata si distinguono
        raise SystemExit(f"Database non raggiungibile su {url}: {motivo_database(errore)}. "
                         "È avviato il database (il container di sviluppo o il servizio di Compose)? "
                         "DATABASE_URL è giusta?") from None
    log.info("database pronto (tabelle chat, messaggi) su %s", url)
    log.info("agente: %s (timeout %d s); documentazione su /docs", impostazioni.agente_url,
             impostazioni.agente_timeout)
    client = ClientAgente(impostazioni.agente_url, impostazioni.agente_timeout)
    # log_config=None: uvicorn usa la configurazione dei log appena fatta
    uvicorn.run(crea_app(fabbrica_sessioni(motore), client), host=impostazioni.host,
                port=impostazioni.porta, log_config=None)


if __name__ == "__main__":
    main()
