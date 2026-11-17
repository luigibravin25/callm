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


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: configurazione, ricerca per ogni domanda, tabella su stdout
    def principale() -> None:
        conf = carica_configurazione()
        parser = argparse.ArgumentParser(description="Valutazione della ricerca sulle domande con fonte attesa")
        parser.add_argument("-k", type=int, default=conf.top_k,
                            help=f"risultati per domanda (predefinito {conf.top_k}, massimo {TOP_K_MASSIMO})")
        k = parser.parse_args(argv).k
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        righe = valuta(leggi_domande(DOMANDE), lambda domanda: indice.cerca(domanda, k=k))
        # parametri dalla collezione: dicono come è stato costruito l'indice, non com'è la configurazione ora
        intestazione = intestazione_valutazione(indice.registrazione(), conf.collezione, indice.conta_punti(),
                                                min(k, TOP_K_MASSIMO), solo_dosi=False)
        print(tabella_markdown(righe, intestazione))

    esegui_script(principale)


if __name__ == "__main__":
    main()
