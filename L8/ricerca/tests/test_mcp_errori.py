# test degli errori del tool search_documents e della riga di log per chiamata.
# Client FastMCP in memoria, Qdrant in memoria o finto, embedder finto (nessun servizio).
# librerie standard: codice asincrono, log
import asyncio
import logging

import pytest
from fastmcp import Client
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException

from app.chunking import chunk_delle_ricette
from app.corpus import Ricetta
from app.indice import Indice
from mcp_ricerca import server
from tests.finti import EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa)
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")

# due ricette brevi di due capitoli: bastano per una ricerca riuscita
RICETTE = [
    Ricetta(1, "Brodo", "BRODI, GELATINA E SUGHI", "brodo di carne con lesso e ossa " * 5),
    Ricetta(2, "Cappelletti", "MINESTRE IN BRODO", "cappelletti all'uso di Romagna " * 5),
]


# client Qdrant in memoria con la collezione scritta come dall'ingestion (modello "bge")
def client_con_collezione() -> QdrantClient:
    client = QdrantClient(":memory:")
    ix = Indice(client, "ricettario", "bge", EmbedderFinto())
    ix.indicizza(chunk_delle_ricette(RICETTE, "paragrafi", 1000, 150), chunking="paragrafi 1000/150")
    return client


# client Qdrant finto che non risponde: ogni metodo solleva l'errore di connessione del client vero
class QdrantIrraggiungibile:
    def __getattr__(self, nome):
        def fallisce(*args, **kwargs):
            raise ResponseHandlingException(ConnectionError("connessione rifiutata"))
        return fallisce


# sostituisce crea_indice del server con una funzione che restituisce l'indice dato
def usa_indice(monkeypatch, indice: Indice) -> None:
    monkeypatch.setattr(server, "crea_indice", lambda: indice)


# chiama il tool e restituisce il messaggio dell'errore ricevuto dal client
def errore_di(**argomenti) -> str:
    async def corpo():
        async with Client(server.mcp) as client:
            await client.call_tool("search_documents", argomenti)
    with pytest.raises(Exception) as info:
        asyncio.run(corpo())
    return str(info.value)


# chiama il tool e restituisce il risultato strutturato (chiamata riuscita)
def cerca(**argomenti) -> dict:
    async def corpo():
        async with Client(server.mcp) as client:
            return (await client.call_tool("search_documents", argomenti)).structured_content
    return asyncio.run(corpo())


@pytest.fixture
def indice_valido(monkeypatch):
    # indice in memoria con lo stesso modello della collezione
    usa_indice(monkeypatch, Indice(client_con_collezione(), "ricettario", "bge", EmbedderFinto()))


def test_query_vuota(indice_valido):
    assert "la domanda è vuota" in errore_di(query="  ")


def test_top_k_zero(indice_valido):
    assert "top_k=0 non valido" in errore_di(query="brodo", top_k=0)


def test_capitolo_sconosciuto(indice_valido):
    messaggio = errore_di(query="brodo", capitolo="DOLCI")
    assert "'DOLCI' sconosciuto" in messaggio and "PASTICCERIA" in messaggio


def test_collezione_assente(monkeypatch):
    usa_indice(monkeypatch, Indice(QdrantClient(":memory:"), "ricettario", "bge", EmbedderFinto()))
    assert "ingestion" in errore_di(query="brodo")


def test_modello_diverso(monkeypatch):
    usa_indice(monkeypatch, Indice(client_con_collezione(), "ricettario", "altro", EmbedderFinto()))
    assert "usa il modello" in errore_di(query="brodo")


def test_embedder_che_fallisce(monkeypatch):
    usa_indice(monkeypatch, Indice(client_con_collezione(), "ricettario", "bge",
                                   EmbedderFinto(fallisci_alla_chiamata=1)))
    assert "LM Studio non risponde" in errore_di(query="brodo")


def test_qdrant_irraggiungibile(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6399")
    usa_indice(monkeypatch, Indice(QdrantIrraggiungibile(), "ricettario", "bge", EmbedderFinto()))
    messaggio = errore_di(query="brodo")
    assert "Qdrant non raggiungibile" in messaggio and "QDRANT_URL=http://127.0.0.1:6399" in messaggio


def test_embedding_model_mancante(monkeypatch):
    # crea_indice vera: la configurazione fallisce prima di collegarsi a qualunque servizio
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert "EMBEDDING_MODEL" in errore_di(query="brodo")


# crea_indice che fallisce con un errore non previsto (dettaglio interno da non mostrare)
def indice_rotto():
    raise ValueError("segreto interno")


def test_errore_inatteso_mascherato(monkeypatch):
    monkeypatch.setattr(server, "crea_indice", indice_rotto)
    messaggio = errore_di(query="brodo")
    assert "segreto" not in messaggio and "search_documents" in messaggio


def test_log_una_riga_per_chiamata(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="mcp_ricerca")
    usa_indice(monkeypatch, Indice(client_con_collezione(), "ricettario", "bge", EmbedderFinto()))
    cerca(query="brodo", top_k=3)
    errore_di(query="")
    monkeypatch.setattr(server, "crea_indice", indice_rotto)
    errore_di(query="brodo")
    righe = [r.getMessage() for r in caplog.records if r.name == "mcp_ricerca"]
    assert len(righe) == 3
    assert 'query="brodo" top_k=3 capitolo=- → 2 passaggi (R' in righe[0] and righe[0].endswith("s")
    assert righe[1] == 'query="" top_k=5 capitolo=- → errore: la domanda è vuota'
    assert righe[2].endswith("→ errore inatteso: ValueError: segreto interno")
    assert "Traceback" not in caplog.text


def test_query_lunga_troncata_nel_log(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="mcp_ricerca")
    usa_indice(monkeypatch, Indice(client_con_collezione(), "ricettario", "bge", EmbedderFinto()))
    cerca(query="a" * 200)
    riga = [r.getMessage() for r in caplog.records if r.name == "mcp_ricerca"][0]
    assert f'query="{"a" * 80}…"' in riga


def test_logger_fastmcp_silenziato():
    assert logging.getLogger("fastmcp").level == logging.CRITICAL


def test_log_del_server_senza_rumore(monkeypatch):
    # in stdio: niente banner di FastMCP e niente righe «Processing request …» della libreria mcp
    avvii = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: avvii.append(kwargs))
    server.main()
    assert avvii == [{"show_banner": False}]
    assert not logging.getLogger("mcp.server.lowlevel.server").isEnabledFor(logging.INFO)
    assert logging.getLogger("mcp_ricerca").isEnabledFor(logging.INFO)
