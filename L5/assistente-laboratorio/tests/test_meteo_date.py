"""Test del meteo per una data specifica: lettura della data, "tra N giorni" come periodo da
domani, limite a oggi + 7, fuso della citta'.

Istante fisso (giovedi' 5 novembre 2026) e risposte simulate: nessuna rete.
"""
from datetime import date, datetime, timezone

import pytest

from mcp_meteo import errori
from mcp_meteo import meteo as modulo_meteo  # il modulo: "testo_meteo" sembrerebbe un test
from mcp_meteo.contatore import Contatore
from mcp_meteo.meteo import FONTE, leggi_giorno, leggi_periodo
from tests.meteo_finto import GEO_ROMA, METEO_ESEMPIO, client_finto, geo_con, meteo_copia

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
    ("natale", date(2026, 12, 25)), ("per domani", date(2026, 11, 6)),
    # forme naturali trovate dalla revisione finale (il modello passa la data come la scrive l'utente)
    ("a Natale", date(2026, 12, 25)), ("il prossimo sabato", date(2026, 11, 7)),
    ("sabato 7 novembre", date(2026, 11, 7)), ("dopo domani", date(2026, 11, 7)),
    ("venerdi'", date(2026, 11, 6)), ("tra un giorno", date(2026, 11, 6)),
    ("tra due giorni", date(2026, 11, 7)), ("fra sette giorni", date(2026, 11, 12)),
    # "prossimo" detto nello stesso giorno della settimana: la settimana dopo, non oggi
    ("giovedì prossimo", date(2026, 11, 12)), ("il prossimo giovedì", date(2026, 11, 12))])
def test_leggi_giorno(testo, atteso):
    """Date relative, giorni della settimana, formati dell'esercizio 3 e parole di contorno."""
    assert leggi_giorno(testo, OGGI) == atteso


@pytest.mark.parametrize("testo, primo, ultimo", [
    # "tra N giorni": gli N giorni da domani, oggi escluso (oggi e' sottinteso)
    ("tra 1 giorno", date(2026, 11, 6), date(2026, 11, 6)),
    ("tra un giorno", date(2026, 11, 6), date(2026, 11, 6)),
    ("tra due giorni", date(2026, 11, 6), date(2026, 11, 7)),
    ("fra 3 giorni", date(2026, 11, 6), date(2026, 11, 8)),
    ("fra sette giorni", date(2026, 11, 6), date(2026, 11, 12)),
    # le altre date restano un giorno solo
    ("domani", date(2026, 11, 6), date(2026, 11, 6)),
    ("sabato", date(2026, 11, 7), date(2026, 11, 7)),
    ("15 novembre", date(2026, 11, 15), date(2026, 11, 15))])
def test_leggi_periodo(testo, primo, ultimo):
    """Primo e ultimo giorno da mostrare: "tra N giorni" e' un periodo, le altre date un giorno."""
    assert leggi_periodo(testo, OGGI) == (primo, ultimo)


@pytest.mark.parametrize("testo", ["tra 0 giorni", "fra zero giorni"])
def test_tra_zero_giorni_non_valido(testo):
    """"tra 0 giorni" non indica nessun giorno da domani -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        leggi_periodo(testo, OGGI)


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


def _meteo_8_giorni() -> dict:
    """METEO_ESEMPIO con un ottavo giorno (12 novembre): serve a "tra 7 giorni"."""
    dati = meteo_copia()
    for chiave, valore in (("time", "2026-11-12"), ("weather_code", 0),
                           ("temperature_2m_max", 16.0), ("temperature_2m_min", 8.0),
                           ("precipitation_probability_max", 0)):
        dati["daily"][chiave].append(valore)
    return dati


def _righe_previsione(testo: str) -> list[str]:
    """Le righe "- ..." dopo "Previsioni:"."""
    return [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]


def test_tra_due_giorni_da_domani(monkeypatch, contatore):
    """"tra due giorni" detto il 5 novembre: il 6 e il 7, oggi escluso."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "tra due giorni", richieste=richieste)
    righe = _righe_previsione(testo)
    assert len(righe) == 2
    assert righe[0].startswith("- domani, venerdì 6 novembre 2026: ")
    assert righe[1].startswith("- sabato 7 novembre 2026: ")
    assert "- oggi, " not in testo
    assert _api(richieste)[0].url.params["forecast_days"] == "3"  # oggi, 6 e 7
    assert "Meteo attuale a Roma (Lazio)" in testo  # il meteo attuale resta


def test_tra_un_giorno_e_domani(monkeypatch, contatore):
    """"tra un giorno" = domani: una sola riga."""
    righe = _righe_previsione(_meteo(monkeypatch, contatore, "tra un giorno"))
    assert len(righe) == 1 and righe[0].startswith("- domani, venerdì 6 novembre 2026: ")


def test_tra_sette_giorni(monkeypatch, contatore):
    """"tra 7 giorni": 7 righe dal 6 al 12 novembre, 8 giorni chiesti a Open-Meteo."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "tra 7 giorni", meteo=_meteo_8_giorni(),
                   richieste=richieste)
    righe = _righe_previsione(testo)
    assert len(righe) == 7
    assert righe[0].startswith("- domani, venerdì 6 novembre 2026: ")
    assert righe[-1].startswith("- giovedì 12 novembre 2026: ")
    assert _api(richieste)[0].url.params["forecast_days"] == "8"


def test_data_singola_a_oggi_piu_sette(monkeypatch, contatore):
    """Anche una data singola arriva a oggi + 7 (12 novembre): una riga, 8 giorni chiesti."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "2026-11-12", meteo=_meteo_8_giorni(),
                   richieste=richieste)
    righe = _righe_previsione(testo)
    assert len(righe) == 1 and righe[0].startswith("- giovedì 12 novembre 2026: ")
    assert _api(richieste)[0].url.params["forecast_days"] == "8"


@pytest.mark.parametrize("data, giorno", [
    ("2026-11-13", "venerdì 13 novembre 2026"), ("tra 30 giorni", "sabato 5 dicembre 2026"),
    ("fra 8 giorni", "venerdì 13 novembre 2026"), ("fra 20 giorni", "mercoledì 25 novembre 2026")])
def test_data_oltre(monkeypatch, contatore, data, giorno):
    """Oltre oggi + 7: nessuna previsione affidabile, nessuna chiamata al meteo, nessun valore."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, data, richieste=richieste)
    assert (f"Nessuna previsione affidabile per {giorno}: oltre giovedì 12 novembre 2026 "
            "non ci sono previsioni affidabili.") in testo
    assert "Località: Roma (Lazio)" in testo
    assert testo.rstrip().endswith(FONTE)
    assert _api(richieste) == [] and len(richieste) == 1  # solo il geocoding
    assert "°C" not in testo  # nessun valore


def test_data_passata(monkeypatch, contatore):
    """Data passata: lo dice e non chiama il meteo."""
    richieste = []
    testo = _meteo(monkeypatch, contatore, "2026-11-01", richieste=richieste)
    assert ("Il 1 novembre 2026 è già passato: sono disponibili solo il meteo attuale e le "
            "previsioni fino a giovedì 12 novembre 2026.") in testo
    assert _api(richieste) == []


def test_date_prevale_su_days(monkeypatch, contatore):
    """Con date e days insieme vale date: una sola riga."""
    testo = _meteo(monkeypatch, contatore, "domani", days=5)
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert len(righe) == 1 and righe[0].startswith("- domani, venerdì 6 novembre 2026: ")


def test_date_con_days_fuori_intervallo(monkeypatch, contatore):
    """Con date presente days e' ignorato, anche se fuori intervallo (il modello riempie entrambi)."""
    testo = _meteo(monkeypatch, contatore, "domani", days=10)
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert len(righe) == 1 and righe[0].startswith("- domani, ")


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
