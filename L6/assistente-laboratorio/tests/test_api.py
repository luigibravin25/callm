# test del servizio HTTP dell'agente (step 6): grafo vero con modelli finti, nessun LM Studio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from openai import (APIConnectionError, APIStatusError, APITimeoutError,
                    LengthFinishReasonError)

from app import adattatore_mcp
from app.adattatore_mcp import ErroreMCP, PromptNonValido
from app.agente import Agente
from app.api import crea_app
from app.config import Ambito
from app.graph import build_graph
from app.info_prompt import InfoArgomento, InfoPrompt
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from app.schemi import StatoMCP, StatoModello
from mcp_assistente import orologio as modulo_orologio
from tests.finti import ModelloFinto, RevisoreFinto, RiassuntoFinto, RouterFinto, tooltime_finto

AMBITO = Ambito(descrizione="Solo ora.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="ora", argomento="ora_data_fusi")
OK = DecisioneRevisore(motivo="risponde", coerente=True)
SPIEGA = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                          InfoArgomento("livello", False)))
RICHIESTA = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")


# orologio fisso: 1 marzo 2026 11:00 UTC
@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    monkeypatch.setattr(modulo_orologio, "_adesso",
                        lambda: datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc))


# modello che solleva l'errore dato (LM Studio spento, errore HTTP, ...)
class ModelloCheSolleva:
    def __init__(self, errore):
        self.errore = errore

    def bind_tools(self, strumenti):
        return self

    def invoke(self, messaggi):
        raise self.errore


# modello che risponde con i testi dell'utente che vede (per controllare la cronologia ricevuta)
class ModelloEco:
    def bind_tools(self, strumenti):
        return self

    def invoke(self, messaggi):
        return AIMessage("eco: " + " | ".join(str(m.content) for m in messaggi
                                               if isinstance(m, HumanMessage)))


# agente con il grafo vero, modelli finti e controlli dello stato finti
def _agente(modello, partito=True, modello_ok=True, mcp_ok=True):
    grafo = build_graph(modello, RouterFinto([IN_AMBITO]), RevisoreFinto([OK]),
                        RiassuntoFinto(["riassunto"]), AMBITO,
                        strumenti=[tooltime_finto([])] if partito else ())
    stato_modello = StatoModello(stato="ok" if modello_ok else "modello_assente",
                                 nome="google/gemma-4-e2b",
                                 messaggio="" if modello_ok else "non caricato")
    stato_mcp = StatoMCP(stato="ok" if mcp_ok else "non_disponibile",
                         messaggio="" if mcp_ok else "Connection closed")
    return Agente(grafo=grafo, prompts=[SPIEGA] if partito else [], mcp_partito=partito,
                  strumenti=("tooltime",) if partito else (), motivo_mcp="",
                  verifica_modello=lambda: stato_modello, verifica_mcp=lambda: stato_mcp)


# client HTTP di prova: lifespan eseguito, eccezioni del server trasformate in risposte 500
@pytest.fixture
def client_per():
    aperti = []

    def crea(agente):
        c = TestClient(crea_app(lambda: agente), raise_server_exceptions=False)
        c.__enter__()
        aperti.append(c)
        return c
    yield crea
    for c in aperti:
        c.__exit__(None, None, None)


# risposte del modello per una domanda con tooltime
def _con_tooltime():
    return ModelloFinto([AIMessage("", tool_calls=[{"name": "tooltime", "id": "c1",
                                                    "args": {"fuso": "Asia/Tokyo"}}]),
                         AIMessage("A Tokyo sono le 20")])


# Verifica una chat con tooltime: risposta, strumenti, categoria, argomento, cronologia OpenAI.
def test_chat_con_strumento(client_per):
    r = client_per(_agente(_con_tooltime())).post("/chat", json={"messaggio": "Che ore sono a Tokyo?"})
    assert r.status_code == 200
    dati = r.json()
    assert dati["risposta"] == "A Tokyo sono le 20"
    assert dati["strumenti_usati"] == [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]
    assert (dati["categoria"], dati["argomento"], dati["riassunto"]) == \
        ("conversazione", "ora_data_fusi", "")
    assert [m["role"] for m in dati["cronologia"]] == ["user", "assistant", "tool", "assistant"]
    assert dati["cronologia"][1]["tool_calls"][0]["function"]["name"] == "tooltime"


# Verifica (Review 1) che la cronologia restituita, rimandata con una nuova domanda, sia accettata
# e arrivi intera al modello.
def test_cronologia_restituita_si_rimanda(client_per):
    c = client_per(_agente(_con_tooltime()))
    primo = c.post("/chat", json={"messaggio": "Che ore sono a Tokyo?"}).json()
    modello = ModelloFinto([AIMessage("Prego")])
    c2 = client_per(_agente(modello))
    r = c2.post("/chat", json={"messaggio": "Grazie", "cronologia": primo["cronologia"],
                               "riassunto": primo["riassunto"]})
    assert r.status_code == 200
    visti = modello.chiamate[-1][1:]  # senza il SystemMessage
    assert [type(m).__name__ for m in visti] == ["HumanMessage", "AIMessage", "ToolMessage",
                                                 "AIMessage", "HumanMessage"]


# Verifica un prompt valido: prompts/get con nome e argomenti, poi il turno.
def test_chat_con_prompt(client_per, monkeypatch):
    chiamate = []

    def ottieni(nome, argomenti):
        chiamate.append((nome, argomenti))
        return [HumanMessage("Spiegami MCP.")]
    monkeypatch.setattr(adattatore_mcp, "ottieni_prompt", ottieni)
    r = client_per(_agente(ModelloEco())).post(
        "/chat", json={"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP"}}})
    assert r.status_code == 200 and r.json()["risposta"] == "eco: Spiegami MCP."
    assert chiamate == [("spiega", {"argomento": "MCP"})]


# Verifica gli errori dei prompt: rifiutato (422) e server non disponibile (503).
@pytest.mark.parametrize("errore,codice,nome", [
    (PromptNonValido("livello non valido"), 422, "prompt_non_valido"),
    (ErroreMCP("Connection closed"), 503, "mcp_non_disponibile"),
])
def test_errori_dei_prompt(client_per, monkeypatch, errore, codice, nome):
    def ottieni(nome_, argomenti):
        raise errore
    monkeypatch.setattr(adattatore_mcp, "ottieni_prompt", ottieni)
    r = client_per(_agente(ModelloEco())).post(
        "/chat", json={"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP"}}})
    assert r.status_code == codice
    assert r.json() == {"errore": nome, "messaggio": str(errore)}


# Verifica il prompt con il server non partito all'avvio: 503 senza chiamare prompts/get.
def test_prompt_server_non_partito(client_per):
    r = client_per(_agente(ModelloEco(), partito=False)).post(
        "/chat", json={"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP"}}})
    assert r.status_code == 503 and r.json()["errore"] == "mcp_non_disponibile"


# Verifica la validazione: 422 richiesta_non_valida, messaggio in italiano senza "body".
@pytest.mark.parametrize("corpo,testo", [
    ({}, "serve messaggio oppure prompt"),
    ({"messaggio": "a", "prompt": {"nome": "spiega"}}, "insieme"),
    ({"messaggio": "  "}, "messaggio vuoto"),
    ({"messaggio": "a", "cronologia": [{"role": "capo", "content": "x"}]}, "cronologia.0.role"),
    ({"messaggio": "a", "cronologia": "x"}, "cronologia"),
    ({"prompt": {"nome": "spiega", "argomenti": {"a": 1}}}, "prompt.argomenti.a"),
])
def test_validazione(client_per, corpo, testo):
    r = client_per(_agente(ModelloEco())).post("/chat", json=corpo)
    assert r.status_code == 422
    dati = r.json()
    assert dati["errore"] == "richiesta_non_valida"
    assert testo in dati["messaggio"] and "body" not in dati["messaggio"]


# Verifica un corpo che non e' JSON: 422 comprensibile.
def test_corpo_non_json(client_per):
    r = client_per(_agente(ModelloEco())).post(
        "/chat", content="non json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["errore"] == "richiesta_non_valida"


# Verifica la mappa degli errori del modello (codice, errore, parte del messaggio).
@pytest.mark.parametrize("errore,codice,nome,testo", [
    (APIConnectionError(request=RICHIESTA), 503, "modello_non_raggiungibile", "LM Studio"),
    (APITimeoutError(request=RICHIESTA), 504, "modello_in_timeout", "tempo"),
    (APIStatusError("bad", response=httpx.Response(400, request=RICHIESTA), body=None), 502,
     "errore_del_modello", "Context Length"),
    (APIStatusError("nf", response=httpx.Response(404, request=RICHIESTA), body=None), 502,
     "errore_del_modello", "LM_MODEL"),
    (LengthFinishReasonError(completion=SimpleNamespace(usage=None)), 502, "errore_del_modello",
     "token"),
])
def test_errori_del_modello(client_per, errore, codice, nome, testo):
    r = client_per(_agente(ModelloCheSolleva(errore))).post("/chat", json={"messaggio": "Ciao"})
    assert r.status_code == codice
    assert r.json()["errore"] == nome and testo in r.json()["messaggio"]


# Verifica un errore imprevisto: 500 senza dettagli interni nel corpo.
def test_errore_interno(client_per):
    r = client_per(_agente(ModelloCheSolleva(RuntimeError("segreto")))).post(
        "/chat", json={"messaggio": "Ciao"})
    assert r.status_code == 500
    assert r.json()["errore"] == "errore_interno" and "segreto" not in r.text


# Verifica (Review 3) due richieste in parallelo con cronologie diverse: nessuna contaminazione.
def test_richieste_in_parallelo(client_per):
    c = client_per(_agente(ModelloEco()))

    def chiedi(nome):
        cronologia = [{"role": "user", "content": f"Mi chiamo {nome}"},
                      {"role": "assistant", "content": "Piacere"}]
        return c.post("/chat", json={"messaggio": "Come mi chiamo?",
                                     "cronologia": cronologia}).json()["risposta"]
    with ThreadPoolExecutor(2) as pool:
        anna, bruno = pool.map(chiedi, ["Anna", "Bruno"])
    assert "Anna" in anna and "Bruno" not in anna
    assert "Bruno" in bruno and "Anna" not in bruno


# Verifica (Review 5) accenti ed emoji in andata e ritorno.
def test_accenti_ed_emoji(client_per):
    r = client_per(_agente(ModelloEco())).post("/chat", json={"messaggio": "Perché? 🕐"})
    assert r.json()["risposta"] == "eco: Perché? 🕐"
    assert r.json()["cronologia"][0]["content"] == "Perché? 🕐"


# Verifica GET /prompts con l'elenco letto all'avvio.
def test_prompts(client_per):
    r = client_per(_agente(ModelloEco())).get("/prompts")
    assert r.status_code == 200
    assert r.json() == [{"nome": "spiega", "descrizione": "Spiega.",
                         "argomenti": [{"nome": "argomento", "obbligatorio": True},
                                       {"nome": "livello", "obbligatorio": False}]}]


# Verifica GET /stato: 200 con tutto ok, 503 con modello o MCP non pronti, corpo completo.
@pytest.mark.parametrize("modello_ok,mcp_ok,codice", [
    (True, True, 200), (False, True, 503), (True, False, 503),
])
def test_stato(client_per, modello_ok, mcp_ok, codice):
    r = client_per(_agente(ModelloEco(), modello_ok=modello_ok, mcp_ok=mcp_ok)).get("/stato")
    assert r.status_code == codice
    dati = r.json()
    assert dati["agente"] == "ok"
    assert dati["mcp"]["strumenti"] == ["tooltime"] and dati["mcp"]["prompt"] == 1
    assert dati["modello"]["nome"] == "google/gemma-4-e2b"


# Verifica la documentazione OpenAPI: tre percorsi, schema Errore, pagina /docs.
def test_openapi_e_docs(client_per):
    c = client_per(_agente(ModelloEco()))
    schema = c.get("/openapi.json").json()
    assert {"/chat", "/prompts", "/stato"} <= set(schema["paths"])
    assert "Errore" in schema["components"]["schemas"]
    assert "503" in schema["paths"]["/chat"]["post"]["responses"]
    assert c.get("/docs").status_code == 200


# Verifica l'avvio con una porta non valida: errore chiaro prima di uvicorn.
def test_main_porta_non_valida(monkeypatch):
    import uvicorn
    from app import api
    chiamate = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: chiamate.append(1))
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "google/gemma-4-e2b")
    monkeypatch.setenv("AGENTE_PORTA", "abc")
    with pytest.raises(SystemExit, match="AGENTE_PORTA"):
        api.main()
    assert chiamate == []


# --- test spostati dalla CLI (step 6): il giro tra i turni ora passa dall'API ---

# Verifica che dopo un rifiuto del revisore la cronologia restituita non contenga il messaggio
# [Revisore] ne' la bozza, e che il turno dopo non li riceva.
def test_turno_successivo_senza_revisore(client_per):
    no = DecisioneRevisore(motivo="parziale", coerente=False)
    modello = ModelloFinto([AIMessage("bozza"), AIMessage("completa"), AIMessage("prego")])
    grafo = build_graph(modello, RouterFinto([IN_AMBITO]), RevisoreFinto([no, OK, OK]),
                        RiassuntoFinto(["r"]), AMBITO)
    c = client_per(Agente(grafo=grafo, prompts=[], mcp_partito=True, strumenti=(),
                          motivo_mcp=""))
    primo = c.post("/chat", json={"messaggio": "domanda"}).json()
    assert primo["risposta"] == "completa"
    assert "bozza" not in str(primo["cronologia"]) and "[Revisore]" not in str(primo["cronologia"])
    c.post("/chat", json={"messaggio": "grazie", "cronologia": primo["cronologia"]})
    assert "bozza" not in [m.content for m in modello.chiamate[2]]


# Verifica che il riassunto restituito, rimandato, arrivi all'agente nel turno dopo.
def test_riassunto_passato_al_turno_successivo(client_per):
    modello = ModelloFinto([AIMessage("r1"), AIMessage("r2"), AIMessage("r3"), AIMessage("r4")])
    grafo = build_graph(modello, RouterFinto([IN_AMBITO]), RevisoreFinto([OK]),
                        RiassuntoFinto(["Si chiama Luigi."]), AMBITO, soglia_riassunto=3,
                        messaggi_recenti=1)
    c = client_per(Agente(grafo=grafo, prompts=[], mcp_partito=True, strumenti=(),
                          motivo_mcp=""))
    cronologia, riassunto = [], ""
    for domanda in ["Mi chiamo Luigi", "d2", "d3", "d4"]:
        dati = c.post("/chat", json={"messaggio": domanda, "cronologia": cronologia,
                                     "riassunto": riassunto}).json()
        cronologia, riassunto = dati["cronologia"], dati["riassunto"]
    assert "Riassunto della conversazione precedente: Si chiama Luigi." in \
        modello.chiamate[3][0].content
