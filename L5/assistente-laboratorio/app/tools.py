# librerie standard: matematica, ambiente, date e ore, tipi con valori fissi, fusi orari
import math
import os
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# httpx: richieste HTTP al servizio FastAPI; tool: trasforma una funzione in strumento per il
# modello; pydantic: descrive e controlla gli argomenti degli strumenti
import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

# logica del convertitore di unita' (modulo senza LangChain)
from app.conversioni import ErroreConversione, converti, formatta_numero


# --- orologio (tooltime): strumento locale, nessuna richiesta HTTP ---

FUSO_DI_RISERVA = "Europe/Rome"  # usato se FUSO_PREDEFINITO non e' impostata

# nomi dei mesi scritti a mano: cosi' non dipendono dalla lingua impostata nel sistema
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")


# scrive la data in parole per la risposta dell'orologio
def _data(momento: datetime) -> str:
    """Data con il mese in italiano (non dipende dalla lingua del sistema): "27 ottobre del 2026"."""
    # month va da 1 a 12, la tupla parte da 0: per questo "- 1"
    return f"{momento.day} {MESI[momento.month - 1]} del {momento.year}"


# scrive l'ora in parole, come la direbbe una persona
def _ora(momento: datetime) -> str:
    """Ora senza secondi, con il verbo: "sono le ore 17 e 12 minuti", "e' l'una e 14 minuti",
    "e' mezzanotte", "e' mezzogiorno"."""
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


# ricava dal fuso un nome di luogo leggibile da mettere nella risposta
def _luogo(zona: ZoneInfo) -> str:
    """Nome del luogo dal nome IANA: "America/New_York" diventa "New York"."""
    # prende l'ultima parte dopo la barra e sostituisce i trattini bassi con spazi
    return zona.key.rsplit("/", 1)[-1].replace("_", " ")


# legge l'orologio del computer
def _adesso() -> datetime:
    """Istante corrente in UTC (funzione separata per poterla sostituire nei test)."""
    return datetime.now(timezone.utc)


# fuso da usare quando l'utente non indica un luogo (usato anche da app/config.py)
def fuso_predefinito() -> str:
    """Fuso usato quando il modello non indica `fuso`: variabile FUSO_PREDEFINITO o Europe/Rome."""
    # una variabile vuota o fatta di spazi diventa "" e "or" passa alla riserva
    return os.environ.get("FUSO_PREDEFINITO", "").strip() or FUSO_DI_RISERVA


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


# --- convertitore di unita' (toolconvert): strumento locale, logica in app/conversioni.py ---

# schema degli argomenti di toolconvert: le descrizioni dei campi arrivano al modello
class ArgomentiConversione(BaseModel):
    # allow_inf_nan=False: pydantic rifiuta gia' infinito e NaN; min_length=1: niente testo vuoto
    valore: float = Field(allow_inf_nan=False,
                          description="Numero da convertire, ad esempio 10 o 36.6.")
    da: str = Field(min_length=1, description=(
        'Unità di partenza: simbolo o nome italiano, ad esempio "km", "miglia", '
        '"gradi Celsius".'))
    a: str = Field(min_length=1, description=(
        'Unità di arrivo: simbolo o nome italiano, ad esempio "m", "chilometri", '
        '"gradi Fahrenheit".'))


# strumento convertitore: args_schema usa lo schema qui sopra al posto di quello automatico
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
        # l'errore diventa testo: il modello lo legge e lo spiega all'utente
        return str(errore)


# --- calcolatrice sicura: la logica sta nel servizio HTTP (servizio/), qui solo il wrapper ---
# nome, descrizione e schema sono scritti a mano: se l'endpoint cambia, va aggiornato qui

CALC_URL_PREDEFINITO = "http://127.0.0.1:8001"  # servizio avviato in locale sulla porta 8001
TIMEOUT_CALC = 5.0  # secondi: oltre, l'agente non resta bloccato

# messaggi fissi restituiti al modello quando il servizio ha un problema
MSG_CALC_422 = ("Richiesta non accettata dal servizio HTTP (HTTP 422): "
                "il contratto dell'endpoint potrebbe essere cambiato.")
MSG_CALC_TIMEOUT = "Il servizio HTTP non ha risposto entro 5 secondi."
MSG_CALC_NON_VALIDA = "Risposta non valida dal servizio HTTP."


# indirizzo del servizio FastAPI (in Docker Compose CALC_BASE_URL punta al servizio "servizio")
def calc_base_url() -> str:
    """Indirizzo del servizio: variabile CALC_BASE_URL (letta a ogni chiamata) o il predefinito."""
    # rstrip("/") toglie la barra finale: evita "//calcola" quando si aggiunge il percorso
    return os.environ.get("CALC_BASE_URL", "").strip().rstrip("/") or CALC_URL_PREDEFINITO


# crea il client HTTP con il limite di attesa
def _client() -> httpx.Client:
    """Client HTTP del wrapper (funzione separata per poterla sostituire nei test)."""
    return httpx.Client(timeout=TIMEOUT_CALC)


# controlla che il risultato del servizio sia davvero un numero finito
def _numero(valore) -> bool:
    # in Python True e False sono anche int: vanno esclusi a parte
    if not isinstance(valore, (int, float)) or isinstance(valore, bool):
        return False
    try:
        return math.isfinite(valore)
    except OverflowError:  # intero JSON troppo grande per un float (es. 10**400)
        return False


# schema dell'unico argomento di toolcalc: l'espressione da calcolare
class ArgomentiCalcolo(BaseModel):
    espressione: str = Field(min_length=1, description=(
        'Espressione aritmetica con numeri in cifre e punto decimale, '
        'ad esempio "(3+4)^2/7" o "2.5*4".'))


# strumento calcolatrice: manda l'espressione al servizio e traduce la risposta in una frase
@tool("toolcalc", args_schema=ArgomentiCalcolo)
def calcola_espressione(espressione: str) -> str:
    """Calcola un'espressione aritmetica.

    Usalo per ogni calcolo aritmetico. Sono ammesse solo + - * /, le parentesi e le
    potenze con ^ (ad esempio "2^10"). Scrivi i numeri in cifre con il punto decimale.
    Riporta il risultato esattamente come scritto.
    OBBLIGATORIO: rispondi in testo semplice, senza LaTeX e senza il simbolo $, né intorno ai
    numeri né intorno all'espressione (scrivi "(3+4)^2 / 7 fa 7", "5 alla seconda fa 25").
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    risposta = _chiedi_al_servizio("/calcola", {"espressione": espressione})
    # una stringa e' gia' il messaggio di un guasto (timeout, rete...): va passata cosi' com'e'
    if isinstance(risposta, str):
        return risposta
    stato, corpo = risposta
    # 400 = il servizio ha rifiutato l'espressione e spiega perche' nel campo "errore"
    if stato == 400:
        return f"Espressione rifiutata: {corpo['errore']}"
    risultato = corpo.get("risultato")
    if not _numero(risultato):
        return MSG_CALC_NON_VALIDA
    # stesso formato del convertitore: virgola decimale e 6 cifre significative
    return f"{espressione} = {formatta_numero(risultato)}"


# funzione comune a toolcalc e tooldate: fa la richiesta POST e gestisce ogni tipo di guasto
def _chiedi_al_servizio(percorso: str, corpo: dict) -> tuple[int, dict] | str:
    """POST al servizio (CALC_BASE_URL + percorso), comune a toolcalc e tooldate.

    Restituisce (200 | 400, corpo JSON) oppure il testo del guasto gia' tradotto
    (timeout, servizio non raggiungibile, URL non valida, 422, altri codici, risposta
    non JSON, 400 senza 'errore' testuale): il wrapper non solleva mai."""
    url = calc_base_url()
    try:
        # "with" chiude il client (e la connessione) anche in caso di errore
        with _client() as client:
            # json=corpo trasforma il dizionario in JSON e imposta l'intestazione giusta
            risposta = client.post(f"{url}{percorso}", json=corpo)
    # l'ordine degli except conta: TimeoutException e' un caso particolare di TransportError
    except httpx.TimeoutException:
        return MSG_CALC_TIMEOUT
    except httpx.TransportError:
        # di solito il servizio non e' avviato (connessione rifiutata)
        return f"Servizio HTTP non raggiungibile a {url}: avvialo e riprova."
    except httpx.InvalidURL:
        return (f"CALC_BASE_URL non valida: {url!r}. "
                "Usa un indirizzo come http://127.0.0.1:8001.")
    except httpx.RequestError:  # es. DecodingError: corpo compresso illeggibile
        return MSG_CALC_NON_VALIDA
    # 422 = FastAPI non ha accettato i campi inviati: wrapper e servizio non sono allineati
    if risposta.status_code == 422:
        return MSG_CALC_422
    # solo 200 (riuscito) e 400 (input rifiutato) sono risposte previste
    if risposta.status_code not in (200, 400):
        return f"Il servizio HTTP ha risposto con l'errore HTTP {risposta.status_code}."
    # il corpo deve essere un oggetto JSON (un dizionario)
    try:
        dati = risposta.json()
    except ValueError:
        return MSG_CALC_NON_VALIDA
    if not isinstance(dati, dict):
        return MSG_CALC_NON_VALIDA
    # un 400 deve contenere il motivo del rifiuto come testo
    if risposta.status_code == 400 and not isinstance(dati.get("errore"), str):
        return MSG_CALC_NON_VALIDA
    # risposta valida: codice di stato e dati, controllati poi dal wrapper
    return risposta.status_code, dati


# --- giorni e scadenze: stesso servizio HTTP (endpoint /giorni), wrapper scritto a mano ---

# schema degli argomenti di tooldate: una sola funzione per tre operazioni diverse
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
    # SkipJsonSchema: lo schema resta {"type": "integer"} (niente anyOf con null), altrimenti il
    # template jinja di gemma in LM Studio fallisce e la richiesta riceve HTTP 400
    giorni: int | SkipJsonSchema[None] = Field(default=None, description=(
        'Numero di giorni della scadenza, ad esempio 30. Solo per "scadenza".'))
    tipo: Literal["lavorativi", "calendario"] = Field(default="lavorativi", description=(
        'Per "scadenza": "lavorativi" (predefinito) oppure "calendario".'))


# frase per l'operazione "giorni": quanti giorni lavorativi e di calendario tra due date
def _testo_giorni(r: dict) -> str:
    # elenca le festivita' che cadono in giorni feriali; se non ce ne sono scrive "nessuna"
    festivita = ", ".join(f"{f['data']} {f['nome']}" for f in r["festivita"]) or "nessuna"
    return (f"Dal {r['da']} ({r['da_giorno']}) al {r['a']} ({r['a_giorno']}), "
            f"{r['conteggio']}: giorni lavorativi {r['giorni_lavorativi']}, "
            f"giorni di calendario {r['giorni_calendario']}. "
            f"Festività in giorni feriali: {festivita}. {r['avviso']}")


# frase per l'operazione "scadenza": data finale dopo N giorni
def _testo_scadenza(r: dict) -> str:
    tipo = "lavorativi" if r["tipo"] == "lavorativi" else "di calendario"
    testo = (f"Scadenza: {r['scadenza']} ({r['scadenza_giorno']}), {r['giorni']} giorni "
             f"{tipo} da {r['da']} ({r['da_giorno']}).")
    # se la data cadeva in un festivo o nel fine settimana, il servizio l'ha spostata in avanti
    if r["slittata_da"]:
        testo += (f" La data calcolata {r['slittata_da']} cade di {r['motivo_slittamento']}: "
                  "slitta al primo giorno lavorativo.")
    return f"{testo} {r['avviso']}"


# frase per l'operazione "giorno": che giorno e' una data e se si lavora
def _testo_giorno(r: dict) -> str:
    # controllo sul formato: un elenco non valido diventa "risposta non valida" nel wrapper
    if not isinstance(r["festivita"], list):
        raise TypeError("festivita non e' un elenco")
    if r["festivita"]:
        stato = f"festivo ({', '.join(r['festivita'])})."
    elif r["fine_settimana"]:
        stato = "fine settimana, non lavorativo."
    else:
        stato = "giorno lavorativo."
    return f"{r['data']} ({r['giorno_settimana']}): {stato} {r['avviso']}"


# per ogni operazione, la funzione che scrive la frase del risultato
_TESTI_DATE = {"giorni": _testo_giorni, "scadenza": _testo_scadenza, "giorno": _testo_giorno}


# strumento date: chiede il calcolo al servizio (/giorni) e traduce la risposta in una frase
@tool("tooldate", args_schema=ArgomentiDate)
def date_e_scadenze(operazione: str, data: str = "", da: str = "", giorni: int | None = None,
                    tipo: str = "lavorativi") -> str:
    """Giorni lavorativi, scadenze e festività italiane.

    Usalo per sapere quanti giorni (lavorativi o di calendario) mancano a una data o ci sono
    tra due date, per calcolare una scadenza dopo un numero di giorni, e per sapere che giorno
    è una data e se è lavorativo o festivo (Natale, Pasqua, Liberazione e le altre feste).
    Passa le date come le scrive l'utente (anche "Natale" o "25 dicembre"): non calcolarle tu.
    Riporta date e numeri esattamente come scritti, in testo semplice, senza LaTeX e senza il
    simbolo $. OBBLIGATORIO: la tua risposta all'utente che usa il risultato di tooldate
    termina sempre con la frase "Calcolo indicativo, non ha valore legale." (anche se la
    risposta è breve). La frase vale solo per le risposte su date e scadenze calcolate con
    tooldate: non aggiungerla alle risposte che non usano tooldate.
    Se il risultato è un errore, spiegalo all'utente senza inventare un valore.
    """
    # corpo della richiesta: solo i campi davvero indicati (le date vuote non si mandano)
    corpo = {"operazione": operazione, "tipo": tipo}
    for chiave, valore in (("data", data), ("da", da)):
        if valore and valore.strip():
            corpo[chiave] = valore
    if giorni is not None:
        corpo["giorni"] = giorni
    risposta = _chiedi_al_servizio("/giorni", corpo)
    # stringa = messaggio di guasto gia' pronto
    if isinstance(risposta, str):
        return risposta
    stato, dati = risposta
    if stato == 400:
        return f"Data rifiutata: {dati['errore']}"
    # sceglie la funzione giusta per l'operazione; un campo mancante o del tipo sbagliato
    # nella risposta diventa "risposta non valida" invece di un errore del programma
    try:
        return _TESTI_DATE[operazione](dati)
    except (KeyError, TypeError, AttributeError):
        return MSG_CALC_NON_VALIDA


# i 4 strumenti locali/FastAPI; app/cli.py ci aggiunge quelli dei server MCP
STRUMENTI = [ora_corrente, converti_unita, calcola_espressione, date_e_scadenze]
