# test del server MCP della ricerca: discovery, resource, formato del risultato, top_k, filtro per capitolo.
# Il client di FastMCP parla con il server in memoria; Qdrant in memoria ed embedder finto (nessun servizio).
# librerie standard: codice asincrono, JSON
import asyncio
import json
import logging

import pytest
from fastmcp import Client
from qdrant_client import QdrantClient

from app.chunking import chunk_delle_ricette
from app.corpus import CAPITOLI, Ricetta
from app.indice import Indice
from mcp_ricerca import server
from app.errori import ErroreRicerca
from tests.finti import ChatFinta, EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")


# variabili della modalità avanzata (esercizio 3): ogni test parte dalla modalità base, con il modello di
# embedding impostato perché il server legge la configurazione a ogni chiamata
@pytest.fixture(autouse=True)
def configurazione_base(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    for nome in ("RICERCA_MODALITA", "LM_MODEL", "RICERCA_CANDIDATI", "RERANK_TETTO"):
        monkeypatch.delenv(nome, raising=False)


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
    assert set(r) == {"modalita", "query", "query_usate", "ripieghi", "top_k", "capitolo", "nota", "passaggi"}
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
    r = cerca(query="brodo", top_k="3")
    # convertito davvero a 3, non solo «al massimo 3 passaggi»
    assert r["top_k"] == 3 and len(r["passaggi"]) <= 3


def test_filtro_capitolo():
    r = cerca(query="brodo", capitolo=" brodi, gelatina e sughi ")
    assert r["capitolo"] == "BRODI, GELATINA E SUGHI"
    assert r["passaggi"] and {p["capitolo"] for p in r["passaggi"]} == {"BRODI, GELATINA E SUGHI"}


def test_capitolo_solo_spazi():
    # solo spazi = nessun filtro, come la stringa vuota (non un capitolo sconosciuto)
    r = cerca(query="brodo", capitolo="   ")
    assert r["capitolo"] == "" and r["passaggi"]


# --- lezione 8, esercizio 3: modalità avanzata ---

# Verifica che argomenti e descrizione del tool siano gli stessi in tutte le modalità.
@pytest.mark.parametrize("modalita", ["base", "riscrittura", "reranking", "entrambe"])
def test_schema_identico_in_tutte_le_modalita(monkeypatch, modalita):
    monkeypatch.setenv("RICERCA_MODALITA", modalita)
    monkeypatch.setenv("LM_MODEL", "gemma")
    tool = con_client(lambda c: c.list_tools())[0]
    assert tool.inputSchema["required"] == ["query"]
    assert set(tool.inputSchema["properties"]) == {"query", "top_k", "capitolo"}
    assert tool.description == server.DESCRIZIONE_TOOL


# Verifica la modalità base senza LM_MODEL: sola domanda, nessun ripiego.
def test_base_senza_lm_model():
    risultato = cerca(query="brodo", top_k=3)
    assert risultato["modalita"] == "base" and risultato["query_usate"] == ["brodo"] and risultato["ripieghi"] == []
    assert len(risultato["passaggi"]) == 3


# Verifica modalità e query usate nel risultato in entrambe.
def test_entrambe_nel_risultato(monkeypatch):
    monkeypatch.setenv("RICERCA_MODALITA", "entrambe")
    monkeypatch.setenv("LM_MODEL", "gemma")
    monkeypatch.setattr(server, "crea_chat", lambda conf: ChatFinta(['{"query": ["sugo"]}', '{"id": ["R3-1"]}']))
    risultato = cerca(query="brodo")
    assert risultato["modalita"] == "entrambe" and risultato["query_usate"] == ["brodo", "sugo"]
    assert [p["id"] for p in risultato["passaggi"]] == ["R3-1"]


# Verifica il ripiego segnalato nel risultato e nella riga di log, senza errore verso il client.
def test_ripiego_nel_risultato_e_nel_log(monkeypatch, caplog):
    monkeypatch.setenv("RICERCA_MODALITA", "reranking")
    monkeypatch.setenv("LM_MODEL", "gemma")
    monkeypatch.setattr(server, "crea_chat", lambda conf: ChatFinta([ErroreRicerca("spenta")]))
    with caplog.at_level(logging.INFO, logger="mcp_ricerca"):
        risultato = cerca(query="brodo", top_k=2)
    assert risultato["ripieghi"] == ["reranking: errore della chiamata → ordine vettoriale"]
    assert len(risultato["passaggi"]) == 2
    riga = [r.getMessage() for r in caplog.records if r.name == "mcp_ricerca"][-1]
    assert "modalita=reranking" in riga and "llm=1" in riga and "ripieghi=[reranking: errore" in riga


# Verifica che il reranking possa escludere tutti i passaggi (lista vuota, nessun ripiego).
def test_lista_vuota_dal_reranking(monkeypatch):
    monkeypatch.setenv("RICERCA_MODALITA", "reranking")
    monkeypatch.setenv("LM_MODEL", "gemma")
    monkeypatch.setattr(server, "crea_chat", lambda conf: ChatFinta(['{"id": []}']))
    risultato = cerca(query="tiramisù")
    assert risultato["passaggi"] == [] and risultato["ripieghi"] == []


# Verifica gli id scartati nella riga di log.
def test_id_scartati_nel_log(monkeypatch, caplog):
    monkeypatch.setenv("RICERCA_MODALITA", "reranking")
    monkeypatch.setenv("LM_MODEL", "gemma")
    monkeypatch.setattr(server, "crea_chat", lambda conf: ChatFinta(['{"id": ["R1-1", "R99-1"]}']))
    with caplog.at_level(logging.INFO, logger="mcp_ricerca"):
        cerca(query="brodo")
    riga = [r.getMessage() for r in caplog.records if r.name == "mcp_ricerca"][-1]
    assert "scartati=1" in riga


# Verifica che crea_chat non crei un modello in base e lo crei con la configurazione negli altri casi.
def test_crea_chat(monkeypatch):
    from app.config import carica_configurazione
    assert server.crea_chat(carica_configurazione()) is None
    monkeypatch.setenv("RICERCA_MODALITA", "riscrittura")
    monkeypatch.setenv("LM_MODEL", "gemma")
    chat = server.crea_chat(carica_configurazione())
    assert chat.modello == "gemma" and chat.base_url == "http://127.0.0.1:1234/v1"
