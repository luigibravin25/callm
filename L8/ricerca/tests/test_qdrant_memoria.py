# verifica della libreria: il metadata della collezione funziona anche con Qdrant in memoria
# (la ricerca ci registra il modello di embedding; se non funzionasse servirebbe il ripiego <nome>_info)
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def test_metadata_della_collezione_in_memoria():
    # Qdrant in memoria: nessun server
    client = QdrantClient(":memory:")
    client.create_collection("prova", vectors_config=VectorParams(size=4, distance=Distance.COSINE),
                             metadata={"modello_embedding": "m", "dimensione": 4})
    # il metadata si rilegge com'era stato scritto
    assert client.get_collection("prova").config.metadata == {"modello_embedding": "m", "dimensione": 4}
