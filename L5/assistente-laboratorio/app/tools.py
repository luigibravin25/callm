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
    if not isinstance(valore, (int, float)) or isinstance(valore, bool):
        return False
    try:
        return math.isfinite(valore)
    except OverflowError:  # intero JSON troppo grande per un float (es. 10**400)
        return False


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
    Rispondi in testo semplice, senza LaTeX e senza il simbolo $ (scrivi "5 alla seconda fa 25").
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    risposta = _chiedi_al_servizio("/calcola", {"espressione": espressione})
    if isinstance(risposta, str):
        return risposta
    stato, corpo = risposta
    if stato == 400:
        return f"Espressione rifiutata: {corpo['errore']}"
    risultato = corpo.get("risultato")
    if not _numero(risultato):
        return MSG_CALC_NON_VALIDA
    return f"{espressione} = {formatta_numero(risultato)}"


def _chiedi_al_servizio(percorso: str, corpo: dict) -> tuple[int, dict] | str:
    """POST al servizio (CALC_BASE_URL + percorso), comune a toolcalc e tooldate.

    Restituisce (200 | 400, corpo JSON) oppure il testo del guasto gia' tradotto
    (timeout, servizio non raggiungibile, URL non valida, 422, altri codici, risposta
    non JSON, 400 senza 'errore' testuale): il wrapper non solleva mai."""
    url = calc_base_url()
    try:
        with _client() as client:
            risposta = client.post(f"{url}{percorso}", json=corpo)
    except httpx.TimeoutException:
        return MSG_CALC_TIMEOUT
    except httpx.TransportError:
        return f"Servizio calcolatrice non raggiungibile a {url}: avvialo e riprova."
    except httpx.InvalidURL:
        return (f"CALC_BASE_URL non valida: {url!r}. "
                "Usa un indirizzo come http://127.0.0.1:8001.")
    except httpx.RequestError:  # es. DecodingError: corpo compresso illeggibile
        return MSG_CALC_NON_VALIDA
    if risposta.status_code == 422:
        return MSG_CALC_422
    if risposta.status_code not in (200, 400):
        return f"Il servizio calcolatrice ha risposto con l'errore HTTP {risposta.status_code}."
    try:
        dati = risposta.json()
    except ValueError:
        return MSG_CALC_NON_VALIDA
    if not isinstance(dati, dict):
        return MSG_CALC_NON_VALIDA
    if risposta.status_code == 400 and not isinstance(dati.get("errore"), str):
        return MSG_CALC_NON_VALIDA
    return risposta.status_code, dati


# --- giorni e scadenze: stesso servizio HTTP (endpoint /giorni), wrapper scritto a mano ---

class ArgomentiDate(BaseModel):
    operazione: Literal["giorni", "scadenza", "giorno"] = Field(description=(
        '"giorni" = quanti giorni (lavorativi e di calendario) fino a `data`; '
        '"scadenza" = che data e\' dopo `giorni` giorni da `da`; '
        '"giorno" = che giorno e\' `data` e se e\' lavorativo o festivo.'))
    data: str = Field(default="", description=(
        'Data come la scrive l\'utente, senza calcolarla: "25/12/2026", "25 dicembre", '
        '"natale", "pasqua 2027", "oggi". Per "giorni" e "giorno".'))
    da: str = Field(default="", description=(
        'Data di partenza come la scrive l\'utente; vuota = oggi. Per "giorni" e "scadenza".'))
    giorni: int | None = Field(default=None, description=(
        'Numero di giorni della scadenza, ad esempio 30. Solo per "scadenza".'))
    tipo: Literal["lavorativi", "calendario"] = Field(default="lavorativi", description=(
        'Per "scadenza": "lavorativi" (predefinito) oppure "calendario".'))


def _testo_giorni(r: dict) -> str:
    festivita = ", ".join(f"{f['data']} {f['nome']}" for f in r["festivita"]) or "nessuna"
    return (f"Dal {r['da']} ({r['da_giorno']}) al {r['a']} ({r['a_giorno']}), "
            f"{r['conteggio']}: giorni lavorativi {r['giorni_lavorativi']}, "
            f"giorni di calendario {r['giorni_calendario']}. "
            f"Festività in giorni feriali: {festivita}. {r['avviso']}")


def _testo_scadenza(r: dict) -> str:
    tipo = "lavorativi" if r["tipo"] == "lavorativi" else "di calendario"
    testo = (f"Scadenza: {r['scadenza']} ({r['scadenza_giorno']}), {r['giorni']} giorni "
             f"{tipo} da {r['da']} ({r['da_giorno']}).")
    if r["slittata_da"]:
        testo += (f" La data calcolata {r['slittata_da']} cade di {r['motivo_slittamento']}: "
                  "slitta al primo giorno lavorativo.")
    return f"{testo} {r['avviso']}"


def _testo_giorno(r: dict) -> str:
    if not isinstance(r["festivita"], list):
        raise TypeError("festivita non e' un elenco")
    if r["festivita"]:
        stato = f"festivo ({', '.join(r['festivita'])})."
    elif r["fine_settimana"]:
        stato = "fine settimana, non lavorativo."
    else:
        stato = "giorno lavorativo."
    return f"{r['data']} ({r['giorno_settimana']}): {stato} {r['avviso']}"


_TESTI_DATE = {"giorni": _testo_giorni, "scadenza": _testo_scadenza, "giorno": _testo_giorno}


@tool("tooldate", args_schema=ArgomentiDate)
def date_e_scadenze(operazione: str, data: str = "", da: str = "", giorni: int | None = None,
                    tipo: str = "lavorativi") -> str:
    """Giorni lavorativi, scadenze e festività italiane.

    Usalo per sapere quanti giorni (lavorativi o di calendario) mancano a una data o ci sono
    tra due date, per calcolare una scadenza dopo un numero di giorni, e per sapere che giorno
    è una data e se è lavorativo o festivo (Natale, Pasqua, Liberazione e le altre feste).
    Passa le date come le scrive l'utente (anche "Natale" o "25 dicembre"): non calcolarle tu.
    Riporta date e numeri esattamente come scritti, in testo semplice, senza LaTeX e senza il
    simbolo $. Riporta sempre l'avviso finale (il calcolo è indicativo).
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    corpo = {"operazione": operazione, "tipo": tipo}
    for chiave, valore in (("data", data), ("da", da)):
        if valore and valore.strip():
            corpo[chiave] = valore
    if giorni is not None:
        corpo["giorni"] = giorni
    risposta = _chiedi_al_servizio("/giorni", corpo)
    if isinstance(risposta, str):
        return risposta
    stato, dati = risposta
    if stato == 400:
        return f"Data rifiutata: {dati['errore']}"
    try:
        return _TESTI_DATE[operazione](dati)
    except (KeyError, TypeError, AttributeError):
        return MSG_CALC_NON_VALIDA


STRUMENTI = [ora_corrente, converti_unita, calcola_espressione, date_e_scadenze]
