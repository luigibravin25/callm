import pytest
from fastapi.testclient import TestClient

from servizio.main import app

client = TestClient(app)


def test_calcola_ok():
    r = client.post("/calcola", json={"espressione": "(3+4)^2/7"})
    assert r.status_code == 200
    assert r.json() == {"espressione": "(3+4)^2/7", "risultato": 7}


def test_espressione_rifiutata_e_400():
    r = client.post("/calcola", json={"espressione": "2+x"})
    assert r.status_code == 400
    assert "carattere non ammesso 'x'" in r.json()["errore"]


def test_divisione_per_zero_e_400_non_500():
    r = client.post("/calcola", json={"espressione": "1/0"})
    assert r.status_code == 400
    assert "divisione per zero" in r.json()["errore"]


@pytest.mark.parametrize("corpo", [{}, {"espressione": 3}, {"testo": "1+1"}])
def test_corpo_non_valido_e_422(corpo):
    assert client.post("/calcola", json=corpo).status_code == 422


def test_json_rotto_e_422():
    r = client.post("/calcola", content="{non json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_salute():
    r = client.get("/salute")
    assert r.status_code == 200 and r.json() == {"stato": "ok"}


def test_carattere_non_stampabile_e_400_non_500():
    # il JSON contiene la sequenza di escape \ud800 (surrogato isolato), non il carattere
    r = client.post("/calcola", content=r'{"espressione": "\ud800"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert "U+D800" in r.json()["errore"]


# --- /giorni (giorni e scadenze) ---

from datetime import date  # noqa: E402

from servizio import date_lavoro  # noqa: E402


@pytest.fixture
def oggi_fisso(monkeypatch):
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2026, 11, 3))


def test_giorni_200_con_avviso(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "giorni", "data": "31/12/2026",
                                     "da": "1/12/2026"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["giorni_lavorativi"] == 21 and corpo["avviso"] == date_lavoro.AVVISO


def test_scadenza_200(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "scadenza", "giorni": 5,
                                     "tipo": "calendario"})
    assert r.status_code == 200
    assert r.json()["scadenza"] == "2026-11-09" and r.json()["slittata_da"] == "2026-11-08"


def test_giorno_200(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "giorno", "data": "pasqua 2027"})
    assert r.status_code == 200
    assert r.json()["data"] == "2027-03-28" and r.json()["festivita"] == ["Pasqua"]


def test_giorni_400(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "giorno", "data": "31/02/2026"})
    assert r.status_code == 400 and "febbraio" in r.json()["errore"]


def test_scadenza_senza_giorni_400(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "scadenza"})
    assert r.status_code == 400 and "manca il numero di giorni" in r.json()["errore"]


def test_argomenti_non_usati_ignorati(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "giorno", "data": "oggi", "tipo": "calendario",
                                     "giorni": 3, "da": "1/1/2026"})
    assert r.status_code == 200 and r.json()["data"] == "2026-11-03"


@pytest.mark.parametrize("corpo", [
    {}, {"operazione": "mesi"}, {"operazione": "giorno", "data": 5},
    {"operazione": "scadenza", "giorni": "3"},
    {"operazione": "scadenza", "giorni": 1, "tipo": "lavorativo"},
])
def test_giorni_422(corpo):
    assert client.post("/giorni", json=corpo).status_code == 422


def test_giorni_carattere_non_stampabile_400(oggi_fisso):
    r = client.post("/giorni", json={"operazione": "giorno", "data": "25\u0001dicembre"})
    assert r.status_code == 400 and "U+0001" in r.json()["errore"]


def test_giorni_surrogato_400(oggi_fisso):
    r = client.post("/giorni", content=r'{"operazione": "giorno", "data": "\ud800"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
