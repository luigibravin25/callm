from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


def _adesso() -> datetime:
    """Istante corrente in UTC (funzione separata per poterla sostituire nei test)."""
    return datetime.now(timezone.utc)


@tool
def ora_corrente(fuso: str) -> str:
    """Restituisce data e ora attuali in un fuso orario.

    Usala ogni volta che serve sapere che ora e' o che giorno e' in una citta' o
    in un paese. L'argomento `fuso` e' il nome IANA del fuso orario, ad esempio
    "Europe/Rome", "Asia/Tokyo" o "America/New_York" (non il nome della citta' da sola).
    """
    try:
        zona = ZoneInfo(fuso.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return (f"Fuso orario non valido: {fuso!r}. Usa un nome IANA, "
                "ad esempio 'Europe/Rome' o 'Asia/Tokyo'.")
    locale = _adesso().astimezone(zona)
    return f"{locale:%Y-%m-%d %H:%M:%S %Z} ({zona.key})"


STRUMENTI = [ora_corrente]
