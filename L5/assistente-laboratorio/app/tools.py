import math
import os
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.conversioni import ErroreConversione, converti, formatta_numero


FUSO_DI_RISERVA = "Europe/Rome"  # usato se FUSO_PREDEFINITO non e' impostata

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")


def _data(momento: datetime) -> str:
    """Data con il mese in italiano (non dipende dalla lingua del sistema): "27 ottobre del 2026"."""
    return f"{momento.day} {MESI[momento.month - 1]} del {momento.year}"


def _ora(momento: datetime) -> str:
    """Ora senza secondi, con il verbo: "sono le ore 17 e 12 minuti", "e' l'una e 14 minuti",
    "e' mezzanotte", "e' mezzogiorno"."""
    ore, minuti = momento.hour, momento.minute
    if ore == 12 and minuti == 0:
        return "è mezzogiorno"  # solo alle 12:00: alle 12:05 resta "sono le ore 12 e 5 minuti"
    verbo, base = {0: ("è", "mezzanotte"), 1: ("è", "l'una")}.get(
        ore, ("sono", f"le ore {ore}"))
    if minuti == 0:
        return f"{verbo} {base}" if ore == 0 else f"{verbo} {base} in punto"
    unita = "minuto" if minuti == 1 else "minuti"
    return f"{verbo} {base} e {minuti} {unita}"


def _luogo(zona: ZoneInfo) -> str:
    """Nome del luogo dal nome IANA: "America/New_York" diventa "New York"."""
    return zona.key.rsplit("/", 1)[-1].replace("_", " ")


def _adesso() -> datetime:
    """Istante corrente in UTC (funzione separata per poterla sostituire nei test)."""
    return datetime.now(timezone.utc)


def fuso_predefinito() -> str:
    """Fuso usato quando il modello non indica `fuso`: variabile FUSO_PREDEFINITO o Europe/Rome."""
    return os.environ.get("FUSO_PREDEFINITO", "").strip() or FUSO_DI_RISERVA


@tool("tooltime")
def ora_corrente(fuso: str = "", parte: Literal["ora", "data", "entrambe"] = "entrambe") -> str:
    """Restituisce data e/o ora attuali in un fuso orario.

    Usala ogni volta che serve sapere che ora e' o che giorno e' in una citta' o
    in un paese. L'argomento `fuso` e' il nome IANA del fuso orario, ad esempio
    "Europe/Rome", "Asia/Tokyo" o "America/New_York" (non il nome della citta' da sola).
    Se l'utente non indica una citta' o un paese, ometti `fuso`: lo strumento usa il fuso
    predefinito. Non usare "UTC" o "GMT" se l'utente non li chiede.
    Il risultato inizia con il nome del luogo: nella risposta usa quel nome (per esempio
    "a New York"), mai il nome IANA con la barra (come "America/New_York").
    Riporta l'ora esattamente come scritta nel risultato, a parole ("sono le ore 10 e 32 minuti"):
    non convertirla in cifre con i due punti (come "10:32") e non aggiungere i secondi.
    L'argomento `parte` dice cosa restituire: "ora" se l'utente chiede solo l'ora,
    "data" se chiede solo il giorno o la data, "entrambe" negli altri casi.
    """
    fuso = fuso.strip() or fuso_predefinito()
    try:
        zona = ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return (f"Fuso orario non valido: {fuso!r}. Usa un nome IANA, "
                "ad esempio 'Europe/Rome' o 'Asia/Tokyo'.")
    locale = _adesso().astimezone(zona)
    if parte == "ora":
        return f"{_luogo(zona)}: {_ora(locale)}"
    if parte == "data":
        return f"{_luogo(zona)}: {_data(locale)}"
    return f"{_luogo(zona)}: {_data(locale)}, {_ora(locale)}"


class ArgomentiConversione(BaseModel):
    valore: float = Field(allow_inf_nan=False,
                          description="Numero da convertire, ad esempio 10 o 36.6.")
    da: str = Field(min_length=1, description=(
        'Unità di partenza: simbolo o nome italiano, ad esempio "km", "miglia", '
        '"gradi Celsius".'))
    a: str = Field(min_length=1, description=(
        'Unità di arrivo: simbolo o nome italiano, ad esempio "m", "chilometri", '
        '"gradi Fahrenheit".'))


@tool("toolconvert", args_schema=ArgomentiConversione)
def converti_unita(valore: float, da: str, a: str) -> str:
    """Converte un valore tra due unità di misura della stessa grandezza.

    Usalo per ogni conversione di unità di misura (lunghezze, masse, temperature,
    volumi, velocità, pressioni, energie, dati digitali e altre).
    `da` e `a` accettano il simbolo o il nome italiano, ad esempio "km", "miglia",
    "gradi Celsius". Riporta il risultato esattamente come scritto.
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    try:
        return converti(valore, da, a)
    except ErroreConversione as errore:
        return str(errore)


# --- calcolatrice sicura: la logica sta nel servizio HTTP (servizio/), qui solo il wrapper ---
# nome, descrizione e schema sono scritti a mano: se l'endpoint cambia, va aggiornato qui

CALC_URL_PREDEFINITO = "http://127.0.0.1:8001"
TIMEOUT_CALC = 5.0  # secondi: oltre, l'agente non resta bloccato

MSG_CALC_422 = ("Richiesta non accettata dal servizio calcolatrice (HTTP 422): "
                "il contratto dell'endpoint potrebbe essere cambiato.")
MSG_CALC_TIMEOUT = "Il servizio calcolatrice non ha risposto entro 5 secondi."
MSG_CALC_NON_VALIDA = "Risposta non valida dal servizio calcolatrice."


def calc_base_url() -> str:
    """Indirizzo del servizio: variabile CALC_BASE_URL (letta a ogni chiamata) o il predefinito."""
    return os.environ.get("CALC_BASE_URL", "").strip().rstrip("/") or CALC_URL_PREDEFINITO


def _client() -> httpx.Client:
    """Client HTTP del wrapper (funzione separata per poterla sostituire nei test)."""
    return httpx.Client(timeout=TIMEOUT_CALC)


def _numero(valore) -> bool:
    return (isinstance(valore, (int, float)) and not isinstance(valore, bool)
            and math.isfinite(valore))


class ArgomentiCalcolo(BaseModel):
    espressione: str = Field(min_length=1, description=(
        'Espressione aritmetica con numeri in cifre e punto decimale, '
        'ad esempio "(3+4)^2/7" o "2.5*4".'))


@tool("toolcalc", args_schema=ArgomentiCalcolo)
def calcola_espressione(espressione: str) -> str:
    """Calcola un'espressione aritmetica.

    Usalo per ogni calcolo aritmetico. Sono ammesse solo + - * /, le parentesi e le
    potenze con ^ (ad esempio "2^10"). Scrivi i numeri in cifre con il punto decimale.
    Riporta il risultato esattamente come scritto.
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    url = calc_base_url()
    try:
        with _client() as client:
            risposta = client.post(f"{url}/calcola", json={"espressione": espressione})
    except httpx.TimeoutException:
        return MSG_CALC_TIMEOUT
    except httpx.TransportError:
        return f"Servizio calcolatrice non raggiungibile a {url}: avvialo e riprova."
    if risposta.status_code == 422:
        return MSG_CALC_422
    if risposta.status_code not in (200, 400):
        return f"Il servizio calcolatrice ha risposto con l'errore HTTP {risposta.status_code}."
    try:
        corpo = risposta.json()
    except ValueError:
        return MSG_CALC_NON_VALIDA
    if not isinstance(corpo, dict):
        return MSG_CALC_NON_VALIDA
    if risposta.status_code == 400:
        errore = corpo.get("errore")
        return f"Espressione rifiutata: {errore}" if isinstance(errore, str) else MSG_CALC_NON_VALIDA
    risultato = corpo.get("risultato")
    if not _numero(risultato):
        return MSG_CALC_NON_VALIDA
    return f"{espressione} = {formatta_numero(risultato)}"


STRUMENTI = [ora_corrente, converti_unita, calcola_espressione]
