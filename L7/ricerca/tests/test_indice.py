# test dell'ingestion in Qdrant in memoria con embedder finto: punti, payload, metadata, ripetizioni, orfani
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.chunking import chunk_delle_ricette
from app.corpus import Ricetta
from app.errori import ErroreRicerca
from app.indice import Indice, id_punto
from tests.finti import EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")

PAROLE = "Mettete la carne nella cazzaruola con burro sale e pepe poi bagnatela col brodo".split()


# testo di prova lungo circa `caratteri`, diverso per ogni ricetta
def parole_di(numero: int, caratteri: int) -> str:
    parole = [f"{PAROLE[i % len(PAROLE)]}{numero}" for i in range(caratteri // 8)]
    return " ".join(parole)


# tre ricette finte di due capitoli: una corta e due lunghe
RICETTE = [
    Ricetta(1, "Brodo", "BRODI, GELATINA E SUGHI", parole_di(1, 300)),
    Ricetta(2, "Sugo", "BRODI, GELATINA E SUGHI", parole_di(2, 2500)),
    Ricetta(3, "Cappelletti", "MINESTRE IN BRODO", parole_di(3, 1800)),
]


def chunk(dimensione: int = 1000, overlap: int = 150):
    return chunk_delle_ricette(RICETTE, "paragrafi", dimensione, overlap)


@pytest.fixture
def client():
    return QdrantClient(":memory:")


def indice(client, modello: str = "bge", embedder=None) -> Indice:
    return Indice(client, "ricettario", modello, embedder or EmbedderFinto())


def test_un_punto_per_chunk_e_payload(client):
    lista = chunk()
    esito = indice(client).indicizza(lista)
    assert esito.chunk == esito.scritti == esito.punti == len(lista)
    assert esito.orfani == 0
    primo = lista[1]
    punto = client.retrieve("ricettario", [id_punto(primo.numero, primo.indice_chunk)], with_payload=True)[0]
    assert punto.payload == {"testo": primo.testo, "numero": primo.numero, "titolo": primo.titolo,
                             "capitolo": primo.capitolo, "indice_chunk": primo.indice_chunk,
                             "totale_chunk": primo.totale_chunk}


def test_metadata_con_il_modello(client):
    indice(client).indicizza(chunk())
    assert client.get_collection("ricettario").config.metadata == {"modello_embedding": "bge", "dimensione": 8}


def test_id_dalla_posizione():
    assert id_punto(7, 0) == id_punto(7, 0)
    assert id_punto(7, 0) != id_punto(7, 1) != id_punto(70, 1)


def test_due_ingestion_stessi_punti(client):
    lista = chunk()
    prima = indice(client).indicizza(lista)
    id_prima = {p.id for p in client.scroll("ricettario", limit=1000)[0]}
    seconda = indice(client).indicizza(lista)
    assert seconda.punti == prima.punti and seconda.orfani == 0
    assert {p.id for p in client.scroll("ricettario", limit=1000)[0]} == id_prima


def test_orfani_dopo_cambio_di_dimensione(client):
    piccoli = chunk(dimensione=200, overlap=20)
    indice(client).indicizza(piccoli, lotto=5)
    grandi = chunk()
    esito = indice(client).indicizza(grandi, lotto=5)
    assert esito.orfani == len(piccoli) - len(grandi) > 0
    assert esito.punti == len(grandi)


def test_modello_diverso_bloccato(client):
    indice(client).indicizza(chunk())
    altro = EmbedderFinto()
    with pytest.raises(ErroreRicerca) as errore:
        indice(client, modello="altro", embedder=altro).indicizza(chunk())
    assert "bge" in str(errore.value) and "altro" in str(errore.value)
    # bloccato prima di ogni embedding
    assert altro.chiamate == []


def test_collezione_senza_metadata_bloccata(client):
    client.create_collection("ricettario", vectors_config=VectorParams(size=8, distance=Distance.COSINE))
    finto = EmbedderFinto()
    with pytest.raises(ErroreRicerca, match="nessun modello registrato"):
        indice(client, embedder=finto).indicizza(chunk())
    assert finto.chiamate == []
    assert client.count("ricettario").count == 0


def test_ingestion_interrotta(client):
    prima = chunk(dimensione=200, overlap=20)
    indice(client).indicizza(prima, lotto=5)
    id_prima = {p.id for p in client.scroll("ricettario", limit=1000)[0]}
    # seconda ingestion con chunk diversi: LM Studio si ferma al secondo lotto
    with pytest.raises(ErroreRicerca):
        indice(client, embedder=EmbedderFinto(fallisci_alla_chiamata=2)).indicizza(chunk(), lotto=5)
    # nessun orfano cancellato: i punti della prima ingestion ci sono ancora tutti
    assert id_prima <= {p.id for p in client.scroll("ricettario", limit=1000)[0]}
    # una nuova ingestion completa rimette a posto i conteggi
    esito = indice(client).indicizza(chunk(), lotto=5)
    assert esito.punti == len(chunk())


def test_conta_punti(client):
    ix = indice(client)
    ix.indicizza(chunk())
    assert ix.conta_punti() == len(chunk())
