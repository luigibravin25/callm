"""Indice vettoriale in Qdrant: un punto per chunk con ID stabili, modello registrato, orfani cancellati.

La collezione registra nel suo metadata il modello di embedding: ingestion e ricerca con un modello
diverso si fermano prima di calcolare embedding (specifica, §10).
"""
# librerie standard: log, identificativi, classi di dati
import logging
import uuid
from dataclasses import dataclass

# client di Qdrant (server in Docker oppure in memoria nei test)
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointIdsList, PointStruct, VectorParams

from app.chunking import Chunk
from app.embedding import Embedder
from app.errori import ErroreRicerca

log = logging.getLogger("ricerca")

# namespace fisso degli ID: stesso numero di ricetta e stessa posizione → stesso ID a ogni ingestion
NAMESPACE_ID = uuid.UUID("6f1d2c4e-8a3b-5e7f-9c1d-2b4a6e8f0a13")


def id_punto(numero: int, indice_chunk: int) -> str:
    """ID del punto dalla posizione del chunk (non dal testo): l'esercizio 2 aggiorna gli stessi punti."""
    return str(uuid.uuid5(NAMESPACE_ID, f"{numero}-{indice_chunk}"))


# conteggi di un'ingestion, per il log finale
@dataclass(frozen=True)
class EsitoIngestion:
    chunk: int  # chunk prodotti dal corpus
    scritti: int  # punti scritti con upsert
    orfani: int  # punti cancellati perché non prodotti in questo giro
    punti: int  # punti nella collezione alla fine


class Indice:
    def __init__(self, client: QdrantClient, collezione: str, modello: str, embedder: Embedder):
        self.client = client
        self.collezione = collezione
        self.modello = modello
        self.embedder = embedder

    # --- registrazione del modello (unico punto da cambiare per il ripiego <collezione>_info) ---

    def _leggi_registrazione(self) -> dict | None:
        return self.client.get_collection(self.collezione).config.metadata or None

    def _crea_collezione(self, dimensione: int) -> None:
        # coseno, dimensione dal primo embedding, modello e dimensione nel metadata
        self.client.create_collection(
            self.collezione, vectors_config=VectorParams(size=dimensione, distance=Distance.COSINE),
            metadata={"modello_embedding": self.modello, "dimensione": dimensione})
        # indice sul campo filtrato dalla ricerca
        self.client.create_payload_index(self.collezione, field_name="capitolo",
                                         field_schema=PayloadSchemaType.KEYWORD)
        log.info("creata la collezione %s (modello %s, dimensione %d)", self.collezione, self.modello, dimensione)

    # --- controlli ---

    def esiste(self) -> bool:
        return self.client.collection_exists(self.collezione)

    def controlla_modello(self) -> None:
        """Errore se la collezione esiste ed è stata costruita con un altro modello (o senza registrazione)."""
        if not self.esiste():
            return
        registrazione = self._leggi_registrazione()
        registrato = (registrazione or {}).get("modello_embedding")
        if registrato != self.modello:
            descrizione = registrato or "nessun modello registrato"
            raise ErroreRicerca(
                f"la collezione {self.collezione} usa il modello {descrizione}, la configurazione indica "
                f"{self.modello}: usare un'altra collezione (QDRANT_COLLEZIONE) o cancellarla")

    # --- ingestion ---

    def indicizza(self, chunk: list[Chunk], lotto: int = 64) -> EsitoIngestion:
        """Scrive un punto per chunk (upsert); a scrittura completa cancella i punti non prodotti (orfani)."""
        # il cambio di modello si blocca prima di calcolare embedding
        self.controlla_modello()
        prodotti: set[str] = set()
        for inizio in range(0, len(chunk), lotto):
            parte = chunk[inizio:inizio + lotto]
            vettori = self.embedder.incorpora([c.testo for c in parte])
            if not self.esiste():
                self._crea_collezione(len(vettori[0]))
            punti = [PointStruct(id=id_punto(c.numero, c.indice_chunk), vector=v, payload={
                "testo": c.testo, "numero": c.numero, "titolo": c.titolo, "capitolo": c.capitolo,
                "indice_chunk": c.indice_chunk, "totale_chunk": c.totale_chunk}) for c, v in zip(parte, vettori)]
            self.client.upsert(self.collezione, points=punti)
            prodotti.update(p.id for p in punti)
            log.info("scritti %d/%d chunk", min(inizio + lotto, len(chunk)), len(chunk))
        # solo dopo un upsert completo: via i punti di giri precedenti non più prodotti
        orfani = [i for i in self._tutti_gli_id() if i not in prodotti]
        if orfani:
            self.client.delete(self.collezione, points_selector=PointIdsList(points=orfani))
        return EsitoIngestion(chunk=len(chunk), scritti=len(prodotti), orfani=len(orfani),
                              punti=self.conta_punti())

    # tutti gli ID della collezione, a pagine
    def _tutti_gli_id(self) -> list[str]:
        ids: list[str] = []
        prossimo = None
        while True:
            punti, prossimo = self.client.scroll(self.collezione, limit=1000, offset=prossimo,
                                                 with_payload=False, with_vectors=False)
            ids.extend(str(p.id) for p in punti)
            if prossimo is None:
                return ids

    def conta_punti(self) -> int:
        return self.client.count(self.collezione, exact=True).count
