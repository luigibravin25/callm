import pytest
from app import conversioni as cv
from app.conversioni import ErroreConversione, riconosci

def test_riconosce_simbolo_singolare_plurale():
    assert riconosci("km").simbolo == "km"
    assert riconosci("chilometro").simbolo == "km"
    assert riconosci("  Chilometri ").simbolo == "km"
    assert riconosci("gradi celsius").simbolo == "°C"
    assert riconosci("GRADI CELSIUS").simbolo == "°C"

def test_varianti_ascii_e_unicode():
    for t in ("m/s²", "m/s^2", "m/s2"): assert riconosci(t).simbolo == "m/s²"
    for t in ("µm", "μm", "um"): assert riconosci(t).simbolo == "µm"
    for t in ("°C", "degC"): assert riconosci(t).simbolo == "°C"
    for t in ("m²", "m2", "metri quadrati"): assert riconosci(t).simbolo == "m²"

def test_simboli_solo_esatti():
    assert riconosci("Gal").grandezza == "accelerazione"
    assert riconosci("mbar").simbolo == "mbar" and riconosci("MB").simbolo == "MB"
    for t in ("Cal", "NM", "KB"):
        with pytest.raises(ErroreConversione, match="non ammessa"):
            riconosci(t)

def test_ambiguita_esplicita():
    for t in ("gallone", "galloni", "pinta"):
        with pytest.raises(ErroreConversione, match="ambigua"):
            riconosci(t)
    with pytest.raises(ErroreConversione) as e:
        riconosci("gallone")
    assert "gal US" in str(e.value) and "gal UK" in str(e.value)
    assert riconosci("tonnellata").simbolo == "t"
    assert riconosci("oncia").grandezza == "massa"
    assert riconosci("oncia fluida").grandezza == "volume"
    assert riconosci("g").grandezza == "massa" and riconosci("g0").grandezza == "accelerazione"

def test_unita_non_ammessa_e_vuota():
    for t in ("parsec", "", "   "):
        with pytest.raises(ErroreConversione, match="Unità non ammessa") as e:
            riconosci(t)
        assert "lunghezza" in str(e.value)

def test_elenco_chiuso_e_nessuna_collisione():
    assert cv.GRANDEZZE == ("lunghezza", "massa", "tempo", "temperatura", "area", "volume",
        "velocità", "accelerazione", "forza", "pressione", "energia", "potenza",
        "frequenza", "angolo", "densità", "portata", "dati digitali")
    assert {u.grandezza for u in cv.UNITA} == set(cv.GRANDEZZE)
    simboli = [s for u in cv.UNITA for s in (u.simbolo, *u.simboli)]
    assert len(simboli) == len(set(simboli))  # simbolo esatto -> una sola unità
    # unici nomi condivisi ammessi: quelli voluti ambigui
    condivisi = {n for n in {cv.normalizza(x) for u in cv.UNITA for x in (u.singolare, u.plurale, *u.nomi)}
                 if sum(n in {cv.normalizza(x) for x in (u.singolare, u.plurale, *u.nomi)} for u in cv.UNITA) > 1}
    assert condivisi <= {"gallone", "galloni", "pinta", "pinte"}

from app.conversioni import converti, formatta_numero

def test_formatta_numero():
    casi = {0.0: "0", -0.0: "0", 0.5: "0,5", 273.15: "273,15", 3.106855961: "3,10686",
            1609.344: "1609,34", 1_000_000: "1000000", 1_234_567: "1234570", -40: "-40",
            0.0001: "0,0001", 1.5e-9: "1,5 × 10^-9", 2.5e12: "2,5 × 10^12",
            1.602176634e-19: "1,60218 × 10^-19"}
    for x, atteso in casi.items():
        assert formatta_numero(x) == atteso, x

@pytest.mark.parametrize("valore,da,a,atteso", [
    (10, "miglia", "km", "10 miglia = 16,0934 chilometri"),
    (1, "lb", "kg", "1 libbra = 0,453592 chilogrammi"),
    (1, "settimana", "h", "1 settimana = 168 ore"),
    (0, "°C", "°F", "0 gradi Celsius = 32 gradi Fahrenheit"),
    (0, "°C", "K", "0 gradi Celsius = 273,15 kelvin"),
    (-40, "°C", "°F", "-40 gradi Celsius = -40 gradi Fahrenheit"),
    (100, "°C", "°R", "100 gradi Celsius = 671,67 gradi Rankine"),
    (1, "ha", "m²", "1 ettaro = 10000 metri quadrati"),
    (1, "gal US", "L", "1 gallone US = 3,78541 litri"),
    (36, "km/h", "m/s", "36 chilometri orari = 10 metri al secondo"),
    (9.80665, "m/s²", "g0", "9,80665 metri al secondo quadrato = 1 accelerazione di gravità"),
    (1, "kgf", "N", "1 chilogrammo-forza = 9,80665 newton"),
    (1, "bar", "psi", "1 bar = 14,5038 psi"),
    (1, "kWh", "J", "1 chilowattora = 3600000 joule"),
    (1, "CV", "W", "1 cavallo vapore = 735,499 watt"),
    (60, "rpm", "Hz", "60 giri al minuto = 1 hertz"),
    (1, "giro", "°", "1 giro = 360 gradi"),
    (1, "g/cm³", "kg/m³", "1 grammo per centimetro cubo = 1000 chilogrammi per metro cubo"),
    (1, "m³/h", "L/min", "1 metro cubo all'ora = 16,6667 litri al minuto"),
    (1, "MiB", "kB", "1 mebibyte = 1048,58 kilobyte"),
])
def test_una_conversione_per_grandezza(valore, da, a, atteso):
    assert converti(valore, da, a) == atteso

def test_errori_di_conversione():
    with pytest.raises(ErroreConversione, match=r"Conversione incompatibile: chilometri \(lunghezza\) → chilogrammi \(massa\)\."):
        converti(5, "km", "kg")
    with pytest.raises(ErroreConversione, match="zero assoluto"):
        converti(-300, "°C", "K")
    with pytest.raises(ErroreConversione, match="numero finito"):
        converti(float("nan"), "m", "km")
    with pytest.raises(ErroreConversione, match="numero finito"):
        converti(float("inf"), "m", "km")
    assert converti(0, "K", "°C") == "0 kelvin = -273,15 gradi Celsius"

def test_stessa_unita_e_negativi():
    assert converti(-5, "m", "cm") == "-5 metri = -500 centimetri"
    assert converti(1, "m", "metri") == "1 metro = 1 metro"

def test_zero_di_temperatura_senza_residui():
    assert converti(491.67, "°R", "°C") == "491,67 gradi Rankine = 0 gradi Celsius"
    assert converti(32, "°F", "°C") == "32 gradi Fahrenheit = 0 gradi Celsius"
    assert converti(273.15, "K", "°C") == "273,15 kelvin = 0 gradi Celsius"

from app import tools

def test_strumento_e_schema():
    assert tools.converti_unita.name == "toolconvert"
    assert set(tools.converti_unita.args) == {"valore", "da", "a"}
    d = tools.converti_unita.description
    assert "esattamente come scritto" in d and "senza inventare" in d

def test_strumento_restituisce_testo_anche_per_errori():
    assert tools.converti_unita.invoke({"valore": 10, "da": "miglia", "a": "km"}) == \
        "10 miglia = 16,0934 chilometri"
    assert tools.converti_unita.invoke({"valore": 5, "da": "km", "a": "kg"}).startswith(
        "Conversione incompatibile")
    assert tools.converti_unita.invoke({"valore": 1, "da": "parsec", "a": "m"}).startswith(
        "Unità non ammessa")

def test_risultato_fuori_intervallo_e_un_errore():
    for valore, da, a in ((1e308, "ly", "nm"), (1e300, "TB", "bit"), (1e308, "m", "nm")):
        with pytest.raises(ErroreConversione, match="fuori dall'intervallo"):
            converti(valore, da, a)

def test_zero_assoluto_dal_lato_di_partenza():
    assert converti(-459.67, "°F", "K") == "-459,67 gradi Fahrenheit = 0 kelvin"
    assert converti(-459.67, "°F", "°R") == "-459,67 gradi Fahrenheit = 0 gradi Rankine"
    assert converti(-273.15, "°C", "K") == "-273,15 gradi Celsius = 0 kelvin"

def test_centigradi_e_simbolo_minuscolo():
    for t in ("centigrado", "centigradi", "grado centigrado", "Gradi Centigradi", "°c"):
        assert riconosci(t).simbolo == "°C", t

def test_risultato_minuscolo_vero_non_azzerato():
    assert not converti(273.1500000001, "K", "°C").endswith(" = 0 gradi Celsius")
    assert not converti(-273.1499999999, "°C", "K").endswith(" = 0 kelvin")
