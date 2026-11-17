"""Ricerca semantica nel ricettario: i chunk più vicini a una domanda, con la loro fonte.

Uso, da L7\\ricerca:  & ..\\venv\\Scripts\\python.exe cerca.py "domanda" [--capitolo NOME] [-k N]
"""
# librerie standard: argomenti da riga di comando
import argparse

# client di Qdrant (server avviato con docker compose up -d qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.config import TOP_K_MASSIMO, carica_configurazione
from app.embedding import EmbedderLMStudio
from app.indice import Indice, Risultato


def formatta(risultati: list[Risultato]) -> str:
    """Una riga di fonte per risultato (ricetta, capitolo, posizione del chunk) e sotto il testo."""
    if not risultati:
        return "Nessun risultato."
    blocchi = [f"#{r.posizione} · score {r.score:.4f} · n. {r.numero} «{r.titolo}» · {r.capitolo} · "
               f"chunk {r.indice_chunk + 1} di {r.totale_chunk}\n{r.testo}" for r in risultati]
    return "\n\n".join(blocchi)


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """Domanda, capitolo facoltativo e k (None = TOP_K della configurazione, deciso dopo)."""
    parser = argparse.ArgumentParser(description="Ricerca semantica nel ricettario di Artusi")
    parser.add_argument("domanda", help="la domanda, tra virgolette")
    parser.add_argument("--capitolo", help="cerca solo in questo capitolo (es. \"minestre in brodo\")")
    parser.add_argument("-k", type=int, default=None,
                        help=f"numero di risultati (predefinito TOP_K, massimo {TOP_K_MASSIMO})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    configura_log()

    # corpo dello script: configurazione, argomenti, ricerca, stampa
    def principale() -> None:
        # argomenti prima della configurazione: --help funziona anche senza variabili d'ambiente
        argomenti = leggi_argomenti(argv)
        conf = carica_configurazione()
        k = argomenti.k if argomenti.k is not None else conf.top_k
        indice = Indice(QdrantClient(url=conf.qdrant_url), conf.collezione, conf.modello_embedding,
                        EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))
        print(formatta(indice.cerca(argomenti.domanda, capitolo=argomenti.capitolo, k=k)))

    esegui_script(principale)


if __name__ == "__main__":
    main()
