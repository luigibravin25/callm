# test del servizio HTTP dell'agente (step 6): grafo vero con modelli finti, nessun LM Studio
import json
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
from app.schemi import RichiestaChat, StatoMCP, StatoModello
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
    ({"messaggio": "a", "cronologia": [{"role": "capo", "content": "x"}]},
     "campo cronologia[0].role: valore non ammesso (ammessi: user, assistant o tool)"),
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


# Verifica l'avvio valido: host e porta da ambiente, log del grafo e del servizio accesi, uvicorn
# chiamato una volta (senza avviarlo davvero).
def test_main_avvia_uvicorn_con_i_log(monkeypatch):
    import logging
    import uvicorn
    from app import api
    chiamate = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: chiamate.append(k))
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_MODEL", "google/gemma-4-e2b")
    monkeypatch.setenv("AGENTE_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENTE_PORTA", "8123")
    api.main()
    assert chiamate == [{"host": "0.0.0.0", "port": 8123, "log_config": None}]
    for nome in ("api", "router", "agente", "mcp", "preferenze"):
        assert logging.getLogger(nome).level == logging.INFO



# --- correzioni della revisione finale ---

# Verifica (I-2) che anche 404, 405 e un corpo non UTF-8 abbiano il corpo {errore, messaggio}.
@pytest.mark.parametrize("metodo,percorso,opzioni,codice,errore", [
    ("GET", "/nonesiste", {}, 404, "percorso_non_trovato"),
    ("GET", "/chat", {}, 405, "metodo_non_ammesso"),
    ("POST", "/chat", {"content": bytes([0xFF, 0xFE]), "headers": {"Content-Type": "application/json"}},
     None, "richiesta_non_valida"),
])
def test_errori_http_con_corpo_uniforme(client_per, metodo, percorso, opzioni, codice, errore):
    r = client_per(_agente(ModelloEco())).request(metodo, percorso, **opzioni)
    if codice is not None:
        assert r.status_code == codice
    dati = r.json()
    assert set(dati) == {"errore", "messaggio"} and dati["errore"] == errore
    assert "Not Found" not in dati["messaggio"] and "Method" not in dati["messaggio"]


# Verifica (M-1) che la cronologia restituita non abbia campi null (formato OpenAI canonico).
def test_cronologia_senza_campi_null(client_per):
    dati = client_per(_agente(_con_tooltime())).post(
        "/chat", json={"messaggio": "Che ore sono a Tokyo?"}).json()
    assert dati["cronologia"][0] == {"role": "user", "content": "Che ore sono a Tokyo?"}
    assert "null" not in json.dumps(dati["cronologia"])


# Verifica (M-3) che un role "system" dia il messaggio dedicato e non un elenco che lo ammette.
def test_role_system_messaggio_dedicato(client_per):
    r = client_per(_agente(ModelloEco())).post(
        "/chat", json={"messaggio": "a", "cronologia": [{"role": "system", "content": "x"}]})
    assert r.status_code == 422
    assert "messaggi di sistema non ammessi" in r.json()["messaggio"]


# Verifica (minore 1 dello step 6) l'andata e ritorno: la cronologia restituita dopo turni con
# strumento (stesso id riusato), revisione e riassunto passa la validazione e si puo' ripassare.
def test_cronologia_restituita_si_puo_ripassare(client_per):
    no = DecisioneRevisore(motivo="parziale", coerente=False)
    chiamata = AIMessage("", tool_calls=[{"name": "tooltime", "id": "c1",
                                          "args": {"fuso": "Asia/Tokyo"}}])
    modello = ModelloFinto([chiamata, AIMessage("bozza"), AIMessage("completa"),
                            chiamata, AIMessage("r2"), chiamata, AIMessage("r3")])
    grafo = build_graph(modello, RouterFinto([IN_AMBITO]), RevisoreFinto([no, OK]),
                        RiassuntoFinto(["Riassunto."]), AMBITO, soglia_riassunto=4,
                        messaggi_recenti=1, strumenti=[tooltime_finto([])])
    c = client_per(Agente(grafo=grafo, prompts=[], mcp_partito=True, strumenti=("tooltime",),
                          motivo_mcp=""))
    cronologia, riassunto = [], ""
    for domanda in ["Ore a Tokyo?", "E adesso?", "E ancora?"]:
        r = c.post("/chat", json={"messaggio": domanda, "cronologia": cronologia,
                                  "riassunto": riassunto})
        assert r.status_code == 200, r.json()
        cronologia, riassunto = r.json()["cronologia"], r.json()["riassunto"]
    assert riassunto == "Riassunto."
    RichiestaChat.model_validate({"messaggio": "x", "cronologia": cronologia,
                                  "riassunto": riassunto})


# ---------- step 10: POST /chat/stream ----------

# eventi SSE di un corpo text/event-stream: [(tipo, dati)] (i commenti di ping si ignorano)
def _eventi_sse(testo: str) -> list[tuple[str, dict]]:
    eventi = []
    for blocco in testo.split("\n\n"):
        righe = [r for r in blocco.splitlines() if r and not r.startswith(":")]
        if not righe:
            continue
        tipo = next(r[len("event: "):] for r in righe if r.startswith("event: "))
        dati = json.loads(next(r[len("data: "):] for r in righe if r.startswith("data: ")))
        eventi.append((tipo, dati))
    return eventi


def _client_flusso(modello):
    from tests.finti import ModelloFlussoFinto  # noqa: F401 (usato dai chiamanti)
    return TestClient(crea_app(lambda: _agente(modello)), raise_server_exceptions=False)


# Verifica lo stream: tipo di contenuto, testo a pezzi, fine con lo stesso corpo di POST /chat.
def test_stream_testo_a_pezzi():
    from tests.finti import ModelloFlussoFinto
    with _client_flusso(ModelloFlussoFinto(risposte=[AIMessage("A Roma sono le 12.")])) as c:
        r = c.post("/chat/stream", json={"messaggio": "Che ore sono?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    eventi = _eventi_sse(r.text)
    assert [t for t, _ in eventi].count("testo") >= 2
    tipo, fine = eventi[-1]
    assert tipo == "fine"
    assert fine["risposta"] == "A Roma sono le 12."
    assert fine["cronologia"][-1] == {"role": "assistant", "content": "A Roma sono le 12."}
    # con lo stesso modello POST /chat restituisce la stessa risposta
    with _client_flusso(ModelloFlussoFinto(risposte=[AIMessage("A Roma sono le 12.")])) as c:
        assert c.post("/chat", json={"messaggio": "Che ore sono?"}).json()["risposta"] == fine["risposta"]


# Verifica che gli errori di validazione arrivino in JSON prima dello stream.
def test_stream_errore_di_validazione_prima():
    from tests.finti import ModelloFlussoFinto
    with _client_flusso(ModelloFlussoFinto(risposte=[AIMessage("x")])) as c:
        r = c.post("/chat/stream", json={"cronologia": []})
    assert r.status_code == 422
    assert r.json()["errore"] == "richiesta_non_valida"


# Verifica un errore del modello a meta': evento errore con il codice di sempre.
def test_stream_errore_a_meta():
    from tests.finti import ModelloFlussoFinto

    class Rotto(ModelloFlussoFinto):
        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            raise APIConnectionError(request=RICHIESTA)

    with _client_flusso(Rotto(risposte=[AIMessage("x")])) as c:
        r = c.post("/chat/stream", json={"messaggio": "Che ore sono?"})
    assert r.status_code == 200
    tipo, dati = _eventi_sse(r.text)[-1]
    assert tipo == "errore" and dati["errore"] == "modello_non_raggiungibile"


# Verifica che la tabella degli errori sia una sola (gestori e stream usano la stessa funzione).
def test_errore_da_eccezione():
    from app.api import CronologiaNonValida, errore_da_eccezione
    risposta = httpx.Response(500, request=RICHIESTA)
    casi = [(APITimeoutError(request=RICHIESTA), 504, "modello_in_timeout"),
            (APIConnectionError(request=RICHIESTA), 503, "modello_non_raggiungibile"),
            (APIStatusError("x", response=risposta, body=None), 502, "errore_del_modello"),
            (ErroreMCP("giù"), 503, "mcp_non_disponibile"),
            (PromptNonValido("no"), 422, "prompt_non_valido"),
            (CronologiaNonValida("rotta"), 422, "richiesta_non_valida"),
            (RuntimeError("boh"), 500, "errore_interno")]
    for eccezione, status, errore in casi:
        assert errore_da_eccezione(eccezione)[:2] == (status, errore), eccezione


# Verifica che l'OpenAPI documenti lo stream.
def test_openapi_con_lo_stream():
    from tests.finti import ModelloFlussoFinto
    with _client_flusso(ModelloFlussoFinto(risposte=[AIMessage("x")])) as c:
        spec = c.get("/openapi.json").json()
    assert "text/event-stream" in spec["paths"]["/chat/stream"]["post"]["responses"]["200"]["content"]


# Verifica che il corpo dello stream chiuda subito il generatore quando la risposta viene annullata
# (client disconnesso), senza aspettare il garbage collector.
def test_corpo_chiude_il_generatore_quando_annullato():
    import asyncio
    import contextlib
    import threading
    import time
    from app.api import _corpo
    chiuso = threading.Event()

    def generatore():
        try:
            while True:
                yield "x"
                time.sleep(0.01)
        finally:
            chiuso.set()

    async def principale():
        g = generatore()  # resta referenziato: niente chiusura dal garbage collector

        async def consuma():
            async for _ in _corpo(g):
                pass
        compito = asyncio.create_task(consuma())
        await asyncio.sleep(0.1)
        compito.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await compito
        await asyncio.sleep(0.1)
        return chiuso.is_set(), g

    chiuso_subito, _ = asyncio.run(principale())
    assert chiuso_subito
