# test del server MCP della ricerca: discovery, resource, formato del risultato, top_k, filtro per capitolo.
# Il client di FastMCP parla con il server in memoria; Qdrant in memoria ed embedder finto (nessun servizio).
# librerie standard: codice asincrono, JSON
import asyncio
import json

import pytest
from fastmcp import Client
from qdrant_client import QdrantClient

from app.chunking import chunk_delle_ricette
from app.corpus import CAPITOLI, Ricetta
from app.indice import Indice
from mcp_ricerca import server
from tests.finti import EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")


# testo di prova diverso per ogni ricetta, lungo circa `caratteri`
def parole_di(numero: int, caratteri: int) -> str:
    return " ".join(f"parola{numero}x{i}" for i in range(caratteri // 12))


# quattro ricette di due capitoli; la 2 è lunga (chunk di ~1000 caratteri, da troncare a 800)
RICETTE = [
    Ricetta(1, "Brodo", "BRODI, GELATINA E SUGHI", parole_di(1, 300)),
    Ricetta(2, "Sugo", "BRODI, GELATINA E SUGHI", parole_di(2, 2500)),
    Ricetta(3, "Cappelletti", "MINESTRE IN BRODO", parole_di(3, 400)),
    Ricetta(4, "Tortellini", "MINESTRE IN BRODO", parole_di(4, 400)),
]


@pytest.fixture(autouse=True)
def indice_in_memoria(monkeypatch):
    # collezione in memoria scritta come dall'ingestion; il server la usa al posto di quella vera
    ix = Indice(QdrantClient(":memory:"), "ricettario", "bge", EmbedderFinto())
    ix.indicizza(chunk_delle_ricette(RICETTE, "paragrafi", 1000, 150), chunking="paragrafi 1000/150")
    monkeypatch.setattr(server, "crea_indice", lambda: ix)
    return ix


# esegue una funzione asincrona che riceve il client collegato al server in memoria
def con_client(azione):
    async def corpo():
        async with Client(server.mcp) as client:
            return await azione(client)
    return asyncio.run(corpo())


# chiama il tool e restituisce il risultato strutturato
def cerca(**argomenti) -> dict:
    return con_client(lambda c: c.call_tool("search_documents", argomenti)).structured_content


def test_discovery():
    tool = con_client(lambda c: c.list_tools())
    assert [t.name for t in tool] == ["search_documents"]
    schema = tool[0].inputSchema
    assert schema["required"] == ["query"]
    assert schema["properties"]["top_k"]["type"] == "integer" and schema["properties"]["top_k"]["default"] == 5
    assert schema["properties"]["capitolo"]["type"] == "string" and schema["properties"]["capitolo"]["default"] == ""
    # nessun anyOf: il template di gemma in LM Studio non lo accetta
    assert "anyOf" not in json.dumps(schema)
    assert "[R89-1]" in tool[0].description
    assert "passaggi" in json.dumps(tool[0].outputSchema)


def test_resource_capitoli():
    risorse = con_client(lambda c: c.list_resources())
    assert [(str(r.uri), r.mimeType) for r in risorse] == [("ricettario://capitoli", "application/json")]
    contenuto = con_client(lambda c: c.read_resource("ricettario://capitoli"))
    assert json.loads(contenuto[0].text) == list(CAPITOLI)


def test_formato_del_risultato():
    r = cerca(query="brodo di carne")
    assert set(r) == {"modalita", "query", "top_k", "capitolo", "nota", "passaggi"}
    assert (r["modalita"], r["query"], r["top_k"], r["capitolo"], r["nota"]) == ("base", "brodo di carne", 5, "", None)
    p = r["passaggi"][0]
    assert set(p) == {"id", "ricetta", "titolo", "capitolo", "posizione", "score", "testo", "troncato"}
    numero, chunk = p["id"][1:].split("-")
    assert int(numero) == p["ricetta"] and p["posizione"].startswith(f"chunk {chunk} di ")


def test_id_stabili():
    assert [p["id"] for p in cerca(query="sugo")["passaggi"]] == [p["id"] for p in cerca(query="sugo")["passaggi"]]


def test_troncamento_nel_risultato():
    passaggi = cerca(query="sugo", top_k=10)["passaggi"]
    lunghi = [p for p in passaggi if p["troncato"]]
    assert lunghi and all(len(p["testo"]) <= 800 for p in passaggi)


def test_top_k_ridotto():
    r = cerca(query="brodo", top_k=25)
    assert r["top_k"] == 10 and len(r["passaggi"]) <= 10
    assert "ridotto a 10" in r["nota"]


def test_top_k_come_stringa():
    # il modello può mandare il numero come testo: FastMCP lo converte
    assert len(cerca(query="brodo", top_k="3")["passaggi"]) <= 3


def test_filtro_capitolo():
    r = cerca(query="brodo", capitolo=" brodi, gelatina e sughi ")
    assert r["capitolo"] == "BRODI, GELATINA E SUGHI"
    assert r["passaggi"] and {p["capitolo"] for p in r["passaggi"]} == {"BRODI, GELATINA E SUGHI"}
