from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


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


@tool("tooltime")
def ora_corrente(fuso: str, parte: Literal["ora", "data", "entrambe"] = "entrambe") -> str:
    """Restituisce data e/o ora attuali in un fuso orario.

    Usala ogni volta che serve sapere che ora e' o che giorno e' in una citta' o
    in un paese. L'argomento `fuso` e' il nome IANA del fuso orario, ad esempio
    "Europe/Rome", "Asia/Tokyo" o "America/New_York" (non il nome della citta' da sola).
    Il risultato inizia con il nome del luogo: nella risposta usa quel nome (per esempio
    "a New York"), mai il nome IANA con la barra (come "America/New_York").
    Riporta l'ora esattamente come scritta nel risultato, a parole ("sono le ore 10 e 32 minuti"):
    non convertirla in cifre con i due punti (come "10:32") e non aggiungere i secondi.
    L'argomento `parte` dice cosa restituire: "ora" se l'utente chiede solo l'ora,
    "data" se chiede solo il giorno o la data, "entrambe" negli altri casi.
    """
    try:
        zona = ZoneInfo(fuso.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return (f"Fuso orario non valido: {fuso!r}. Usa un nome IANA, "
                "ad esempio 'Europe/Rome' o 'Asia/Tokyo'.")
    locale = _adesso().astimezone(zona)
    if parte == "ora":
        return f"{_luogo(zona)}: {_ora(locale)}"
    if parte == "data":
        return f"{_luogo(zona)}: {_data(locale)}"
    return f"{_luogo(zona)}: {_data(locale)}, {_ora(locale)}"


STRUMENTI = [ora_corrente]
