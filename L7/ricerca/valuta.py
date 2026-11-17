"""Valutazione della ricerca sulle domande con fonte attesa: stampa una tabella Markdown.

Uso, da L7\\ricerca:  & ..\\venv\\Scripts\\python.exe valuta.py [-k N]
La tabella va copiata in docs/retrieval.md.
"""
# librerie standard: argomenti da riga di comando, percorsi
import argparse
from pathlib import Path

# client di Qdrant (server avviato con docker compose up -d qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.config import TOP_K_MASSIMO, carica_configurazione
from app.embedding import EmbedderLMStudio
from app.indice import Indice
from app.valutazione import intestazione_valutazione, leggi_domande, tabella_markdown, valuta

# file delle domande, accanto a questo script
DOMANDE = Path(__file__).resolve().parent / "valutazione" / "domande.toml"


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """k (None = TOP_K della configurazione, deciso dopo)."""
    parser = argparse.ArgumentParser(description="Valutazione della ricerca sulle domande con fonte attesa")
    parser.add_argument("--solo-dosi", action="store_true",
                        help="cerca solo tra i chunk con un elenco di ingredienti")
    parser.add_argument("-k", type=int, default=None,
                        help=f"risultati per domanda (predefinito TOP_K, massimo {TOP_K_MASSIMO})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: argomenti, configurazione, ricerca per ogni domanda, tabella su stdout
    def principale() -> None:
        # argomenti prima della configurazione: --help funziona anche senza variabili d'ambiente
        argomenti = leggi_argomenti(argv)
        conf = carica_configurazione()
        k = argomenti.k if argomenti.k is not None else conf.top_k
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        righe = valuta(leggi_domande(DOMANDE),
                       lambda domanda: indice.cerca(domanda, k=k, solo_dosi=argomenti.solo_dosi))
        # parametri dalla collezione: dicono come è stato costruito l'indice, non com'è la configurazione ora
        intestazione = intestazione_valutazione(indice.registrazione(), conf.collezione, indice.conta_punti(),
                                                min(k, TOP_K_MASSIMO), solo_dosi=argomenti.solo_dosi)
        print(tabella_markdown(righe, intestazione))

    esegui_script(principale)


if __name__ == "__main__":
    main()
