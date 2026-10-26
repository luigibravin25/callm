import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    max_steps: int


def _obbligatoria(nome: str) -> str:
    valore = os.environ.get(nome, "").strip()
    if not valore:
        raise ValueError(f"Variabile d'ambiente mancante: {nome}")
    return valore


def load_settings() -> Settings:
    """Legge la configurazione dalle variabili d'ambiente (nessun file .env)."""
    base_url = _obbligatoria("LM_BASE_URL")
    model = _obbligatoria("LM_MODEL")
    grezzo = os.environ.get("MAX_STEPS", "5").strip()
    try:
        max_steps = int(grezzo)
    except ValueError:
        max_steps = 0
    if max_steps < 1:
        raise ValueError(f"MAX_STEPS deve essere un intero positivo, trovato: {grezzo!r}")
    return Settings(base_url=base_url, model=model, max_steps=max_steps)
