"""Test del meteo per una data specifica: lettura della data, limite dei 7 giorni, fuso della citta'.

Istante fisso (giovedi' 5 novembre 2026) e risposte simulate: nessuna rete.
"""
from datetime import date, datetime, timezone

import pytest

from mcp_meteo import errori
from mcp_meteo import meteo as modulo_meteo  # il modulo: "testo_meteo" sembrerebbe un test
from mcp_meteo.contatore import Contatore
from mcp_meteo.meteo import FONTE, leggi_giorno
from tests.meteo_finto import GEO_ROMA, METEO_ESEMPIO, client_finto, geo_con

ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # giovedi' 5 novembre 2026
OGGI = date(2026, 11, 5)


@pytest.fixture
def contatore(tmp_path):
    """Contatore vero su un file temporaneo, limite 1000."""
    return Contatore(tmp_path / "c.sqlite", 1000, lambda: ISTANTE)


def _meteo(monkeypatch, contatore, data, days=0, istante=ISTANTE, geo=GEO_ROMA,
           meteo=METEO_ESEMPIO, richieste=None):
    """testo_meteo per "Roma" (o il geocoding indicato) con una data e un istante fisso."""
    monkeypatch.setattr("mcp_meteo.meteo._adesso", lambda: istante)
    client = client_finto(geo=geo, meteo=meteo, richieste=richieste)
    return modulo_meteo.testo_meteo("Roma", days, data, client, contatore)


def _api(richieste):
    """Richieste inviate all'API meteo (non al geocoding)."""
    return [r for r in richieste if r.url.host == "api.open-meteo.com"]


@pytest.mark.parametrize("testo, atteso", [
    ("oggi", date(2026, 11, 5)), ("domani", date(2026, 11, 6)),
    ("dopodomani", date(2026, 11, 7)), ("tra 3 giorni", date(2026, 11, 8)),
    ("fra 20 giorni", date(2026, 11, 25)), ("tra 1 giorno", date(2026, 11, 6)),
    ("sabato", date(2026, 11, 7)), ("giovedì", date(2026, 11, 5)),
    ("Sabato prossimo", date(2026, 11, 7)), ("mercoledi", date(2026, 11, 11)),
    ("il 15 novembre", date(2026, 11, 15)), ("15 novembre", date(2026, 11, 15)),
    ("2026-11-09", date(2026, 11, 9)), ("09/11/2026", date(2026, 11, 9)),
    ("natale", date(2026, 12, 25)), ("per domani", date(2026, 11, 6))])
def test_leggi_giorno(testo, atteso):
    """Date relative, giorni della settimana, formati dell'esercizio 3 e parole di contorno."""
    assert leggi_giorno(testo, OGGI) == atteso


@pytest.mark.parametrize("testo", ["boh", "32 novembre", ""])
def test_data_non_leggibile(testo):
    """Data non leggibile o vuota -> ArgomentoNonValido con i formati ammessi."""
    with pytest.raises(errori.ArgomentoNonValido) as info:
        leggi_giorno(testo, OGGI)
    assert "formati ammessi" in str(info.value)


def test_data_valida_una_riga(monkeypatch, contatore):
    """Data entro 7 giorni: meteo attuale piu' la sola riga di quel giorno."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "2026-11-11", richieste=richieste)  # oggi + 6
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert righe == ["- mercoledì 11 novembre 2026: rovesci di pioggia deboli, minima 4,4 °C, "
                     "massima 9,9 °C, pioggia 60 %"]
    assert _api(richieste)[0].url.params["forecast_days"] == "7"
    assert "Meteo attuale a Roma (Lazio)" in testo  # anche il meteo attuale


@pytest.mark.parametrize("data", ["2026-11-12", "tra 30 giorni"])
def test_data_oltre(monkeypatch, contatore, data):
    """Oltre i 7 giorni: nessuna previsione affidabile, nessuna chiamata al meteo, nessun valore."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, data, richieste=richieste)
    giorno = "giovedì 12 novembre 2026" if data == "2026-11-12" else "sabato 5 dicembre 2026"
    assert (f"Nessuna previsione affidabile per {giorno}: le previsioni arrivano a 7 giorni, "
            "fino a mercoledì 11 novembre 2026.") in testo
    assert "Località: Roma (Lazio)" in testo
    assert testo.rstrip().endswith(FONTE)
    assert _api(richieste) == [] and len(richieste) == 1  # solo il geocoding
    assert "°C" not in testo  # nessun valore


def test_data_passata(monkeypatch, contatore):
    """Data passata: lo dice e non chiama il meteo."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "2026-11-01", richieste=richieste)
    assert ("Il 1 novembre 2026 è già passato: sono disponibili solo il meteo attuale e le "
            "previsioni fino a mercoledì 11 novembre 2026.") in testo
    assert _api(richieste) == []


def test_date_prevale_su_days(monkeypatch, contatore):
    """Con date e days insieme vale date: una sola riga."""
    testo = _meteo(monkeypatch, contatore, "domani", days=5)
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert len(righe) == 1 and righe[0].startswith("- domani, venerdì 6 novembre 2026: ")


def test_date_non_testo(monkeypatch, contatore):
    """date che non e' un testo -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        _meteo(monkeypatch, contatore, 15)


def test_oggi_dopo_la_mezzanotte_italiana(monkeypatch, contatore):
    """"oggi" e' la data locale della citta': alle 23:30 UTC del 5 novembre in Italia e' gia' il 6."""
    # Review Focus 4: il giorno non e' quello UTC ma quello del fuso della citta' (Europe/Rome)
    testo = _meteo(monkeypatch, contatore, "oggi",
                   istante=datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc))
    assert "- oggi, venerdì 6 novembre 2026: " in testo


def test_fuso_della_citta_mancante(monkeypatch, contatore):
    """Luogo senza fuso orario con una data -> RispostaNonValida."""
    roma = dict(GEO_ROMA["results"][0])
    del roma["timezone"]
    with pytest.raises(errori.RispostaNonValida):
        _meteo(monkeypatch, contatore, "domani", geo=geo_con(roma))
