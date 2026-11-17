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
                             "totale_chunk": primo.totale_chunk, "contiene_dosi": primo.contiene_dosi}


def test_metadata_con_il_modello(client):
    indice(client).indicizza(chunk())
    metadata = client.get_collection("ricettario").config.metadata
    # modello e dimensione registrati (chunking e testo indicizzato: test dedicato più sotto)
    assert (metadata["modello_embedding"], metadata["dimensione"]) == ("bge", 8)


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


# --- esercizio 2, minori 1 e 6: metadata a ingestion completa, indici sempre presenti ---

def test_metadata_con_chunking_e_testo_indicizzato(client):
    indice(client).indicizza(chunk(), chunking="paragrafi 1000/150")
    assert client.get_collection("ricettario").config.metadata == {
        "modello_embedding": "bge", "dimensione": 8, "chunking": "paragrafi 1000/150",
        "testo_indicizzato": "titolo e capitolo + testo"}


def test_metadata_invariato_se_interrotta(client):
    indice(client).indicizza(chunk(), chunking="a", lotto=5)
    with pytest.raises(ErroreRicerca):
        indice(client, embedder=EmbedderFinto(fallisci_alla_chiamata=2)).indicizza(chunk(), chunking="b", lotto=5)
    # l'ingestion interrotta non dichiara un chunking che non è stato scritto per intero
    assert client.get_collection("ricettario").config.metadata["chunking"] == "a"


# client che registra i campi passati a create_payload_index
class ClientCheContaGliIndici:
    def __init__(self, client):
        self._client = client
        self.indici: list[str] = []

    def create_payload_index(self, collection_name, field_name, field_schema, **kwargs):
        self.indici.append(field_name)
        return self._client.create_payload_index(collection_name, field_name=field_name,
                                                 field_schema=field_schema, **kwargs)

    def __getattr__(self, nome):
        return getattr(self._client, nome)


def test_indice_ricreato_su_collezione_esistente(client):
    indice(client).indicizza(chunk())
    spia = ClientCheContaGliIndici(client)
    Indice(spia, "ricettario", "bge", EmbedderFinto()).indicizza(chunk())
    # anche su una collezione che esiste già l'indice sul campo filtrato viene (ri)creato
    assert "capitolo" in spia.indici


# --- esercizio 2, B: testo indicizzato con titolo e capitolo, payload originale, collezione non ricreata ---
# alias: un nome che inizia con "test" verrebbe raccolto da pytest come test
from app.chunking import testo_indicizzato as forma_indicizzata


def test_testo_passato_all_embedder(client):
    finto = EmbedderFinto()
    lista = chunk()
    indice(client, embedder=finto).indicizza(lista, lotto=5)
    assert finto.chiamate[0] == [forma_indicizzata(c) for c in lista[:5]]
    assert finto.chiamate[0][0].startswith("Ricetta: Brodo\nCapitolo: Brodi, gelatina e sughi\n\n")


def test_payload_testo_originale(client):
    lista = chunk()
    indice(client).indicizza(lista)
    punto = client.retrieve("ricettario", [id_punto(lista[0].numero, 0)], with_payload=True)[0]
    assert punto.payload["testo"] == lista[0].testo


# client che conta le chiamate a create_collection
class ClientCheContaLeCreazioni(ClientCheContaGliIndici):
    def __init__(self, client):
        super().__init__(client)
        self.creazioni = 0

    def create_collection(self, *args, **kwargs):
        self.creazioni += 1
        return self._client.create_collection(*args, **kwargs)


def test_reingestion_senza_ricreare(client):
    prima = indice(client).indicizza(chunk(), chunking="paragrafi 1000/150")
    spia = ClientCheContaLeCreazioni(client)
    dopo = Indice(spia, "ricettario", "bge", EmbedderFinto()).indicizza(chunk(), chunking="paragrafi 1000/150")
    assert spia.creazioni == 0
    assert dopo.punti == prima.punti and dopo.orfani == 0
    assert client.get_collection("ricettario").config.metadata["testo_indicizzato"] == "titolo e capitolo + testo"
