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
from qdrant_client.models import (Distance, FieldCondition, Filter, IsEmptyCondition, MatchValue, PayloadField,
                                  PayloadSchemaType, PointIdsList, PointStruct, VectorParams)

from app.chunking import Chunk, ha_dosi, testo_indicizzato
from app.config import TOP_K_MASSIMO
from app.corpus import CAPITOLI
from app.embedding import Embedder
from app.errori import ErroreRicerca

log = logging.getLogger("ricerca")

# forma del testo passato all'embedder, registrata nel metadata della collezione
TESTO_INDICIZZATO = "titolo e capitolo + testo"
# campi del payload filtrati dalla ricerca, con il tipo del loro indice
CAMPI_INDICIZZATI = {"capitolo": PayloadSchemaType.KEYWORD, "contiene_dosi": PayloadSchemaType.BOOL}

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


# conteggi di aggiorna_dosi, per il log finale
@dataclass(frozen=True)
class EsitoDosi:
    punti: int  # punti aggiornati (tutti quelli della collezione)
    con_dosi: int  # punti con contiene_dosi vero


# un risultato della ricerca con la sua fonte: ricetta, capitolo, posizione del chunk
@dataclass(frozen=True)
class Risultato:
    posizione: int  # 1..k
    score: float  # similarità coseno
    numero: int
    titolo: str
    capitolo: str
    indice_chunk: int
    totale_chunk: int
    testo: str  # testo originale del chunk
    contiene_dosi: bool = False  # il chunk ha un elenco di ingredienti


# capitolo scritto dall'utente → nome esatto dell'elenco (senza maiuscole/minuscole e spazi ai bordi)
def _capitolo_valido(capitolo: str) -> str:
    cercato = capitolo.strip().upper()
    if cercato not in CAPITOLI:
        raise ErroreRicerca(f"capitolo {capitolo!r} sconosciuto; capitoli validi: {', '.join(CAPITOLI)}")
    return cercato


class Indice:
    # embedder None: solo operazioni senza embedding (aggiorna_dosi)
    def __init__(self, client: QdrantClient, collezione: str, modello: str, embedder: Embedder | None):
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
        log.info("creata la collezione %s (modello %s, dimensione %d)", self.collezione, self.modello, dimensione)

    # indici sui campi filtrati: si creano a ogni ingestion (senza effetto se ci sono già), così non si
    # perdono se un'ingestion si interrompe subito dopo aver creato la collezione
    def _crea_indici(self) -> None:
        for campo, tipo in CAMPI_INDICIZZATI.items():
            self.client.create_payload_index(self.collezione, field_name=campo, field_schema=tipo)

    def registrazione(self) -> dict:
        """Metadata della collezione (modello, dimensione, chunking, testo indicizzato); {} se assente."""
        return self._leggi_registrazione() or {}

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

    def indicizza(self, chunk: list[Chunk], chunking: str = "", lotto: int = 64) -> EsitoIngestion:
        """Scrive un punto per chunk (upsert); a scrittura completa cancella i punti non prodotti (orfani)."""
        # il cambio di modello si blocca prima di calcolare embedding
        self.controlla_modello()
        prodotti: set[str] = set()
        for inizio in range(0, len(chunk), lotto):
            parte = chunk[inizio:inizio + lotto]
            # all'embedder titolo e capitolo davanti al chunk; nel payload resta il testo originale
            vettori = self.embedder.incorpora([testo_indicizzato(c) for c in parte])
            if not self.esiste():
                self._crea_collezione(len(vettori[0]))
            punti = [PointStruct(id=id_punto(c.numero, c.indice_chunk), vector=v, payload={
                "testo": c.testo, "numero": c.numero, "titolo": c.titolo, "capitolo": c.capitolo,
                "indice_chunk": c.indice_chunk, "totale_chunk": c.totale_chunk,
                "contiene_dosi": c.contiene_dosi}) for c, v in zip(parte, vettori)]
            self.client.upsert(self.collezione, points=punti)
            prodotti.update(p.id for p in punti)
            log.info("scritti %d/%d chunk", min(inizio + lotto, len(chunk)), len(chunk))
        # solo dopo un upsert completo: via i punti di giri precedenti non più prodotti
        orfani = [i for i in self._tutti_gli_id() if i not in prodotti]
        if orfani:
            self.client.delete(self.collezione, points_selector=PointIdsList(points=orfani))
        self._crea_indici()
        # metadata aggiornato solo a scrittura completa (i campi esistenti restano): un'ingestion interrotta
        # non dichiara un chunking o un testo indicizzato che non sono stati scritti per intero
        self.client.update_collection(self.collezione,
                                      metadata={"chunking": chunking, "testo_indicizzato": TESTO_INDICIZZATO})
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

    # --- campo contiene_dosi sui punti esistenti (senza embedding) ---

    def aggiorna_dosi(self, ingredienti: dict[int, tuple[str, ...]], lotto: int = 256) -> EsitoDosi:
        """Scrive contiene_dosi su tutti i punti dal testo del loro payload; nessun embedding, nessun chunking."""
        if not self.esiste():
            raise ErroreRicerca(f"la collezione {self.collezione} non esiste: eseguire prima l'ingestion")
        # prima si calcola tutto: con un numero sconosciuto non si scrive niente
        valori: dict[bool, list] = {True: [], False: []}
        prossimo = None
        while True:
            punti, prossimo = self.client.scroll(self.collezione, limit=1000, offset=prossimo,
                                                 with_payload=["numero", "testo"], with_vectors=False)
            for p in punti:
                numero = p.payload.get("numero")
                if numero not in ingredienti:
                    raise ErroreRicerca(f"il punto {p.id} ha la ricetta n. {numero}, che non è nel corpus: "
                                        "rifare l'ingestion")
                valori[ha_dosi(p.payload.get("testo", ""), ingredienti[numero])].append(p.id)
            if prossimo is None:
                break
        # un set_payload per valore, a lotti di ID
        for valore, ids in valori.items():
            for inizio in range(0, len(ids), lotto):
                self.client.set_payload(self.collezione, payload={"contiene_dosi": valore},
                                        points=ids[inizio:inizio + lotto])
        self._crea_indici()
        return EsitoDosi(punti=len(valori[True]) + len(valori[False]), con_dosi=len(valori[True]))

    # --- ricerca ---

    def cerca(self, domanda: str, capitolo: str | None = None, k: int = 5,
              solo_dosi: bool = False) -> list[Risultato]:
        """Primi k chunk più vicini alla domanda (al massimo TOP_K_MASSIMO), filtrabili per capitolo e dosi."""
        if not domanda.strip():
            raise ErroreRicerca("la domanda è vuota")
        if k < 1:
            raise ErroreRicerca(f"k={k} non valido (ammesso: intero >= 1)")
        nome_capitolo = _capitolo_valido(capitolo) if capitolo is not None else None
        if not self.esiste():
            raise ErroreRicerca(f"la collezione {self.collezione} non esiste: eseguire prima l'ingestion")
        # stesso modello dell'indice, controllato prima di calcolare l'embedding della domanda
        self.controlla_modello()
        if solo_dosi:
            self._controlla_campo_dosi()
        if k > TOP_K_MASSIMO:
            log.warning("k=%d oltre il massimo: ridotto a %d", k, TOP_K_MASSIMO)
            k = TOP_K_MASSIMO
        # stessa funzione di embedding dei chunk, sul testo esatto della domanda
        vettore = self.embedder.incorpora([domanda])[0]
        # filtro applicato da Qdrant durante la ricerca, non dopo
        condizioni = []
        if nome_capitolo is not None:
            condizioni.append(FieldCondition(key="capitolo", match=MatchValue(value=nome_capitolo)))
        if solo_dosi:
            condizioni.append(FieldCondition(key="contiene_dosi", match=MatchValue(value=True)))
        filtro = Filter(must=condizioni) if condizioni else None
        punti = self.client.query_points(self.collezione, query=vettore, query_filter=filtro, limit=k,
                                         with_payload=True).points
        return [Risultato(posizione=i, score=p.score, numero=p.payload["numero"], titolo=p.payload["titolo"],
                          capitolo=p.payload["capitolo"], indice_chunk=p.payload["indice_chunk"],
                          totale_chunk=p.payload["totale_chunk"], testo=p.payload["testo"],
                          contiene_dosi=p.payload.get("contiene_dosi", False))
                for i, p in enumerate(punti, start=1)]

    # errore se qualche punto non ha ancora il campo: il filtro lo escluderebbe senza dirlo
    def _controlla_campo_dosi(self) -> None:
        senza = self.client.count(self.collezione, exact=True, count_filter=Filter(
            must=[IsEmptyCondition(is_empty=PayloadField(key="contiene_dosi"))])).count
        if senza:
            raise ErroreRicerca(f"la collezione {self.collezione} non ha ancora il campo contiene_dosi "
                                f"({senza} punti senza): eseguire aggiorna_dosi.py")

    def conta_punti(self) -> int:
        return self.client.count(self.collezione, exact=True).count
