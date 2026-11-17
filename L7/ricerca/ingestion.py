"""Ingestion (script separato): corpus → chunk → embedding da LM Studio → punti in Qdrant.

Uso, da L7\\ricerca:  & ..\\venv\\Scripts\\python.exe ingestion.py
Nessun argomento: tutto dalla configurazione (variabili d'ambiente, vedi README.md).
"""
# librerie standard: log, misura della durata
import logging
import time

# client di Qdrant (server avviato con docker compose up -d qdrant)
from qdrant_client import QdrantClient

from app.avvio import configura_log, esegui as esegui_script
from app.chunking import chunk_delle_ricette
from app.config import Configurazione, carica_configurazione
from app.corpus import carica_corpus
from app.embedding import Embedder, EmbedderLMStudio
from app.indice import EsitoIngestion, Indice

log = logging.getLogger("ricerca")


def esegui(conf: Configurazione, client: QdrantClient, embedder: Embedder) -> EsitoIngestion:
    """Ingestion completa; il log finale riassume i conteggi."""
    inizio = time.perf_counter()
    indice = Indice(client, conf.collezione, conf.modello_embedding, embedder)
    # modello diverso da quello della collezione: errore prima ancora di leggere il corpus
    indice.controlla_modello()
    ricette = carica_corpus(conf.corpus_file)
    chunk = chunk_delle_ricette(ricette, conf.strategia, conf.dimensione, conf.overlap)
    log.info("corpus letto: %d ricette, %d chunk; embedding con %s", len(ricette), len(chunk), conf.modello_embedding)
    esito = indice.indicizza(chunk, chunking=f"{conf.strategia} {conf.dimensione}/{conf.overlap}")
    durata = time.perf_counter() - inizio
    log.info("ricette %d · chunk %d · punti scritti %d · orfani cancellati %d · punti nella collezione %d · "
             "modello %s · chunking %s %d/%d · durata %.1fs", len(ricette), esito.chunk, esito.scritti,
             esito.orfani, esito.punti, conf.modello_embedding, conf.strategia, conf.dimensione, conf.overlap,
             durata)
    return esito


# corpo dello script: configurazione, client reali, ingestion
def _principale() -> None:
    conf = carica_configurazione()
    esegui(conf, QdrantClient(url=conf.qdrant_url), EmbedderLMStudio(conf.lm_base_url, conf.modello_embedding))


def main() -> None:
    configura_log()
    esegui_script(_principale)


if __name__ == "__main__":
    main()
