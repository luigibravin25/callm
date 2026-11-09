# librerie standard: date e ore, tipi con valori fissi, fusi orari IANA
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# tool: trasforma una funzione in uno strumento che il modello puo' chiamare
from langchain_core.tools import tool

# fuso da usare quando l'utente non indica un luogo (variabile FUSO_PREDEFINITO o Europe/Rome)
from app.config import fuso_predefinito

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


# strumento orologio: il decoratore @tool lo rende chiamabile dal modello con il nome "tooltime"
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
    # fuso vuoto: il modello non ha indicato un luogo, si usa quello predefinito
    fuso = fuso.strip() or fuso_predefinito()
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


# strumenti dell'agente: lo step 1 ha solo l'orologio (ambito: ora, data e fusi orari)
STRUMENTI = [ora_corrente]
