"""Aggiunge il campo contiene_dosi ai punti già nell'indice, senza ricalcolare gli embedding.

Uso, da L7\\ricerca:  & ..\\venv\\Scripts\\python.exe aggiorna_dosi.py
Legge il corpus (righe di ingrediente di ogni ricetta) e decide il campo dal testo salvato nel payload di
ogni punto: non rifà il chunking e non chiama LM Studio. Ripeterlo dà lo stesso risultato.
"""
# librerie standard: log, misura della durata
import logging
import time

# client di Qdrant (server avviato con docker compose up -d qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.config import Configurazione, carica_configurazione
from app.corpus import carica_corpus
from app.indice import EsitoDosi, Indice

log = logging.getLogger("ricerca")


def esegui(conf: Configurazione, client: QdrantClient) -> EsitoDosi:
    """Aggiornamento del campo su tutti i punti; il log finale riassume i conteggi."""
    inizio = time.perf_counter()
    ingredienti = {r.numero: r.ingredienti for r in carica_corpus(conf.corpus_file)}
    # nessun embedder: questo script non calcola embedding
    esito = Indice(client, conf.collezione, conf.modello_embedding, None).aggiorna_dosi(ingredienti)
    durata = time.perf_counter() - inizio
    log.info("punti aggiornati %d · con dosi %d · senza dosi %d · embedding ricalcolati 0 · durata %.1fs",
             esito.punti, esito.con_dosi, esito.punti - esito.con_dosi, durata)
    return esito


# corpo dello script: configurazione, client reale, aggiornamento
def _principale() -> None:
    conf = carica_configurazione()
    esegui(conf, QdrantClient(url=conf.qdrant_url))


def main() -> None:
    configura_log()
    esegui_script(_principale)


if __name__ == "__main__":
    main()
