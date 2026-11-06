"""Test della traduzione del meteo: scelta della citta' italiana, omonimi, previsioni, testo.

Risposte di Open-Meteo simulate (tests/meteo_finto.py), istante fisso: nessuna rete.
"""
# date con fuso, per l'istante fisso
from datetime import datetime, timezone

# httpx (per simulare un errore di rete) e pytest
import httpx
import pytest

# il codice da verificare e i dati finti di Open-Meteo
from mcp_meteo import errori
# il modulo, non la funzione: un nome importato che inizia con "test" (testo_meteo) verrebbe
# raccolto da pytest come se fosse un test
from mcp_meteo import meteo as modulo_meteo
from mcp_meteo.contatore import Contatore
from mcp_meteo.meteo import FONTE
from tests.meteo_finto import (GEO_PARIS_IT, GEO_ROMA, GEO_SAN_GIOVANNI, GEO_VUOTO,
                               METEO_ESEMPIO, client_finto, geo_con, luogo, meteo_copia)

ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # giovedi' 5 novembre 2026


# autouse: vale per ogni test del file; "oggi" e' sempre il 5 novembre 2026
@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    """Istante fisso per tutti i test del file."""
    monkeypatch.setattr("mcp_meteo.meteo._adesso", lambda: ISTANTE)


# contatore delle richieste in un file temporaneo: il limite vero non si consuma
@pytest.fixture
def contatore(tmp_path):
    """Contatore vero su un file temporaneo, limite 1000."""
    return Contatore(tmp_path / "c.sqlite", 1000, lambda: ISTANTE)


# scorciatoia: chiede il meteo con le risposte finte scelte dal test
def _meteo(contatore, city, days=0, geo=GEO_ROMA, meteo=METEO_ESEMPIO, richieste=None):
    """Chiama testo_meteo con il client finto (nessuna data)."""
    client = client_finto(geo=geo, meteo=meteo, richieste=richieste)
    return modulo_meteo.testo_meteo(city, days, "", client, contatore)


# filtra le richieste registrate: geocoding oppure meteo
def _host(richieste, prefisso):
    """Richieste inviate a un host (prefisso "geocoding" o "api")."""
    return [r for r in richieste if r.url.host.startswith(prefisso)]


# --- il testo del risultato ---

# il testo per il modello contiene tutte le informazioni richieste, con la fonte in fondo
def test_risultato_completo(contatore):
    """Meteo attuale: citta', temperatura con unita', condizioni, ora con fuso, fonte."""
    testo = _meteo(contatore, "Roma")
    assert "Meteo attuale a Roma (Lazio)" in testo
    assert "- Temperatura: 10,5 °C" in testo
    assert "- Condizioni: coperto" in testo
    assert "- Ora di riferimento: 2026-11-05 19:45, ora locale Europe/Rome (GMT+1)" in testo
    assert testo.rstrip().endswith(FONTE)
    assert "Previsioni:" not in testo  # days=0: solo meteo attuale


# se l'API cambia unita' il testo la segue (qui °F al posto di °C)
def test_unita_dalla_risposta(contatore):
    """L'unita' della temperatura viene dalla risposta, non e' scritta nel codice."""
    dati = meteo_copia()  # copia: l'esempio originale resta intatto per gli altri test
    dati["current_units"]["temperature_2m"] = "°F"
    assert "- Temperatura: 10,5 °F" in _meteo(contatore, "Roma", meteo=dati)


# --- scelta tra luoghi con lo stesso nome ---

# tra omonimi vince il piu' abitato (Catania, 1789), non il primo della lista (Savona, 316)
def test_sceglie_la_piu_popolosa(contatore):
    """Tra gli omonimi si sceglie il piu' popoloso, anche se Open-Meteo lo mette dopo."""
    richieste = []  # qui il client finto registra le richieste fatte
    testo = _meteo(contatore, "San Giovanni", geo=GEO_SAN_GIOVANNI, richieste=richieste)
    assert "Meteo attuale a San Giovanni (Catania, Sicilia)" in testo
    # coordinate della San Giovanni siciliana nella richiesta del meteo
    assert _host(richieste, "api")[0].url.params["latitude"] == "37.6"


# il testo elenca gli altri omonimi e suggerisce al modello di chiedere all'utente
def test_omonimi_dichiarati(contatore):
    """Omonimi reali: 3 elencati per abitanti, gli altri contati, e la domanda all'utente."""
    testo = _meteo(contatore, "San Giovanni", geo=GEO_SAN_GIOVANNI)
    assert ("Altre località con questo nome: San Giovanni (Pordenone, Friuli Venezia Giulia); "
            "San Giovanni (Ferrara, Emilia-Romagna); San Giovanni (Teramo, Abruzzo) "
            "e altre 2.") in testo
    assert ("Chiedi all'utente quale preferisce: può scrivere per esempio "
            '"San Giovanni, Pordenone".') in testo


# soglia del 5%: le frazioni minuscole non disturbano con domande inutili
def test_alternative_dal_cinque_per_cento(contatore):
    """Un omonimo con meno del 5% degli abitanti della scelta non e' un'alternativa."""
    # geocoding su misura: 10000 abitanti la scelta, 400 e 600 gli omonimi
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", 10000),
                  luogo("Borgo", "Toscana", "Provincia di Siena", 400),     # 4%: scartato
                  luogo("Borgo", "Marche", "Provincia di Ancona", 600))     # 6%: alternativa
    testo = _meteo(contatore, "Borgo", geo=geo)
    assert "Altre località con questo nome: Borgo (Ancona, Marche)." in testo
    assert "Siena" not in testo


# un luogo senza il campo population non rompe la scelta
def test_popolazione_assente(contatore):
    """Abitanti mancanti valgono 0: non battono la scelta e non superano la soglia."""
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", None),
                  luogo("Borgo", "Marche", "Provincia di Ancona", 1000),
                  luogo("Borgo", "Toscana", "Provincia di Siena", None))
    testo = _meteo(contatore, "Borgo", geo=geo)
    assert "Meteo attuale a Borgo (Ancona, Marche)" in testo
    assert "Altre località" not in testo


# con un solo luogo trovato non c'e' nulla da chiedere
def test_un_solo_risultato_senza_alternative(contatore):
    """Una sola citta' trovata: nessuna alternativa e nessuna domanda."""
    testo = _meteo(contatore, "Roma", geo=geo_con(GEO_ROMA["results"][0]))  # solo la capitale
    assert "Altre località" not in testo and "Chiedi" not in testo


# il caso reale di "Roma": la frazione mantovana e "Romana" non sono alternative
def test_roma_senza_alternative(contatore):
    """Roma (Mantova, 87 abitanti) e' sotto il 5%; "Romana" non ha lo stesso nome."""
    testo = _meteo(contatore, "Roma")
    assert "Altre località" not in testo
    assert "Mantova" not in testo and "Romana" not in testo


# --- citta' estere e precisazioni ---

# "Paris" non deve diventare "Parise" (Trento): errore che spiega che il servizio e' solo italiano
def test_citta_estera(contatore):
    """Una citta' estera (solo nomi simili in Italia) -> non trovata, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Paris", geo=GEO_PARIS_IT, richieste=richieste)
    assert "solo per le città italiane" in str(info.value) and "Paris" in str(info.value)
    assert _host(richieste, "api") == []  # nessuna richiesta all'API del meteo


# "nome, regione" o "nome, provincia" (maiuscole libere) sceglie l'omonimo voluto
@pytest.mark.parametrize("city", ["San Giovanni, Friuli Venezia Giulia",
                                  "san giovanni, pordenone",
                                  "San Giovanni, Provincia di Pordenone"])
def test_precisazione(contatore, city):
    """Regione o provincia dopo la virgola scelgono l'omonimo; a Open-Meteo va solo il nome."""
    richieste = []
    testo = _meteo(contatore, city, geo=GEO_SAN_GIOVANNI, richieste=richieste)
    assert "Meteo attuale a San Giovanni (Pordenone, Friuli Venezia Giulia)" in testo
    # al geocoding va solo la parte prima della virgola
    assert _host(richieste, "geocoding")[0].url.params["name"] == city.split(",")[0]
    assert "Altre località" not in testo  # resta un solo candidato


# la precisazione vince sulla soglia del 5%: si puo' chiedere la frazione piccola
def test_precisazione_sceglie_anche_una_frazione(contatore):
    """Con la precisazione si puo' chiedere anche l'omonimo piccolo (Roma in provincia di Mantova)."""
    assert "Meteo attuale a Roma (Mantova, Lombardia)" in _meteo(contatore, "Roma, Mantova")


# una precisazione sbagliata non sceglie a caso: errore con i luoghi possibili
def test_precisazione_senza_corrispondenze(contatore):
    """Precisazione senza corrispondenze: errore con le localita' trovate, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Roma, Toscana", richieste=richieste)
    assert "con quella precisazione" in str(info.value)
    assert "Roma (Lazio)" in str(info.value) and "Roma (Mantova, Lombardia)" in str(info.value)
    assert _host(richieste, "api") == []


# nome inesistente: errore "Città non trovata" che invita a controllare il nome
def test_citta_non_trovata(contatore):
    """Geocoding vuoto: CittaNonTrovata con il nome cercato, nessun meteo chiesto."""
    richieste = []
    with pytest.raises(errori.CittaNonTrovata) as info:
        _meteo(contatore, "Xyzqwk", geo=GEO_VUOTO, richieste=richieste)
    # prima il "non trovata", poi il controllo del nome: il modello non deve ridurlo a "solo Italia"
    assert str(info.value).startswith(
        "Città non trovata: nessuna città italiana chiamata «Xyzqwk»: controlla il nome")
    assert _host(richieste, "api") == []


# --- citta' predefinita ---

# senza citta' si usa la riserva Roma e il testo lo dice (l'utente sa di che citta' si parla)
@pytest.mark.parametrize("city", ["", "   "])
def test_citta_predefinita(contatore, monkeypatch, city):
    """city vuota o di soli spazi: si usa Roma e lo si dichiara."""
    monkeypatch.delenv("CITTA_PREDEFINITA", raising=False)  # nessuna variabile: vale Roma
    richieste = []
    testo = _meteo(contatore, city, richieste=richieste)
    assert testo.startswith("Nessuna città indicata: uso la città predefinita, Roma.")
    assert _host(richieste, "geocoding")[0].url.params["name"] == "Roma"


# la variabile d'ambiente cambia la citta' predefinita
def test_citta_predefinita_da_variabile(contatore, monkeypatch):
    """CITTA_PREDEFINITA sostituisce Roma come citta' predefinita."""
    monkeypatch.setenv("CITTA_PREDEFINITA", "Torino")
    richieste = []
    testo = _meteo(contatore, "", geo=geo_con(luogo("Torino", "Piemonte", "Torino", 870000)),
                   richieste=richieste)
    assert "città predefinita, Torino." in testo
    assert _host(richieste, "geocoding")[0].url.params["name"] == "Torino"


# per la citta' predefinita non si propongono omonimi
def test_citta_predefinita_senza_alternative(contatore, monkeypatch):
    """Con la citta' predefinita non si chiede quale omonimo: e' una scelta voluta."""
    monkeypatch.setenv("CITTA_PREDEFINITA", "San Giovanni")
    testo = _meteo(contatore, "", geo=GEO_SAN_GIOVANNI)
    assert "Altre località" not in testo and "Chiedi" not in testo


# --- argomenti e previsioni ---

# un nome troppo lungo e' rifiutato prima di chiamare l'API
def test_citta_troppo_lunga(contatore):
    """city oltre 100 caratteri -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        _meteo(contatore, "x" * 101)


# days=N da' N giorni di previsione, oggi compreso, con data in italiano
@pytest.mark.parametrize("days", [1, 3, 7])
def test_days(contatore, days):
    """days=N: N righe di previsione, la prima e' "oggi", la seconda "domani"."""
    testo = _meteo(contatore, "Roma", days=days)
    # le righe dell'elenco dopo "Previsioni:"
    righe = [r for r in testo.split("Previsioni:\n")[1].split("\n") if r.startswith("- ")]
    assert len(righe) == days
    assert righe[0] == ("- oggi, giovedì 5 novembre 2026: coperto, minima 9,1 °C, "
                        "massima 17,4 °C, pioggia 10 %")
    if days > 1:
        assert righe[1].startswith("- domani, venerdì 6 novembre 2026: pioggia debole, ")
    if days == 7:
        assert righe[6].startswith("- mercoledì 11 novembre 2026: ")


# Open-Meteo da' al massimo 7 giorni affidabili: oltre, o un booleano, e' un errore
@pytest.mark.parametrize("days", [8, -1, True])
def test_days_fuori_intervallo(contatore, days):
    """days fuori da 0-7 o booleano -> ArgomentoNonValido."""
    with pytest.raises(errori.ArgomentoNonValido):
        _meteo(contatore, "Roma", days=days)


# un codice meteo nuovo non blocca la risposta: si mostra con il suo numero
def test_wmo_sconosciuto(contatore):
    """Un codice WMO sconosciuto non e' un errore: "condizione non riconosciuta"."""
    dati = meteo_copia()
    dati["current"]["weather_code"] = 42  # codice che non esiste nella tabella WMO
    assert "- Condizioni: condizione non riconosciuta (codice WMO 42)" in _meteo(
        contatore, "Roma", meteo=dati)


# --- risposte rovinate di Open-Meteo ---

# funzioni "guasto": ognuna rovina in un modo diverso una copia della risposta del meteo
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


# una risposta rovinata da' un errore chiaro invece di un'eccezione Python qualsiasi
@pytest.mark.parametrize("guasto", [_senza_current, _temperatura_testo, _liste_diverse,
                                    _senza_unita])
def test_campi_mancanti_nel_meteo(contatore, guasto):
    """Campi mancanti, di tipo sbagliato o liste incoerenti -> RispostaNonValida."""
    dati = meteo_copia()
    guasto(dati)  # preparazione: si rovina la copia
    with pytest.raises(errori.RispostaNonValida):
        _meteo(contatore, "Roma", days=3, meteo=dati)


# anche una risposta rovinata del geocoding e' RispostaNonValida
def test_latitudine_mancante_nel_geocoding(contatore):
    """Un luogo senza latitudine -> RispostaNonValida."""
    roma = dict(GEO_ROMA["results"][0])  # copia del luogo, senza toccare GEO_ROMA
    del roma["latitude"]
    with pytest.raises(errori.RispostaNonValida):
        _meteo(contatore, "Roma", geo=geo_con(roma))


# un valore null e' normale nell'API: si scrive "n.d." e il resto della risposta resta
def test_temperatura_nulla(contatore):
    """Temperatura nulla in un giorno (capita nell'ultimo giorno) -> "n.d.", non un errore."""
    dati = meteo_copia()
    dati["daily"]["temperature_2m_max"][1] = None  # massima di domani assente
    testo = _meteo(contatore, "Roma", days=2, meteo=dati)
    assert "minima 10,3 °C, massima n.d., pioggia 80 %" in testo


# stessa regola per la probabilita' di pioggia
def test_pioggia_nulla(contatore):
    """Probabilita' di pioggia nulla in un giorno -> "pioggia n.d.", non un errore."""
    dati = meteo_copia()
    dati["daily"]["precipitation_probability_max"][0] = None  # pioggia di oggi assente
    testo = _meteo(contatore, "Roma", days=2, meteo=dati)
    assert "massima 17,4 °C, pioggia n.d." in testo


# --- nomi ed etichette ---

# accenti e apostrofi non si perdono ne' nella richiesta ne' nel testo
@pytest.mark.parametrize("nome, regione, provincia", [
    ("Forlì", "Emilia-Romagna", "Provincia di Forlì-Cesena"),
    ("L'Aquila", "Abruzzo", "Provincia dell'Aquila")])
def test_accenti_e_apostrofi(contatore, nome, regione, provincia):
    """Nomi con accenti e apostrofi arrivano intatti a Open-Meteo e nell'etichetta."""
    richieste = []
    testo = _meteo(contatore, nome, geo=geo_con(luogo(nome, regione, provincia, 100000)),
                   richieste=richieste)
    # il nome arriva intatto al geocoding e compare nell'etichetta con la regione
    assert _host(richieste, "geocoding")[0].url.params["name"] == nome
    assert f"Meteo attuale a {nome} (" in testo and f"{regione})" in testo


# niente "Roma (Roma, Lazio)": la provincia con lo stesso nome non si ripete
def test_provincia_uguale_al_nome_non_ripetuta(contatore):
    """Se la provincia ha il nome della citta' si scrive solo la regione: "Roma (Lazio)"."""
    testo = _meteo(contatore, "Roma")
    assert "Roma (Lazio)" in testo and "Roma (Roma" not in testo


# --- limite e rete ---

# limite 1: il geocoding usa l'unica richiesta, la seconda (il meteo) e' bloccata
def test_limite_a_meta(tmp_path):
    """Limite raggiunto dopo il geocoding: errore e nessuna richiesta al meteo."""
    contatore = Contatore(tmp_path / "c.sqlite", 1, lambda: ISTANTE)
    richieste = []
    with pytest.raises(errori.LimiteRaggiunto):
        _meteo(contatore, "Roma", richieste=richieste)
    assert len(richieste) == 1 and _host(richieste, "geocoding")  # solo il geocoding


# la rete assente non va confusa con una citta' inesistente: sono errori diversi per l'utente
def test_errore_di_rete_non_e_citta_non_trovata(contatore):
    """Rete assente durante il geocoding: errore di rete, non "citta' non trovata"."""
    # il trasporto finto solleva ConnectError, come senza connessione
    with pytest.raises(errori.ReteNonRaggiungibile):
        _meteo(contatore, "Roma", geo=httpx.ConnectError("rete assente"))


# anche con l'apostrofo tipografico (’) la provincia uguale al nome si riconosce
def test_apostrofo_tipografico_nella_provincia(contatore):
    """Open-Meteo scrive "Provincia dell’Aquila" con l'apostrofo tipografico: si toglie lo stesso."""
    geo = geo_con(luogo("L'Aquila", "Abruzzo", "Provincia dell’Aquila", 69000))
    assert "Meteo attuale a L'Aquila (Abruzzo)" in _meteo(contatore, "L'Aquila", geo=geo)


# --- avviso per le piccole localita' ---

# una frazione omonima di una citta' estera: il testo avverte che il servizio e' solo italiano
def test_piccola_localita_dichiarata(contatore):
    """Una localita' sotto i 1000 abitanti si dichiara: "Parigi" in Italia e' una frazione."""
    geo = geo_con(luogo("Parigi", "Veneto", "Provincia di Vicenza", 31))
    testo = _meteo(contatore, "Parigi", geo=geo)
    assert ("Parigi (Vicenza, Veneto) è una piccola località (31 abitanti): se l'utente "
            "intendeva una città estera, il servizio meteo copre solo l'Italia.") in testo


# abitanti non indicati: l'avviso c'e' lo stesso
def test_abitanti_sconosciuti_dichiarati(contatore):
    """Senza il numero di abitanti la localita' si dichiara come piccola o sconosciuta."""
    geo = geo_con(luogo("Borgo", "Veneto", "Provincia di Verona", None))
    assert ("Borgo (Verona, Veneto) è una piccola località (abitanti non indicati)"
            in _meteo(contatore, "Borgo", geo=geo))


# per una citta' grande nessun avviso inutile
def test_citta_grande_senza_avviso(contatore):
    """Sopra i 1000 abitanti nessun avviso."""
    assert "piccola località" not in _meteo(contatore, "Roma")
