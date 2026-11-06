# librerie standard: variabili d'ambiente, classi di soli dati, fusi orari IANA
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# funzione che legge FUSO_PREDEFINITO (con la riserva Europe/Rome)
from app.tools import fuso_predefinito


# contenitore della configurazione: frozen=True la rende immutabile dopo la creazione
@dataclass(frozen=True)
class Settings:
    base_url: str  # indirizzo dell'API di LM Studio (LM_BASE_URL)
    model: str  # identificativo del modello caricato (LM_MODEL)
    max_steps: int  # numero massimo di giri modello-strumenti per una domanda
    fuso_predefinito: str  # fuso dell'orologio quando l'utente non indica un luogo


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
        # un testo non numerico diventa 0, cosi' cade nel controllo qui sotto
        max_steps = 0
    if max_steps < 1:
        raise ValueError(f"MAX_STEPS deve essere un intero positivo, trovato: {grezzo!r}")
    fuso = fuso_predefinito()
    # prova a creare il fuso: se il nome non esiste, ZoneInfo solleva un errore
    try:
        ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # "from None" nasconde l'errore originale: l'utente vede solo il messaggio chiaro
        raise ValueError(f"FUSO_PREDEFINITO non e' un fuso IANA valido: {fuso!r}") from None
    # tutti i controlli sono passati: restituisce la configurazione pronta
    return Settings(base_url=base_url, model=model, max_steps=max_steps,
                    fuso_predefinito=fuso)
