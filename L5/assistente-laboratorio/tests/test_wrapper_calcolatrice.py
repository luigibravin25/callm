import json

import httpx
import pytest

from app import tools


@pytest.fixture
def servizio_finto(monkeypatch):
    """Sostituisce il client HTTP del wrapper con uno che risponde tramite `handler`.
    Restituisce l'elenco delle richieste ricevute."""
    richieste = []

    def installa(handler):
        def registra(request):
            richieste.append(request)
            return handler(request)
        monkeypatch.setattr(tools, "_client",
                            lambda: httpx.Client(transport=httpx.MockTransport(registra)))
        return richieste
    monkeypatch.delenv("CALC_BASE_URL", raising=False)
    return installa


def chiama(espressione):
    return tools.calcola_espressione.invoke({"espressione": espressione})


def risposta(*args, **kwargs):
    return lambda request: httpx.Response(*args, **kwargs)


def solleva(eccezione):
    def handler(request):
        raise eccezione("simulato", request=request)
    return handler


def test_risultato_formattato(servizio_finto):
    servizio_finto(risposta(200, json={"espressione": "2^0.5", "risultato": 1.4142135623730951}))
    assert chiama("2^0.5") == "2^0.5 = 1,41421"


def test_risultato_grande(servizio_finto):
    servizio_finto(risposta(200, json={"espressione": "10^20", "risultato": 1e20}))
    assert chiama("10^20") == "10^20 = 1 × 10^20"


def test_rifiuto_del_servizio(servizio_finto):
    servizio_finto(risposta(400, json={"errore": "divisione per zero"}))
    assert chiama("1/0") == "Espressione rifiutata: divisione per zero"


def test_422(servizio_finto):
    servizio_finto(risposta(422, json={"detail": []}))
    assert "HTTP 422" in chiama("1+1")


def test_errore_500(servizio_finto):
    servizio_finto(risposta(500, text="Internal Server Error"))
    assert chiama("1+1") == "Il servizio HTTP ha risposto con l'errore HTTP 500."


def test_timeout(servizio_finto):
    servizio_finto(solleva(httpx.ReadTimeout))
    assert chiama("1+1") == "Il servizio HTTP non ha risposto entro 5 secondi."


def test_non_raggiungibile(servizio_finto, monkeypatch):
    servizio_finto(solleva(httpx.ConnectError))
    monkeypatch.setenv("CALC_BASE_URL", "http://spento:9")
    testo = chiama("1+1")
    assert "non raggiungibile a http://spento:9" in testo
    assert "Traceback" not in testo


@pytest.mark.parametrize("finta", [
    httpx.Response(200, text="non json"), httpx.Response(200, json={}),
    httpx.Response(200, json={"risultato": "7"}), httpx.Response(200, json={"risultato": True}),
    httpx.Response(400, json={"messaggio": "x"}), httpx.Response(200, json=[1]),
    httpx.Response(400, text="rotto"),
])
def test_risposta_non_valida(servizio_finto, finta):
    servizio_finto(lambda request: finta)
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


def test_url_letta_a_ogni_chiamata(servizio_finto, monkeypatch):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    monkeypatch.setenv("CALC_BASE_URL", "http://primo:8001")
    chiama("1+1")
    monkeypatch.setenv("CALC_BASE_URL", "http://secondo:8001")
    chiama("1+1")
    assert [str(r.url) for r in richieste] == [
        "http://primo:8001/calcola", "http://secondo:8001/calcola"]


def test_url_senza_doppia_barra(servizio_finto, monkeypatch):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    monkeypatch.setenv("CALC_BASE_URL", "http://host:8001/")
    chiama("1+1")
    assert str(richieste[0].url) == "http://host:8001/calcola"


def test_url_predefinita(servizio_finto):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    chiama("1+1")
    assert str(richieste[0].url) == "http://127.0.0.1:8001/calcola"


def test_corpo_inviato(servizio_finto):
    richieste = servizio_finto(risposta(200, json={"risultato": 2}))
    chiama("1+1")
    assert richieste[0].method == "POST"
    assert json.loads(richieste[0].content) == {"espressione": "1+1"}


def test_nome_e_schema():
    assert tools.calcola_espressione.name == "toolcalc"
    assert set(tools.calcola_espressione.args) == {"espressione"}
    assert "^" in tools.calcola_espressione.description


def test_strumenti_registrati():
    assert [t.name for t in tools.STRUMENTI] == ["tooltime", "toolconvert", "toolcalc", "tooldate"]


# --- correzioni della revisione finale: il wrapper non solleva mai ---

def test_url_non_valida(servizio_finto, monkeypatch):
    servizio_finto(risposta(200, json={"risultato": 2}))
    monkeypatch.setenv("CALC_BASE_URL", "http://localhost:80O1")
    testo = chiama("1+1")
    assert "CALC_BASE_URL non valida" in testo and "80O1" in testo


def test_corpo_compresso_rotto(servizio_finto):
    servizio_finto(risposta(200, headers={"content-encoding": "gzip"}, content=b"spazzatura"))
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


def test_risultato_intero_enorme(servizio_finto):
    servizio_finto(risposta(200, json={"risultato": 10**400}))
    assert chiama("1+1") == "Risposta non valida dal servizio HTTP."


def test_descrizione_chiede_testo_semplice():
    # il modello tende a rispondere in LaTeX ("$5$ alla seconda fa $25$"): il terminale non lo rende
    descrizione = tools.calcola_espressione.description
    assert "senza LaTeX" in descrizione and "$" in descrizione
