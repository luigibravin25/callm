"""Test delle richieste HTTP a Open-Meteo: parametri, conteggio e traduzione degli errori.

Le risposte sono simulate con httpx.MockTransport (tests/meteo_finto.py): nessuna rete.
"""
from datetime import datetime, timezone

import httpx
import pytest

from mcp_meteo import errori
from mcp_meteo.contatore import Contatore
from mcp_meteo.open_meteo import cerca_citta, meteo
from tests.meteo_finto import GEO_SAN_GIOVANNI, GEO_VUOTO, METEO_ESEMPIO, client_finto

ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def contatore(tmp_path):
    """Contatore vero su un file temporaneo, limite 1000."""
    return Contatore(tmp_path / "c.sqlite", 1000, lambda: ISTANTE)


def test_geocoding_parametri(contatore):
    """Il geocoding cerca solo in Italia (countryCode=IT), in italiano, e restituisce i luoghi."""
    richieste = []
    risultati = cerca_citta(client_finto(geo=GEO_SAN_GIOVANNI, richieste=richieste), contatore,
                            "San Giovanni")
    parametri = richieste[0].url.params
    assert (parametri["name"], parametri["count"], parametri["language"], parametri["format"],
            parametri["countryCode"]) == ("San Giovanni", "10", "it", "json", "IT")
    assert len(risultati) == 6 and all(r["name"] == "San Giovanni" for r in risultati)


def test_geocoding_senza_results(contatore):
    """Senza la chiave results (nessuna citta') il geocoding restituisce []."""
    assert cerca_citta(client_finto(geo=GEO_VUOTO), contatore, "Xyzqwk") == []


def test_meteo_parametri(contatore):
    """days=0: solo meteo attuale; days=3: anche daily e forecast_days=3."""
    richieste = []
    client = client_finto(meteo=METEO_ESEMPIO, richieste=richieste)
    meteo(client, contatore, 41.89, 12.51, 0)
    meteo(client, contatore, 41.89, 12.51, 3)
    senza, con = richieste[0].url.params, richieste[1].url.params
    assert senza["current"] == "temperature_2m,weather_code"
    assert senza["timezone"] == "auto"
    assert "daily" not in senza and "forecast_days" not in senza
    assert con["daily"] == ("weather_code,temperature_2m_max,temperature_2m_min,"
                            "precipitation_probability_max")
    assert con["forecast_days"] == "3"


@pytest.mark.parametrize("eccezione", [httpx.ReadTimeout("lento"),
                                       httpx.ConnectTimeout("lento")])
def test_timeout(contatore, eccezione):
    """Timeout di connessione o di lettura -> TimeoutMeteo, problema di connessione e non di citta'."""
    with pytest.raises(errori.TimeoutMeteo) as info:
        cerca_citta(client_finto(geo=eccezione), contatore, "Roma")
    assert "connessione" in str(info.value) and "non trovata" not in str(info.value)


def test_rete_assente(contatore):
    """Rete assente (ConnectError) -> ReteNonRaggiungibile, distinto da "citta' non trovata"."""
    with pytest.raises(errori.ReteNonRaggiungibile) as info:
        cerca_citta(client_finto(geo=httpx.ConnectError("getaddrinfo failed")), contatore, "Roma")
    assert not isinstance(info.value, errori.CittaNonTrovata)
    assert "non riguarda la città" in str(info.value)


@pytest.mark.parametrize("stato", [500, 503])
def test_errore_5xx(contatore, stato):
    """HTTP 500 e 503 -> ServizioNonDisponibile."""
    with pytest.raises(errori.ServizioNonDisponibile):
        meteo(client_finto(meteo=httpx.Response(stato, text="guasto")), contatore, 1, 2, 0)


def test_429(contatore):
    """HTTP 429 -> "troppe richieste, riprova più tardi", diverso dal limite giornaliero locale."""
    with pytest.raises(errori.ServizioNonDisponibile) as info:
        meteo(client_finto(meteo=httpx.Response(429, json={"error": True})), contatore, 1, 2, 0)
    assert "troppe richieste, riprova più tardi" in str(info.value)
    assert not isinstance(info.value, errori.LimiteRaggiunto)


def test_400_con_reason(contatore):
    """HTTP 400 -> RispostaNonValida con il motivo dato da Open-Meteo."""
    corpo = {"error": True, "reason": "Latitude must be in range of -90 to 90°. Given: 999.0."}
    with pytest.raises(errori.RispostaNonValida) as info:
        meteo(client_finto(meteo=httpx.Response(400, json=corpo)), contatore, 999, 2, 0)
    assert "Latitude must be in range" in str(info.value)


def test_json_non_valido(contatore):
    """Corpo che non e' JSON -> RispostaNonValida."""
    with pytest.raises(errori.RispostaNonValida):
        cerca_citta(client_finto(geo=httpx.Response(200, text="<html>non json</html>")),
                    contatore, "Roma")


@pytest.mark.parametrize("corpo", [[1, 2, 3], "testo", 42])
def test_json_non_oggetto(contatore, corpo):
    """JSON valido ma non oggetto (lista, testo, numero) -> RispostaNonValida."""
    with pytest.raises(errori.RispostaNonValida):
        cerca_citta(client_finto(geo=httpx.Response(200, json=corpo)), contatore, "Roma")


def test_results_non_lista(contatore):
    """results che non e' un elenco di luoghi -> RispostaNonValida."""
    with pytest.raises(errori.RispostaNonValida):
        cerca_citta(client_finto(geo={"results": "nessuno"}), contatore, "Roma")


def test_ogni_richiesta_contata(contatore):
    """Ogni richiesta inviata e' contata, anche quella fallita."""
    client = client_finto(geo=GEO_SAN_GIOVANNI, meteo=METEO_ESEMPIO)
    cerca_citta(client, contatore, "San Giovanni")
    meteo(client, contatore, 41.89, 12.51, 0)
    assert contatore.conteggio_di_oggi() == 2
    with pytest.raises(errori.ServizioNonDisponibile):
        meteo(client_finto(meteo=httpx.Response(500)), contatore, 1, 2, 0)
    assert contatore.conteggio_di_oggi() == 3  # anche la richiesta fallita e' stata inviata


def test_limite_nessuna_richiesta(tmp_path):
    """Con il limite raggiunto la richiesta non parte nemmeno."""
    pieno = Contatore(tmp_path / "c.sqlite", 1, lambda: ISTANTE)
    pieno.registra()
    richieste = []
    with pytest.raises(errori.LimiteRaggiunto):
        cerca_citta(client_finto(geo=GEO_SAN_GIOVANNI, richieste=richieste), pieno, "San Giovanni")
    assert richieste == []  # bloccata prima di partire
