# librerie standard: variabili d'ambiente, lettura dei file TOML, percorsi, classi di dati, fusi
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# cartella assistente-laboratorio/: i percorsi relativi della configurazione partono da qui
CARTELLA_PROGETTO = Path(__file__).resolve().parent.parent

FUSO_DI_RISERVA = "Europe/Rome"  # usato se FUSO_PREDEFINITO non e' impostata
AMBITO_PREDEFINITO = "config/ambito.toml"  # usato se AMBITO_FILE non e' impostata


# contenitore della configurazione: frozen=True la rende immutabile dopo la creazione
@dataclass(frozen=True)
class Settings:
    base_url: str  # indirizzo dell'API di LM Studio (LM_BASE_URL)
    model: str  # identificativo del modello caricato (LM_MODEL)
    max_steps: int  # numero massimo di giri modello-strumenti per una domanda
    fuso_predefinito: str  # fuso dell'orologio quando l'utente non indica un luogo
    ambito_file: Path  # file TOML con l'ambito dell'agente


# ambito dell'agente letto da config/ambito.toml: entra nel prompt del router
@dataclass(frozen=True)
class Ambito:
    descrizione: str  # di cosa puo' parlare l'agente
    rifiuto: str  # risposta fissa per le domande fuori ambito
    esempi_in_ambito: tuple[str, ...] = ()  # esempi di domande accettate
    esempi_fuori_ambito: tuple[str, ...] = ()  # esempi di domande rifiutate


# fuso da usare quando l'utente non indica un luogo (usato anche da tooltime)
def fuso_predefinito() -> str:
    """Variabile FUSO_PREDEFINITO senza spazi, oppure Europe/Rome."""
    # una variabile vuota o fatta di spazi diventa "" e "or" passa alla riserva
    return os.environ.get("FUSO_PREDEFINITO", "").strip() or FUSO_DI_RISERVA


# legge una variabile d'ambiente che deve esserci per forza
def _obbligatoria(nome: str) -> str:
    # strip() toglie spazi e a capo: una variabile fatta solo di spazi conta come vuota
    valore = os.environ.get(nome, "").strip()
    if not valore:
        raise ValueError(f"Variabile d'ambiente mancante: {nome}")
    return valore


# costruisce la configurazione completa e controlla che i valori siano validi
def load_settings() -> Settings:
    """Legge la configurazione dalle variabili d'ambiente (nessun file .env)."""
    base_url = _obbligatoria("LM_BASE_URL")
    model = _obbligatoria("LM_MODEL")
    # MAX_STEPS e' facoltativa: se manca vale 5
    grezzo = os.environ.get("MAX_STEPS", "5").strip()
    try:
        max_steps = int(grezzo)
    except ValueError:
        max_steps = 0  # un testo non numerico cade nel controllo qui sotto
    if max_steps < 1:
        raise ValueError(f"MAX_STEPS deve essere un intero positivo, trovato: {grezzo!r}")
    fuso = fuso_predefinito()
    # prova a creare il fuso: se il nome non esiste, ZoneInfo solleva un errore
    try:
        ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"FUSO_PREDEFINITO non e' un fuso IANA valido: {fuso!r}") from None
    # percorso dell'ambito: se e' relativo parte dalla cartella del progetto, non da quella corrente
    ambito_file = Path(os.environ.get("AMBITO_FILE", "").strip() or AMBITO_PREDEFINITO)
    if not ambito_file.is_absolute():
        ambito_file = CARTELLA_PROGETTO / ambito_file
    return Settings(base_url=base_url, model=model, max_steps=max_steps,
                    fuso_predefinito=fuso, ambito_file=ambito_file)


# controlla un campo di testo obbligatorio del file dell'ambito
def _testo(dati: dict, campo: str, percorso: Path) -> str:
    valore = dati.get(campo)
    if not isinstance(valore, str) or not valore.strip():
        raise ValueError(f"{percorso.name}: il campo '{campo}' manca o e' vuoto")
    return valore.strip()


# controlla un elenco facoltativo di esempi (lista di testi)
def _esempi(dati: dict, campo: str, percorso: Path) -> tuple[str, ...]:
    valore = dati.get(campo, [])
    if not isinstance(valore, list) or not all(isinstance(e, str) for e in valore):
        raise ValueError(f"{percorso.name}: il campo '{campo}' deve essere una lista di testi")
    return tuple(e.strip() for e in valore if e.strip())


# legge e controlla il file TOML dell'ambito
def load_ambito(percorso: Path) -> Ambito:
    """Ambito dal file TOML; ogni problema diventa un ValueError con file e campo."""
    try:
        # tomllib vuole il file in binario: la codifica UTF-8 la gestisce lui
        with open(percorso, "rb") as f:
            dati = tomllib.load(f)
    except FileNotFoundError:
        raise ValueError(f"File dell'ambito non trovato: {percorso}") from None
    except tomllib.TOMLDecodeError as errore:
        raise ValueError(f"{percorso.name}: TOML non valido ({errore})") from None
    return Ambito(
        descrizione=_testo(dati, "descrizione", percorso),
        rifiuto=_testo(dati, "rifiuto", percorso),
        esempi_in_ambito=_esempi(dati, "esempi_in_ambito", percorso),
        esempi_fuori_ambito=_esempi(dati, "esempi_fuori_ambito", percorso),
    )
