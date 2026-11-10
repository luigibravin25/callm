"""Logica dell'orologio di tooltime (server MCP mcp_assistente): data e ora a parole."""
# librerie standard: variabili d'ambiente, date e ore, fusi orari IANA
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FUSO_DI_RISERVA = "Europe/Rome"  # usato se FUSO_PREDEFINITO non e' impostata


# fuso da usare quando tooltime non riceve un fuso (l'host di solito lo completa da solo)
def _fuso_predefinito() -> str:
    # una variabile vuota o fatta di spazi diventa "" e "or" passa alla riserva
    return os.environ.get("FUSO_PREDEFINITO", "").strip() or FUSO_DI_RISERVA


# nomi dei mesi scritti a mano: cosi' non dipendono dalla lingua impostata nel sistema
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")


# scrive la data in parole per la risposta dell'orologio
def _data(momento: datetime) -> str:
    # month va da 1 a 12, la tupla parte da 0: per questo "- 1"
    return f"{momento.day} {MESI[momento.month - 1]} del {momento.year}"


# scrive l'ora in parole, come la direbbe una persona ("sono le ore 17 e 12 minuti")
def _ora(momento: datetime) -> str:
    ore, minuti = momento.hour, momento.minute
    if ore == 12 and minuti == 0:
        return "è mezzogiorno"  # solo alle 12:00: alle 12:05 resta "sono le ore 12 e 5 minuti"
    # le ore 0 e 1 sono singolari ("e' mezzanotte", "e' l'una"); le altre "sono le ore N"
    verbo, base = {0: ("è", "mezzanotte"), 1: ("è", "l'una")}.get(
        ore, ("sono", f"le ore {ore}"))
    # ora esatta: "in punto", tranne a mezzanotte dove suonerebbe strano
    if minuti == 0:
        return f"{verbo} {base}" if ore == 0 else f"{verbo} {base} in punto"
    unita = "minuto" if minuti == 1 else "minuti"
    return f"{verbo} {base} e {minuti} {unita}"


# ricava dal fuso un nome di luogo leggibile: "America/New_York" diventa "New York"
def _luogo(zona: ZoneInfo) -> str:
    # prende l'ultima parte dopo la barra e sostituisce i trattini bassi con spazi
    return zona.key.rsplit("/", 1)[-1].replace("_", " ")


# legge l'orologio del computer in UTC (funzione separata per poterla sostituire nei test)
def _adesso() -> datetime:
    return datetime.now(timezone.utc)


# data e/o ora attuali in un fuso: e' il corpo del tool MCP tooltime
def ora_corrente(fuso: str = "", parte: str = "entrambe") -> str:
    """Testo come "Tokyo: 1 marzo del 2026, sono le ore 20 in punto" (parte: ora, data, entrambe)."""
    # fuso vuoto: il modello non ha indicato un luogo, si usa quello predefinito
    fuso = fuso.strip() or _fuso_predefinito()
    try:
        zona = ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # nome sbagliato: invece di sollevare un errore, spiega al modello come correggersi
        return (f"Fuso orario non valido: {fuso!r}. Usa un nome IANA, "
                "ad esempio 'Europe/Rome' o 'Asia/Tokyo'.")
    # converte l'istante UTC nell'ora locale del fuso richiesto
    locale = _adesso().astimezone(zona)
    # restituisce solo la parte chiesta: ora, data o entrambe
    if parte == "ora":
        return f"{_luogo(zona)}: {_ora(locale)}"
    if parte == "data":
        return f"{_luogo(zona)}: {_data(locale)}"
    return f"{_luogo(zona)}: {_data(locale)}, {_ora(locale)}"
