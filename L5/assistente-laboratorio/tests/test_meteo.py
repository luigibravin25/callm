"""Test della traduzione del meteo: scelta della citta' italiana, omonimi, previsioni, testo.

Risposte di Open-Meteo simulate (tests/meteo_finto.py), istante fisso: nessuna rete.
"""
from datetime import datetime, timezone

import httpx
import pytest

from mcp_meteo import errori
# il modulo, non la funzione: un nome importato che inizia con "test" (testo_meteo) verrebbe
# raccolto da pytest come se fosse un test
from mcp_meteo import meteo as modulo_meteo
from mcp_meteo.contatore import Contatore
from mcp_meteo.meteo import FONTE
from tests.meteo_finto import (GEO_PARIS_IT, GEO_ROMA, GEO_SAN_GIOVANNI, GEO_VUOTO,
                               METEO_ESEMPIO, client_finto, geo_con, luogo, meteo_copia)

ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # giovedi' 5 novembre 2026


@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    """Istante fisso per tutti i test del file."""
    monkeypatch.setattr("mcp_meteo.meteo._adesso", lambda: ISTANTE)


@pytest.fixture
def contatore(tmp_path):
    """Contatore vero su un file temporaneo, limite 1000."""
    return Contatore(tmp_path / "c.sqlite", 1000, lambda: ISTANTE)


def _meteo(contatore, city, days=0, geo=GEO_ROMA, meteo=METEO_ESEMPIO, richieste=None):
    """Chiama testo_meteo con il client finto (nessuna data)."""
    client = client_finto(geo=geo, meteo=meteo, richieste=richieste)
    return modulo_meteo.testo_meteo(city, days, "", client, contatore)


def _host(richieste, prefisso):
    """Richieste inviate a un host (prefisso "geocoding" o "api")."""
    return [r for r in richieste if r.url.host.startswith(prefisso)]


def test_risultato_completo(contatore):
    """Meteo attuale: citta', temperatura con unita', condizioni, ora con fuso, fonte."""
    testo = _meteo(contatore, "Roma")
    assert "Meteo attuale a Roma (Lazio)" in testo
    assert "- Temperatura: 10,5 °C" in testo
    assert "- Condizioni: coperto" in testo
    assert "- Ora di riferimento: 2026-11-05 19:45, ora locale Europe/Rome (GMT+1)" in testo
    assert testo.rstrip().endswith(FONTE)
    assert "Previsioni:" not in testo  # days=0: solo meteo attuale


def test_unita_dalla_risposta(contatore):
    """L'unita' della temperatura viene dalla risposta, non e' scritta nel codice."""
    dati = meteo_copia()
    dati["current_units"]["temperature_2m"] = "°F"
    assert "- Temperatura: 10,5 °F" in _meteo(contatore, "Roma", meteo=dati)


def test_sceglie_la_piu_popolosa(contatore):
    """Tra gli omonimi si sceglie il piu' popoloso, anche se Open-Meteo lo mette dopo."""
    richieste = []
    testo = _meteo(contatore, "San Giovanni", geo=GEO_SAN_GIOVANNI, richieste=richieste)
    assert "Meteo attuale a San Giovanni (Catania, Sicilia)" in testo
    # coordinate della San Giovanni siciliana nella richiesta del meteo
    assert _host(richieste, "api")[0].url.params["latitude"] == "37.6"


def test_omonimi_dichiarati(contatore):
    """Omonimi reali: 3 elencati per abitanti, gli altri contati, e la domanda all'utente."""
    testo = _meteo(contatore, "San Giovanni", geo=GEO_SAN_GIOVANNI)
    assert ("Altre località con questo nome: San Giovanni (Pordenone, Friuli Venezia Giulia); "
            "San Giovanni (Ferrara, Emilia-Romagna); San Giovanni (Teramo, Abruzzo) "
            "e altre 2.") in testo
    assert ("Chiedi all'utente quale preferisce: può scrivere per esempio "
            '"San Giovanni, Pordenone".') in testo


def test_alternative_dal_cinque_per_cento(contatore):
    """Un omonimo con meno del 5% degli abitanti della scelta non e' un'alternativa."""
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", 10000),
                  luogo("Borgo", "Toscana", "Provincia di Siena", 400),     # 4%: scartato
                  luogo("Borgo", "Marche", "Provincia di Ancona", 600))     # 6%: alternativa
    testo = _meteo(contatore, "Borgo", geo=geo)
    assert "Altre località con questo nome: Borgo (Ancona, Marche)." in testo
    assert "Siena" not in testo


def test_popolazione_assente(contatore):
    """Abitanti mancanti valgono 0: non battono la scelta e non superano la soglia."""
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", None),
                  luogo("Borgo", "Marche", "Provincia di Ancona", 1000),
                  luogo("Borgo", "Toscana", "Provincia di Siena", None))
    testo = _meteo(contatore, "Borgo", geo=geo)
    assert "Meteo attuale a Borgo (Ancona, Marche)" in testo
    assert "Altre località" not in testo


def test_un_solo_risultato_senza_alternative(contatore):
    """Una sola citta' trovata: nessuna alternativa e nessuna domanda."""
    testo = _meteo(contatore, "Roma", geo=geo_con(GEO_ROMA["results"][0]))
    assert "Altre località" not in testo and "Chiedi" not in testo


def test_roma_senza_alternative(contatore):
    """Roma (Mantova, 87 abitanti) e' sotto il 5%; "Romana" non ha lo stesso nome."""
    testo = _meteo(contatore, "Roma")
    assert "Altre località" not in testo
    assert "Mantova" not in testo and "Romana" not in testo


def test_citta_estera(contatore):
    """Una citta' estera (solo nomi simili in Italia) -> non trovata, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Paris", geo=GEO_PARIS_IT, richieste=richieste)
    assert "solo per le città italiane" in str(info.value) and "Paris" in str(info.value)
    assert _host(richieste, "api") == []


@pytest.mark.parametrize("city", ["San Giovanni, Friuli Venezia Giulia",
                                  "san giovanni, pordenone",
                                  "San Giovanni, Provincia di Pordenone"])
def test_precisazione(contatore, city):
    """Regione o provincia dopo la virgola scelgono l'omonimo; a Open-Meteo va solo il nome."""
    richieste = []
    testo = _meteo(contatore, city, geo=GEO_SAN_GIOVANNI, richieste=richieste)
    assert "Meteo attuale a San Giovanni (Pordenone, Friuli Venezia Giulia)" in testo
    assert _host(richieste, "geocoding")[0].url.params["name"] == city.split(",")[0]
    assert "Altre località" not in testo  # resta un solo candidato


def test_precisazione_sceglie_anche_una_frazione(contatore):
    """Con la precisazione si puo' chiedere anche l'omonimo piccolo (Roma in provincia di Mantova)."""
    assert "Meteo attuale a Roma (Mantova, Lombardia)" in _meteo(contatore, "Roma, Mantova")


def test_precisazione_senza_corrispondenze(contatore):
    """Precisazione senza corrispondenze: errore con le localita' trovate, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Roma, Toscana", richieste=richieste)
    assert "con quella precisazione" in str(info.value)
    assert "Roma (Lazio)" in str(info.value) and "Roma (Mantova, Lombardia)" in str(info.value)
    assert _host(richieste, "api") == []


def test_citta_non_trovata(contatore):
    """Geocoding vuoto: CittaNonTrovata con il nome cercato, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Xyzqwk", geo=GEO_VUOTO, richieste=richieste)
    # prima il "non trovata", poi il controllo del nome: il modello non deve ridurlo a "solo Italia"
    assert str(info.value).startswith(
        "Città non trovata: nessuna città italiana chiamata «Xyzqwk»: controlla il nome")
    assert _host(richieste, "api") == []


@pytest.mark.parametrize("city", ["", "   "])
def test_citta_predefinita(contatore, monkeypatch, city):
    """city vuota o di soli spazi: si usa Roma e lo si dichiara."""
    monkeypatch.delenv("CITTA_PREDEFINITA", raising=False)
    richieste = []
    testo = _meteo(contatore, city, richieste=richieste)
    assert testo.startswith("Nessuna città indicata: uso la città predefinita, Roma.")
    assert _host(richieste, "geocoding")[0].url.params["name"] == "Roma"


def test_citta_predefinita_da_variabile(contatore, monkeypatch):
    """CITTA_PREDEFINITA sostituisce Roma come citta' predefinita."""
    monkeypatch.setenv("CITTA_PREDEFINITA", "Torino")
    richieste = []
    testo = _meteo(contatore, "", geo=geo_con(luogo("Torino", "Piemonte", "Torino", 870000)),
                   richieste=richieste)
    assert "città predefinita, Torino." in testo
    assert _host(richieste, "geocoding")[0].url.params["name"] == "Torino"


def test_citta_predefinita_senza_alternative(contatore, monkeypatch):
    """Con la citta' predefinita non si chiede quale omonimo: e' una scelta voluta."""
    monkeypatch.setenv("CITTA_PREDEFINITA", "San Giovanni")
    testo = _meteo(contatore, "", geo=GEO_SAN_GIOVANNI)
    assert "Altre località" not in testo and "Chiedi" not in testo


def test_citta_troppo_lunga(contatore):
    """city oltre 100 caratteri -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        _meteo(contatore, "x" * 101)


@pytest.mark.parametrize("days", [1, 3, 7])
def test_days(contatore, days):
    """days=N: N righe di previsione, la prima e' "oggi", la seconda "domani"."""
    testo = _meteo(contatore, "Roma", days=days)
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert len(righe) == days
    assert righe[0] == ("- oggi, giovedì 5 novembre 2026: coperto, minima 9,1 °C, "
                        "massima 17,4 °C, pioggia 10 %")
    if days > 1:
        assert righe[1].startswith("- domani, venerdì 6 novembre 2026: pioggia debole, ")
    if days == 7:
        assert righe[6].startswith("- mercoledì 11 novembre 2026: ")


@pytest.mark.parametrize("days", [8, -1, True])
def test_days_fuori_intervallo(contatore, days):
    """days fuori da 0-7 o booleano -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        _meteo(contatore, "Roma", days=days)


def test_wmo_sconosciuto(contatore):
    """Un codice WMO sconosciuto non e' un errore: "condizione non riconosciuta"."""
    dati = meteo_copia()
    dati["current"]["weather_code"] = 42
    assert "- Condizioni: condizione non riconosciuta (codice WMO 42)" in _meteo(
        contatore, "Roma", meteo=dati)


def _senza_current(d):
    """Guasto: manca il blocco current."""
    del d["current"]


def _temperatura_testo(d):
    """Guasto: la temperatura e' un testo."""
    d["current"]["temperature_2m"] = "dieci"


def _liste_diverse(d):
    """Guasto: le liste giornaliere hanno lunghezze diverse."""
    d["daily"]["temperature_2m_max"] = [17.4]


def _senza_unita(d):
    """Guasto: mancano le unita' del meteo attuale."""
    del d["current_units"]


@pytest.mark.parametrize("guasto", [_senza_current, _temperatura_testo, _liste_diverse,
                                    _senza_unita])
def test_campi_mancanti_nel_meteo(contatore, guasto):
    """Campi mancanti, di tipo sbagliato o liste incoerenti -> RispostaNonValida."""
    dati = meteo_copia()
    guasto(dati)
    with pytest.raises(errori.RispostaNonValida):
        _meteo(contatore, "Roma", days=3, meteo=dati)


def test_latitudine_mancante_nel_geocoding(contatore):
    """Un luogo senza latitudine -> RispostaNonValida."""
    roma = dict(GEO_ROMA["results"][0])
    del roma["latitude"]
    with pytest.raises(errori.RispostaNonValida):
        _meteo(contatore, "Roma", geo=geo_con(roma))


def test_pioggia_nulla(contatore):
    """Probabilita' di pioggia nulla in un giorno -> "pioggia n.d.", non un errore."""
    dati = meteo_copia()
    dati["daily"]["precipitation_probability_max"][0] = None
    testo = _meteo(contatore, "Roma", days=2, meteo=dati)
    assert "massima 17,4 °C, pioggia n.d." in testo


@pytest.mark.parametrize("nome, regione, provincia", [
    ("Forlì", "Emilia-Romagna", "Provincia di Forlì-Cesena"),
    ("L'Aquila", "Abruzzo", "Provincia dell'Aquila")])
def test_accenti_e_apostrofi(contatore, nome, regione, provincia):
    """Nomi con accenti e apostrofi arrivano intatti a Open-Meteo e nell'etichetta."""
    richieste = []
    testo = _meteo(contatore, nome, geo=geo_con(luogo(nome, regione, provincia, 100000)),
                   richieste=richieste)
    assert _host(richieste, "geocoding")[0].url.params["name"] == nome
    assert f"Meteo attuale a {nome} (" in testo and f"{regione})" in testo


def test_provincia_uguale_al_nome_non_ripetuta(contatore):
    """Se la provincia ha il nome della citta' si scrive solo la regione: "Roma (Lazio)"."""
    testo = _meteo(contatore, "Roma")
    assert "Roma (Lazio)" in testo and "Roma (Roma" not in testo


def test_limite_a_meta(tmp_path):
    """Limite raggiunto dopo il geocoding: errore e nessuna richiesta al meteo."""
    contatore = Contatore(tmp_path / "c.sqlite", 1, lambda: ISTANTE)
    richieste = []
    with pytest.raises(errori.LimiteRaggiunto):
        _meteo(contatore, "Roma", richieste=richieste)
    assert len(richieste) == 1 and _host(richieste, "geocoding")


def test_errore_di_rete_non_e_citta_non_trovata(contatore):
    """Rete assente durante il geocoding: errore di rete, non "citta' non trovata"."""
    with pytest.raises(errori.ReteNonRaggiungibile):
        _meteo(contatore, "Roma", geo=httpx.ConnectError("rete assente"))


def test_apostrofo_tipografico_nella_provincia(contatore):
    """Open-Meteo scrive "Provincia dell’Aquila" con l'apostrofo tipografico: si toglie lo stesso."""
    geo = geo_con(luogo("L'Aquila", "Abruzzo", "Provincia dell’Aquila", 69000))
    assert "Meteo attuale a L'Aquila (Abruzzo)" in _meteo(contatore, "L'Aquila", geo=geo)


def test_piccola_localita_dichiarata(contatore):
    """Una localita' sotto i 1000 abitanti si dichiara: "Parigi" in Italia e' una frazione."""
    geo = geo_con(luogo("Parigi", "Veneto", "Provincia di Vicenza", 31))
    testo = _meteo(contatore, "Parigi", geo=geo)
    assert ("Parigi (Vicenza, Veneto) è una piccola località (31 abitanti): se l'utente "
            "intendeva una città estera, il servizio meteo copre solo l'Italia.") in testo


def test_abitanti_sconosciuti_dichiarati(contatore):
    """Senza il numero di abitanti la localita' si dichiara come piccola o sconosciuta."""
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", None))
    assert ("Borgo (Verona, Veneto) è una piccola località (abitanti non indicati)"
            in _meteo(contatore, "Borgo", geo=geo))


def test_citta_grande_senza_avviso(contatore):
    """Sopra i 1000 abitanti nessun avviso."""
    assert "piccola località" not in _meteo(contatore, "Roma")
