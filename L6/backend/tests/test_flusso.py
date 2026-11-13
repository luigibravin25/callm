# test dello streaming del back-end (step 10): lettura degli eventi dell'agente, turno con
# salvataggio solo a fine, domanda cancellata su errore o chiusura, endpoint SSE
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import sse
from app.api import crea_app
from app.client_agente import ClientAgente, ErroreAgente, leggi_eventi
from app.db import Messaggio
from app.servizio import crea_chat, invia_in_flusso, leggi_chat
from tests.finti import URL_AGENTE

# risposta di fine dell'agente (corpo di POST /chat)
FINE = {"risposta": "A Tokyo sono le 20.", "strumenti_usati": [{"nome": "tooltime",
        "argomenti": {"fuso": "Asia/Tokyo"}}], "categoria": "conversazione",
        "argomento": "ora_data_fusi",
        "cronologia": [{"role": "user", "content": "Che ore sono a Tokyo?"},
                       {"role": "assistant", "content": "A Tokyo sono le 20."}],
        "riassunto": ""}


def _sse(tipo, dati):
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


# corpo SSE di un turno completo dell'agente (con un ping in mezzo)
CORPO_OK = (_sse("fase", {"fase": "pensa"}) + _sse("bozza", {}) + ": ping\n\n"
            + _sse("strumento", {"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}})
            + _sse("testo", {"testo": "A Tokyo "}) + _sse("testo", {"testo": "sono le 20."})
            + _sse("fine", FINE))


# client dell'agente con una risposta fissa allo stream (corpo testo o iteratore di byte)
def _client(status=200, corpo=CORPO_OK, eccezione=None):
    def gestore(richiesta: httpx.Request) -> httpx.Response:
        assert richiesta.url.path == "/chat/stream"
        if eccezione:
            raise eccezione
        if isinstance(corpo, (str, bytes)):
            return httpx.Response(status, content=corpo if isinstance(corpo, bytes) else corpo.encode())
        return httpx.Response(status, content=corpo)
    return ClientAgente(URL_AGENTE, 5, transport=httpx.MockTransport(gestore))


# ---------- lettura degli eventi ----------

def test_leggi_eventi_ignora_i_ping():
    eventi = list(leggi_eventi(CORPO_OK.splitlines()))
    assert [t for t, _ in eventi] == ["fase", "bozza", "strumento", "testo", "testo", "fine"]
    assert eventi[3][1] == {"testo": "A Tokyo "}


def test_turno_in_flusso_completo():
    eventi = list(_client().turno_in_flusso("Che ore sono a Tokyo?", [], ""))
    assert eventi[-1][0] == "fine"
    assert eventi[-1][1].risposta == "A Tokyo sono le 20."


def test_flusso_senza_fine_interrotto():
    corpo = _sse("fase", {"fase": "pensa"}) + _sse("testo", {"testo": "A met"})
    with pytest.raises(ErroreAgente) as e:
        list(_client(corpo=corpo).turno_in_flusso("x", [], ""))
    assert (e.value.status, e.value.errore) == (502, "flusso_interrotto")


def test_errore_dell_agente_prima_dello_stream():
    corpo = json.dumps({"errore": "modello_non_raggiungibile", "messaggio": "LM Studio giù"})
    with pytest.raises(ErroreAgente) as e:
        list(_client(status=503, corpo=corpo).turno_in_flusso("x", [], ""))
    assert (e.value.status, e.value.errore) == (503, "modello_non_raggiungibile")


def test_agente_spento():
    with pytest.raises(ErroreAgente) as e:
        list(_client(eccezione=httpx.ConnectError("rifiutata")).turno_in_flusso("x", [], ""))
    assert e.value.errore == "agente_non_raggiungibile"


# ---------- servizio (database di prova) ----------

def _nuova_chat(fabbrica) -> int:
    with fabbrica() as s:
        return crea_chat(s).id


def _messaggi(fabbrica, chat_id):
    with fabbrica() as s:
        return [(m.ruolo, m.testo) for m in leggi_chat(s, chat_id).messaggi]


def test_salvataggio_solo_a_fine(fabbrica):
    chat_id = _nuova_chat(fabbrica)
    eventi = []
    for tipo, dati in invia_in_flusso(fabbrica, _client(), chat_id, "Che ore sono a Tokyo?"):
        # prima di fine: solo la domanda salvata
        if tipo == "testo":
            assert _messaggi(fabbrica, chat_id) == [("utente", "Che ore sono a Tokyo?")]
        eventi.append((tipo, dati))
    assert eventi[-1][0] == "fine"
    assert eventi[-1][1]["risposta"].testo == "A Tokyo sono le 20."
    assert _messaggi(fabbrica, chat_id) == [("utente", "Che ore sono a Tokyo?"),
                                            ("assistente", "A Tokyo sono le 20.")]


def test_errore_dell_agente_cancella_la_domanda(fabbrica):
    chat_id = _nuova_chat(fabbrica)
    corpo = _sse("fase", {"fase": "pensa"}) + _sse(
        "errore", {"errore": "modello_non_raggiungibile", "messaggio": "LM Studio giù"})
    eventi = list(invia_in_flusso(fabbrica, _client(corpo=corpo), chat_id, "x"))
    assert eventi[-1] == ("errore", {"errore": "modello_non_raggiungibile",
                                     "messaggio": "LM Studio giù"})
    assert _messaggi(fabbrica, chat_id) == []


def test_flusso_interrotto_cancella_la_domanda(fabbrica):
    chat_id = _nuova_chat(fabbrica)
    corpo = _sse("testo", {"testo": "A met"})
    eventi = list(invia_in_flusso(fabbrica, _client(corpo=corpo), chat_id, "x"))
    assert eventi[-1][0] == "errore" and eventi[-1][1]["errore"] == "flusso_interrotto"
    assert _messaggi(fabbrica, chat_id) == []


def test_chiusura_a_meta_cancella_la_domanda(fabbrica):
    chat_id = _nuova_chat(fabbrica)
    gen = invia_in_flusso(fabbrica, _client(), chat_id, "x")
    assert next(gen)[0] == "fase"
    gen.close()  # client disconnesso
    assert _messaggi(fabbrica, chat_id) == []


def test_client_chiuso_durante_il_silenzio(fabbrica, monkeypatch):
    # agente che dopo il primo evento tace a lungo (gemma che ragiona): con il ping il back-end si
    # accorge della chiusura senza aspettare l'evento successivo
    monkeypatch.setattr(sse, "INTERVALLO_PING", 0.05)
    chat_id = _nuova_chat(fabbrica)

    def lento():
        yield _sse("fase", {"fase": "pensa"}).encode()
        time.sleep(3)
        yield _sse("fine", FINE).encode()

    # la chiusura dello stream imposta "annullato": a ogni riga dell'agente il turno lo controlla
    annullato = threading.Event()
    righe = sse.con_ping((sse.formatta(t, {}) for t, _ in invia_in_flusso(
        fabbrica, _client(corpo=lento()), chat_id, "x", annullato)), alla_chiusura=annullato.set)
    assert next(righe).startswith("event: fase")
    assert next(righe) == sse.PING
    inizio = time.monotonic()
    righe.close()
    # la domanda sparisce quando il produttore si ferma (al massimo alla fine del silenzio)
    for _ in range(80):
        if _messaggi(fabbrica, chat_id) == []:
            break
        time.sleep(0.05)
    assert _messaggi(fabbrica, chat_id) == []
    assert time.monotonic() - inizio < 4


# ---------- API ----------

def _eventi_sse(testo):
    eventi = []
    for blocco in testo.split("\n\n"):
        righe = [r for r in blocco.splitlines() if r and not r.startswith(":")]
        if righe:
            tipo = righe[0][len("event: "):]
            eventi.append((tipo, json.loads(righe[1][len("data: "):])))
    return eventi


def test_api_stream(fabbrica):
    with TestClient(crea_app(fabbrica, _client())) as c:
        chat_id = c.post("/chat").json()["id"]
        r = c.post(f"/chat/{chat_id}/messaggi/stream", json={"testo": "Che ore sono a Tokyo?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    eventi = _eventi_sse(r.text)
    assert [t for t, _ in eventi] == ["fase", "bozza", "strumento", "testo", "testo", "fine"]
    fine = eventi[-1][1]
    assert fine["domanda"]["testo"] == "Che ore sono a Tokyo?"
    assert fine["risposta"]["testo"] == "A Tokyo sono le 20."
    assert fine["risposta"]["strumenti"][0]["nome"] == "tooltime"


def test_api_stream_disattivato(fabbrica):
    with TestClient(crea_app(fabbrica, _client(), streaming=False)) as c:
        chat_id = c.post("/chat").json()["id"]
        r = c.post(f"/chat/{chat_id}/messaggi/stream", json={"testo": "x"})
    assert r.status_code == 409
    assert r.json()["errore"] == "streaming_disattivato"


def test_api_stream_chat_inesistente(fabbrica):
    with TestClient(crea_app(fabbrica, _client())) as c:
        r = c.post("/chat/999/messaggi/stream", json={"testo": "x"})
    assert r.status_code == 404
    assert r.json()["errore"] == "chat_non_trovata"


def test_openapi_con_gli_eventi(fabbrica):
    with TestClient(crea_app(fabbrica, _client())) as c:
        spec = c.get("/openapi.json").json()
    risposta = spec["paths"]["/chat/{chat_id}/messaggi/stream"]["post"]["responses"]["200"]
    assert "text/event-stream" in risposta["content"]
    for nome in ("EventoFase", "EventoTesto", "EventoStrumento", "EventoRevisione"):
        assert nome in spec["components"]["schemas"], nome
