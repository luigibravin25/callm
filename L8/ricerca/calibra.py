r"""Calibrazione delle soglie sullo score (lezione 8, esercizio 4): score delle fonti e delle domande senza risposta.

Uso, da L8\ricerca (Qdrant e LM Studio accesi, $env:EMBEDDING_MODEL impostata):
  & ..\venv\Scripts\python.exe calibra.py [-k N]
Ricerca in modalità base sulle domande di valutazione/domande.toml; la tabella va copiata in docs/rag-agente.md.
"""
# librerie standard: argomenti da riga di comando
import argparse

# client di Qdrant (server avviato con docker compose start qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.calibrazione import riga, tabella_calibrazione
from app.config import carica_configurazione
from app.embedding import EmbedderLMStudio
from app.indice import Indice
from app.valutazione import leggi_domande
from valuta import DOMANDE


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """k (None = TOP_K della configurazione, deciso dopo)."""
    parser = argparse.ArgumentParser(description="Calibrazione delle soglie sullo score")
    parser.add_argument("-k", type=int, default=None, help="passaggi per domanda (predefinito TOP_K, cioè 5)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: ricerca base per ogni domanda, score registrati, tabella su stdout
    def principale() -> None:
        # argomenti prima della configurazione: --help funziona anche senza variabili d'ambiente
        argomenti = leggi_argomenti(argv)
        conf = carica_configurazione()
        k = argomenti.k if argomenti.k is not None else conf.top_k
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        righe = [riga(d, indice.cerca(d.testo, k=k)) for d in leggi_domande(DOMANDE)]
        intestazione = {"modello di embedding": conf.modello_embedding,
                        "collezione": f"{conf.collezione} ({indice.conta_punti()} punti)", "modalità": "base",
                        "k": str(k),
                        "soglie configurate ora": f"{conf.soglia_alta:.2f}/{conf.soglia_bassa:.2f}"}
        print(tabella_calibrazione(righe, intestazione))

    esegui_script(principale)


if __name__ == "__main__":
    main()
