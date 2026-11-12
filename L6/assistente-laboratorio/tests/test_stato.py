# test dei controlli dello stato (GET /stato): LM Studio e server MCP, dal vivo ma simulati
import httpx

from app.adattatore_mcp import ErroreMCP
from app.agente import Agente
from app.stato import verifica_mcp, verifica_modello

URL = "http://127.0.0.1:1234/v1"
MODELLO = "google/gemma-4-e2b"


# client httpx con un LM Studio finto che risponde con la funzione data
def _client(gestore):
    return httpx.Client(transport=httpx.MockTransport(gestore))


# Verifica: LM Studio risponde e il modello e' tra quelli disponibili.
def test_modello_ok():
    richieste = []

    def gestore(r):
        richieste.append(str(r.url))
        return httpx.Response(200, json={"data": [{"id": MODELLO}, {"id": "altro"}]})
    stato = verifica_modello(URL, MODELLO, _client(gestore))
    assert (stato.stato, stato.nome) == ("ok", MODELLO)
    assert richieste == [URL + "/models"]


# Verifica: LM Studio risponde ma il modello non c'e' (elenco nel messaggio).
def test_modello_assente():
    stato = verifica_modello(URL, MODELLO, _client(
        lambda r: httpx.Response(200, json={"data": [{"id": "qwen"}]})))
    assert stato.stato == "modello_assente"
    assert MODELLO in stato.messaggio and "qwen" in stato.messaggio


# Verifica: LM Studio spento.
def test_modello_non_raggiungibile():
    def gestore(r):
        raise httpx.ConnectError("rifiutata")
    stato = verifica_modello(URL, MODELLO, _client(gestore))
    assert stato.stato == "non_raggiungibile" and URL in stato.messaggio


# Verifica: LM Studio risponde con un errore HTTP.
def test_modello_errore_http():
    stato = verifica_modello(URL, MODELLO, _client(lambda r: httpx.Response(500)))
    assert stato.stato == "non_raggiungibile" and "500" in stato.messaggio


# Verifica: server non partito all'avvio, nessun nuovo tentativo.
def test_mcp_non_partito():
    chiamate = []
    stato = verifica_mcp(False, lambda: chiamate.append(1))
    assert stato.stato == "non_disponibile" and "riavviare" in stato.messaggio
    assert chiamate == []


# Verifica: server partito e ancora raggiungibile, poi rotto dopo l'avvio.
def test_mcp_ok_e_rotto():
    assert verifica_mcp(True, lambda: ["tooltime"]).stato == "ok"

    def rotto():
        raise ErroreMCP("Connection closed")
    stato = verifica_mcp(True, rotto)
    assert stato.stato == "non_disponibile" and "Connection closed" in stato.messaggio


# Verifica che Agente.stato unisca i due controlli con strumenti e numero di prompt.
def test_stato_dell_agente():
    from app.schemi import StatoMCP, StatoModello
    agente = Agente(grafo=None, prompts=[1, 2], mcp_partito=True, strumenti=("tooltime",),
                    motivo_mcp="",
                    verifica_modello=lambda: StatoModello(stato="ok", nome=MODELLO),
                    verifica_mcp=lambda: StatoMCP(stato="ok"))
    stato = agente.stato()
    assert stato.agente == "ok"
    assert (stato.mcp.strumenti, stato.mcp.prompt) == (["tooltime"], 2)
    assert stato.modello.nome == MODELLO
