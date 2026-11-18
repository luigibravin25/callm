"""Configurazione della ricerca, letta solo dalle variabili d'ambiente (Python non legge .env)."""
# librerie standard: variabili d'ambiente, classi di dati, percorsi
import os
from dataclasses import dataclass
from pathlib import Path

from app.errori import ErroreRicerca

# cartella L7/ (padre di ricerca/): i percorsi relativi della configurazione partono da qui,
# non dalla cartella da cui si lancia lo script
CARTELLA_L7 = Path(__file__).resolve().parents[2]

# massimo dei risultati di una ricerca: imposto dal codice, non configurabile
TOP_K_MASSIMO = 20

# strategie di chunking ammesse (CHUNK_STRATEGIA)
STRATEGIE = ("paragrafi", "caratteri")


# contenitore della configurazione: frozen=True la rende immutabile dopo la creazione
@dataclass(frozen=True)
class Configurazione:
    lm_base_url: str  # API di LM Studio (LM_BASE_URL)
    modello_embedding: str  # id del modello di embedding (EMBEDDING_MODEL)
    qdrant_url: str  # indirizzo di Qdrant (QDRANT_URL)
    collezione: str  # nome della collezione (QDRANT_COLLEZIONE)
    corpus_file: Path  # file del ricettario (CORPUS_FILE)
    strategia: str  # strategia di chunking (CHUNK_STRATEGIA)
    dimensione: int  # caratteri massimi di un chunk (CHUNK_DIMENSIONE)
    overlap: int  # caratteri ripresi dal chunk precedente (CHUNK_OVERLAP)
    top_k: int  # risultati predefiniti di una ricerca (TOP_K)


# valore di una variabile senza spazi ai bordi; vuota o assente → predefinito
def _testo(nome: str, predefinito: str) -> str:
    return os.environ.get(nome, "").strip() or predefinito


# intero di una variabile con il minimo ammesso; errore con nome e valore ammesso
def _intero(nome: str, predefinito: int, minimo: int) -> int:
    grezzo = _testo(nome, str(predefinito))
    try:
        valore = int(grezzo)
    except ValueError:
        raise ErroreRicerca(f"{nome}={grezzo!r} non è un intero (ammesso: intero >= {minimo})") from None
    if valore < minimo:
        raise ErroreRicerca(f"{nome}={valore} non valido (ammesso: intero >= {minimo})")
    return valore


def carica_configurazione() -> Configurazione:
    """Legge e controlla le variabili d'ambiente prima di qualsiasi chiamata a LM Studio o Qdrant."""
    # il modello non ha predefinito: deve essere quello caricato in LM Studio
    modello = _testo("EMBEDDING_MODEL", "")
    if not modello:
        raise ErroreRicerca("EMBEDDING_MODEL non impostata: indicare l'id del modello di embedding "
                            "(GET /v1/models di LM Studio), es. $env:EMBEDDING_MODEL = \"...\"")
    strategia = _testo("CHUNK_STRATEGIA", "paragrafi")
    if strategia not in STRATEGIE:
        raise ErroreRicerca(f"CHUNK_STRATEGIA={strategia!r} non valida (ammesse: {', '.join(STRATEGIE)})")
    dimensione = _intero("CHUNK_DIMENSIONE", 1000, 1)
    overlap = _intero("CHUNK_OVERLAP", 150, 0)
    # l'overlap deve lasciare spazio a testo nuovo in ogni chunk
    if overlap >= dimensione:
        raise ErroreRicerca(f"CHUNK_OVERLAP={overlap} non valido (ammesso: 0 <= overlap < "
                            f"CHUNK_DIMENSIONE={dimensione})")
    # percorso relativo → da L7/; percorso assoluto → com'è
    corpus = Path(_testo("CORPUS_FILE", "Ricettario/Ricettario.txt"))
    if not corpus.is_absolute():
        corpus = CARTELLA_L7 / corpus
    return Configurazione(
        lm_base_url=_testo("LM_BASE_URL", "http://127.0.0.1:1234/v1"),
        modello_embedding=modello,
        qdrant_url=_testo("QDRANT_URL", "http://127.0.0.1:6333"),
        collezione=_testo("QDRANT_COLLEZIONE", "ricettario"),
        corpus_file=corpus,
        strategia=strategia,
        dimensione=dimensione,
        overlap=overlap,
        top_k=_intero("TOP_K", 5, 1),
    )
