"""Configurazione del back-end, solo da variabili d'ambiente (come l'agente).

DATABASE_URL e' obbligatoria; AGENTE_URL e AGENTE_TIMEOUT sono le stesse variabili della CLI;
BACKEND_HOST e BACKEND_PORTA dicono dove ascolta il servizio; STREAMING (step 10) rende disponibili
le risposte in streaming. La password del database non
compare mai nei messaggi: si usa maschera_url.
"""
# librerie standard: ambiente, struttura dei valori letti
import os
from dataclasses import dataclass

# lettura sicura dell'URL del database (utente, password, host, nome)
from sqlalchemy.engine import make_url

AGENTE_URL_PREDEFINITO = "http://127.0.0.1:8000"
AGENTE_TIMEOUT_PREDEFINITO = 300  # secondi: un turno con revisioni puo' durare minuti
HOST_PREDEFINITO = "127.0.0.1"
PORTA_PREDEFINITA = 8001
SCHEMA_DB = "postgresql+psycopg"  # SQLAlchemy con il driver psycopg 3


# valori letti dall'ambiente
@dataclass(frozen=True)
class Impostazioni:
    database_url: str
    agente_url: str
    agente_timeout: int
    host: str
    porta: int
    streaming: bool = True  # step 10: risposte in streaming disponibili per il front-end


# URL del database con la password sostituita da *** (per log e messaggi d'errore)
def maschera_url(url: str) -> str:
    try:
        letto = make_url(url)
    except Exception:
        return "<URL non leggibile>"
    if letto.password is None:
        return url
    # hide_password scrive *** al posto della password (senza codificarla come %2A)
    return letto.render_as_string(hide_password=True)


# intero dentro un intervallo, con errore che nomina la variabile e il valore trovato
def _intero(nome: str, predefinito: int, minimo: int, massimo: int) -> int:
    grezzo = os.environ.get(nome, str(predefinito)).strip()
    if not grezzo.isdigit() or not minimo <= int(grezzo) <= massimo:
        raise ValueError(f"{nome} deve essere un intero tra {minimo} e {massimo}, "
                         f"trovato: {grezzo!r}")
    return int(grezzo)


# valori ammessi per STREAMING (senza maiuscole)
VERI = {"true", "1", "sì", "si"}
FALSI = {"false", "0", "no"}


# booleano da variabile d'ambiente: assente → predefinito; valore non ammesso → errore che lo nomina
def _booleano(nome: str, predefinito: bool) -> bool:
    grezzo = os.environ.get(nome, "").strip().lower()
    if not grezzo:
        return predefinito
    if grezzo in VERI:
        return True
    if grezzo in FALSI:
        return False
    raise ValueError(f"{nome} deve essere true o false, trovato: {grezzo!r}")


# legge e controlla tutte le variabili; ValueError con un messaggio chiaro se qualcosa non va
def leggi_impostazioni() -> Impostazioni:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL mancante: es. "
                         f"{SCHEMA_DB}://assistente:<password>@127.0.0.1:5433/assistente")
    # schema controllato senza mostrare l'URL (contiene la password)
    try:
        schema = make_url(url).drivername
    except Exception:
        schema = ""
    if schema != SCHEMA_DB:
        raise ValueError(f"DATABASE_URL deve iniziare con {SCHEMA_DB}://, trovato lo schema "
                         f"{schema or 'non leggibile'!r}")
    agente_url = os.environ.get("AGENTE_URL", "").strip() or AGENTE_URL_PREDEFINITO
    return Impostazioni(
        database_url=url,
        agente_url=agente_url.rstrip("/"),
        agente_timeout=_intero("AGENTE_TIMEOUT", AGENTE_TIMEOUT_PREDEFINITO, 1, 86400),
        host=os.environ.get("BACKEND_HOST", "").strip() or HOST_PREDEFINITO,
        porta=_intero("BACKEND_PORTA", PORTA_PREDEFINITA, 1, 65535),
        streaming=_booleano("STREAMING", True),
    )
