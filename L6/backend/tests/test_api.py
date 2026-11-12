# test dell'API del back-end: endpoint, errori {errore, messaggio}, OpenAPI, persistenza, avvio
import os

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import api, servizio
from app.api import crea_app
from app.db import crea_motore, fabbrica_sessioni
from tests.finti import AgenteFinto, client_finto, risposta_ok

STRUMENTI = [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]
URL_SPENTO = "postgresql+psycopg://assistente:segreta@127.0.0.1:1/nessuno_test"


# client HTTP di prova sul back-end con database di prova e agente finto
@pytest.fixture
def client_per(fabbrica):
    aperti = []

    def crea(agente=None, fab=None):
        c = TestClient(crea_app(fab or fabbrica, client_finto(agente or AgenteFinto())),
                       raise_server_exceptions=False)
        aperti.append(c)
        return c
    yield crea
    for c in aperti:
        c.close()


# crea una chat e restituisce il suo id
def _nuova(c) -> int:
    r = c.post("/chat")
    assert r.status_code == 201
    return r.json()["id"]


# Verifica le cinque operazioni nel caso normale.
def test_operazioni(client_per):
    agente = AgenteFinto([risposta_ok("A Tokyo sono le 20.", strumenti=STRUMENTI)])
    c = client_per(agente)
    r = c.post("/chat")
    assert r.status_code == 201
    assert set(r.json()) == {"id", "titolo", "creata_il"} and r.json()["titolo"] == "Nuova chat"
    chat_id = r.json()["id"]
    assert c.get("/chat").json() == [{"id": chat_id, "titolo": "Nuova chat",
                                      "ultimo_messaggio_il": None}]
    r = c.post(f"/chat/{chat_id}/messaggi", json={"testo": "Ore a Tokyo?"})
    assert r.status_code == 200
    turno = r.json()
    assert (turno["domanda"]["ruolo"], turno["domanda"]["testo"]) == ("utente", "Ore a Tokyo?")
    assert turno["domanda"]["strumenti"] is None
    assert (turno["risposta"]["ruolo"], turno["risposta"]["strumenti"]) == ("assistente", STRUMENTI)
    letta = c.get(f"/chat/{chat_id}").json()
    assert [m["testo"] for m in letta["messaggi"]] == ["Ore a Tokyo?", "A Tokyo sono le 20."]
    assert letta["titolo"] == "Ore a Tokyo?"
    assert letta["ultimo_messaggio_il"] == turno["risposta"]["creato_il"]
    assert "cronologia_agente" not in letta and "riassunto" not in letta
    r = c.delete(f"/chat/{chat_id}")
    assert r.status_code == 204 and r.content == b""
    r = c.get(f"/chat/{chat_id}")
    assert r.status_code == 404
    assert r.json() == {"errore": "chat_non_trovata", "messaggio": f"Chat {chat_id} non trovata."}


# Verifica l'agente spento: 503 chiaro e domanda non salvata.
def test_agente_non_raggiungibile(client_per):
    c = client_per(AgenteFinto([httpx.ConnectError("rifiutata")]))
    chat_id = _nuova(c)
    r = c.post(f"/chat/{chat_id}/messaggi", json={"testo": "Ciao"})
    assert r.status_code == 503
    assert r.json()["errore"] == "agente_non_raggiungibile"
    assert "non è raggiungibile" in r.json()["messaggio"]
    assert c.get(f"/chat/{chat_id}").json()["messaggi"] == []


# Verifica timeout, errore inoltrato e risposta inattesa dell'agente.
@pytest.mark.parametrize("risposta, codice, errore", [
    (httpx.ReadTimeout("lento"), 504, "agente_in_timeout"),
    ((503, {"errore": "modello_non_raggiungibile", "messaggio": "LM Studio spento."}), 503,
     "modello_non_raggiungibile"),
    ((404, {"errore": "percorso_non_trovato", "messaggio": "x"}), 502,
     "risposta_agente_non_valida"),
])
def test_errori_dell_agente(client_per, risposta, codice, errore):
    c = client_per(AgenteFinto([risposta]))
    r = c.post(f"/chat/{_nuova(c)}/messaggi", json={"testo": "Ciao"})
    assert (r.status_code, r.json()["errore"]) == (codice, errore)
    if errore == "modello_non_raggiungibile":
        assert r.json()["messaggio"] == "LM Studio spento."


# Verifica le richieste non valide: 422 con messaggio in italiano.
@pytest.mark.parametrize("percorso, opzioni, testo", [
    ("/chat/{id}/messaggi", {"json": {"testo": "   "}}, "testo vuoto"),
    ("/chat/{id}/messaggi", {"json": {"testo": "a", "altro": 1}}, "campo non previsto"),
    ("/chat/{id}/messaggi", {"json": {}}, "campo obbligatorio mancante"),
    ("/chat/{id}/messaggi", {"content": b"{non json",
                             "headers": {"content-type": "application/json"}},
     "il corpo non è JSON valido"),
    ("/chat/abc/messaggi", {"json": {"testo": "a"}}, "deve essere un intero"),
    ("/chat/99999999999/messaggi", {"json": {"testo": "a"}}, "valore fuori intervallo"),
    ("/chat/0/messaggi", {"json": {"testo": "a"}}, "valore fuori intervallo"),
])
def test_richieste_non_valide(client_per, percorso, opzioni, testo):
    c = client_per()
    r = c.post(percorso.format(id=_nuova(c)), **opzioni)
    assert r.status_code == 422
    assert r.json()["errore"] == "richiesta_non_valida" and testo in r.json()["messaggio"]


# Verifica id fuori intervallo anche in lettura ed eliminazione (niente 500 dal database).
def test_id_enorme(client_per):
    c = client_per()
    assert c.get("/chat/99999999999").status_code == 422
    assert c.delete("/chat/99999999999").status_code == 422


# Verifica il corpo non UTF-8: 400 come l'agente.
def test_corpo_non_utf8(client_per):
    c = client_per()
    r = c.post(f"/chat/{_nuova(c)}/messaggi", content=b'{"testo": "\xff"}',
               headers={"content-type": "application/json"})
    assert (r.status_code, r.json()["errore"]) == (400, "richiesta_non_valida")


# Verifica 404 chat_non_trovata per lettura, invio, eliminazione; 404 e 405 generici.
def test_non_trovati(client_per):
    c = client_per()
    for r in (c.get("/chat/999"), c.post("/chat/999/messaggi", json={"testo": "a"}),
              c.delete("/chat/999")):
        assert (r.status_code, r.json()["errore"]) == (404, "chat_non_trovata")
    r = c.get("/altro")
    assert (r.status_code, r.json()["errore"]) == (404, "percorso_non_trovato")
    r = c.put("/chat")
    assert (r.status_code, r.json()["errore"]) == (405, "metodo_non_ammesso")


# Verifica il database non raggiungibile durante l'uso: 503.
def test_database_non_disponibile(client_per):
    motore = crea_motore(URL_SPENTO)
    c = client_per(fab=fabbrica_sessioni(motore))
    r = c.get("/chat")
    assert (r.status_code, r.json()["errore"]) == (503, "database_non_disponibile")
    assert "segreta" not in r.text
    motore.dispose()


# Verifica un errore imprevisto: 500 con messaggio fisso.
def test_errore_interno(client_per, monkeypatch):
    def rotta(_s):
        raise RuntimeError("guasto")
    monkeypatch.setattr(servizio, "elenca_chat", rotta)
    r = client_per().get("/chat")
    assert (r.status_code, r.json()["errore"]) == (500, "errore_interno")
    assert "guasto" not in r.text


# Verifica la documentazione OpenAPI: percorsi, schema Errore, /docs.
def test_openapi(client_per):
    c = client_per()
    schema = c.get("/openapi.json").json()
    assert {"/chat", "/chat/{chat_id}", "/chat/{chat_id}/messaggi"} <= set(schema["paths"])
    assert "Errore" in schema["components"]["schemas"]
    assert "agente_non_raggiungibile" in schema["info"]["description"]
    assert "modello_non_raggiungibile" in schema["info"]["description"]
    assert c.get("/docs").status_code == 200


# Verifica la persistenza: dati scritti da un'app, letti da un'altra con un motore nuovo
# (come dopo il riavvio del back-end).
def test_persistenza(client_per, motore):
    c = client_per(AgenteFinto([risposta_ok("Sono le 20.", strumenti=STRUMENTI)]))
    chat_id = _nuova(c)
    c.post(f"/chat/{chat_id}/messaggi", json={"testo": "Ore a Tokyo?"})
    prima = c.get(f"/chat/{chat_id}").json()
    motore.dispose()
    nuovo = crea_motore(os.environ["TEST_DATABASE_URL"])
    c2 = client_per(fab=fabbrica_sessioni(nuovo))
    assert c2.get(f"/chat/{chat_id}").json() == prima
    assert [x["id"] for x in c2.get("/chat").json()] == [chat_id]
    nuovo.dispose()


# --- avvio (python -m app.api) ---

# uvicorn.run che non deve essere chiamato
def _vietato(*a, **k):
    raise AssertionError("uvicorn.run chiamato")


# Verifica il database non raggiungibile all'avvio: messaggio chiaro, password nascosta.
def test_main_database_non_raggiungibile(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL_SPENTO)
    monkeypatch.setattr(uvicorn, "run", _vietato)
    with pytest.raises(SystemExit) as uscita:
        api.main()
    testo = str(uscita.value)
    assert "Database non raggiungibile" in testo and "***" in testo and "segreta" not in testo


# Verifica la configurazione non valida all'avvio.
def test_main_configurazione_non_valida(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(uvicorn, "run", _vietato)
    with pytest.raises(SystemExit) as uscita:
        api.main()
    assert str(uscita.value).startswith("Configurazione non valida: DATABASE_URL")


# Verifica l'avvio valido: tabelle create e uvicorn con host e porta.
def test_main_avvia_uvicorn(monkeypatch, motore):
    visti = {}
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("BACKEND_PORTA", "9123")
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: visti.update(k, app=app))
    api.main()
    assert (visti["host"], visti["port"], visti["log_config"]) == ("127.0.0.1", 9123, None)
