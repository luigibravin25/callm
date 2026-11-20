"""Avvio comune degli script: log nel terminale ed errori previsti → messaggio e codice di uscita 1."""
# librerie standard: log, variabili d'ambiente, uscita del processo, tipi
import logging
import os
import sys
from collections.abc import Callable

# errori del client di Qdrant (server spento o risposta inattesa)
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.errori import ErroreRicerca

log = logging.getLogger("ricerca")


def configura_log() -> None:
    # i caratteri che la console non conosce (es. cp1252 su Windows) diventano \uXXXX invece di un errore;
    # i flussi senza reconfigure (quelli finti di pytest) restano come sono
    for flusso in (sys.stdout, sys.stderr):
        riconfigura = getattr(flusso, "reconfigure", None)
        if riconfigura is not None:
            riconfigura(errors="backslashreplace")
    # log su stderr come [ricerca] messaggio
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stderr)
    # le richieste HTTP (httpx di Qdrant, httpx2 del client openai verso LM Studio) restano fuori dal log
    for nome in ("httpx", "httpx2"):
        logging.getLogger(nome).setLevel(logging.WARNING)


def esegui(principale: Callable[[], None]) -> None:
    """Esegue lo script; gli errori previsti diventano un messaggio comprensibile e l'uscita con 1."""
    try:
        principale()
    except ErroreRicerca as errore:
        log.error("%s", errore)
        sys.exit(1)
    except (ResponseHandlingException, UnexpectedResponse) as errore:
        # indirizzo dalla variabile: la configurazione può non essere ancora stata letta
        indirizzo = os.environ.get("QDRANT_URL", "").strip() or "http://127.0.0.1:6333"
        log.error("Qdrant non raggiungibile o risposta inattesa (QDRANT_URL=%s): %s. Avviare: "
                  "docker compose up -d qdrant", indirizzo, errore)
        sys.exit(1)
