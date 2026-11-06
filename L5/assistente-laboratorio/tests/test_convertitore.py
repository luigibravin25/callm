# Test del convertitore di unita' (app/conversioni.py) e dello strumento `toolconvert`.
# pytest, il modulo delle conversioni, la sua eccezione e la funzione che riconosce un'unita'
import pytest
from app import conversioni as cv
from app.conversioni import ErroreConversione, riconosci

# Verifica che un'unita' si riconosca da simbolo, singolare o plurale, senza badare a
# maiuscole e spazi intorno.
def test_riconosce_simbolo_singolare_plurale():
    assert riconosci("km").simbolo == "km"
    assert riconosci("chilometro").simbolo == "km"
    assert riconosci("  Chilometri ").simbolo == "km"
    assert riconosci("gradi celsius").simbolo == "°C"
    assert riconosci("GRADI CELSIUS").simbolo == "°C"

# Verifica che le varianti scritte da tastiera (m/s^2, um, degC, m2) valgano come i simboli
# Unicode (m/s², µm, °C, m²): l'utente non deve cercare i caratteri speciali.
def test_varianti_ascii_e_unicode():
    for t in ("m/s²", "m/s^2", "m/s2"): assert riconosci(t).simbolo == "m/s²"
    for t in ("µm", "μm", "um"): assert riconosci(t).simbolo == "µm"
    for t in ("°C", "degC"): assert riconosci(t).simbolo == "°C"
    for t in ("m²", "m2", "metri quadrati"): assert riconosci(t).simbolo == "m²"

# Verifica che i simboli contino maiuscole e minuscole: "Gal" (accelerazione) non e' "gal",
# "MB" non e' "mbar"; varianti come "Cal", "NM", "KB" sono rifiutate.
def test_simboli_solo_esatti():
    assert riconosci("Gal").grandezza == "accelerazione"
    assert riconosci("mbar").simbolo == "mbar" and riconosci("MB").simbolo == "MB"
    # controllo: un simbolo con le maiuscole sbagliate da' "non ammessa"
    for t in ("Cal", "NM", "KB"):
        with pytest.raises(ErroreConversione, match="non ammessa"):
            riconosci(t)

# Verifica che i nomi ambigui (gallone, pinta: US o UK?) diano un errore che propone le
# alternative, invece di sceglierne una a caso; i nomi non ambigui funzionano.
def test_ambiguita_esplicita():
    for t in ("gallone", "galloni", "pinta"):
        with pytest.raises(ErroreConversione, match="ambigua"):
            riconosci(t)
    # controllo: il messaggio elenca le due possibilita'
    with pytest.raises(ErroreConversione) as e:
        riconosci("gallone")
    assert "gal US" in str(e.value) and "gal UK" in str(e.value)
    # nomi simili ma distinti: oncia (massa) e oncia fluida (volume), g e g0
    assert riconosci("tonnellata").simbolo == "t"
    assert riconosci("oncia").grandezza == "massa"
    assert riconosci("oncia fluida").grandezza == "volume"
    assert riconosci("g").grandezza == "massa" and riconosci("g0").grandezza == "accelerazione"

# Verifica che un'unita' fuori elenco o vuota sia rifiutata con l'elenco delle grandezze.
def test_unita_non_ammessa_e_vuota():
    for t in ("parsec", "", "   "):
        with pytest.raises(ErroreConversione, match="Unità non ammessa") as e:
            riconosci(t)
        # controllo: il messaggio mostra le grandezze ammesse (qui basta "lunghezza")
        assert "lunghezza" in str(e.value)

# Verifica l'elenco chiuso: le 17 grandezze previste, ognuna con almeno un'unita', e nessun
# simbolo o nome che porti a due unita' diverse (tranne gli ambigui voluti).
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

# funzioni della conversione vera e propria e della scrittura dei numeri
from app.conversioni import converti, formatta_numero

# Verifica la scrittura dei numeri all'italiana: virgola decimale, 6 cifre significative,
# notazione "× 10^" per numeri molto piccoli o grandi, niente "-0".
def test_formatta_numero():
    casi = {0.0: "0", -0.0: "0", 0.5: "0,5", 273.15: "273,15", 3.106855961: "3,10686",
            1609.344: "1609,34", 1_000_000: "1000000", 1_234_567: "1234570", -40: "-40",
            0.0001: "0,0001", 1.5e-9: "1,5 × 10^-9", 2.5e12: "2,5 × 10^12",
            1.602176634e-19: "1,60218 × 10^-19"}
    for x, atteso in casi.items():
        assert formatta_numero(x) == atteso, x

# Verifica almeno una conversione per ogni grandezza, con il testo completo della risposta
# (nomi delle unita' al singolare o al plurale). Ogni riga: valore, da, a, risultato atteso.
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

# Verifica gli errori: grandezze incompatibili, temperatura sotto lo zero assoluto, valori non
# finiti (nan, inf). Lo zero assoluto esatto (0 K) invece e' ammesso.
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

# Verifica i valori negativi e la conversione verso la stessa unita' (scritta in modi diversi).
def test_stessa_unita_e_negativi():
    assert converti(-5, "m", "cm") == "-5 metri = -500 centimetri"
    assert converti(1, "m", "metri") == "1 metro = 1 metro"

# Verifica che lo zero di arrivo sia "0" pulito, senza residui di arrotondamento (es. 1e-14).
def test_zero_di_temperatura_senza_residui():
    assert converti(491.67, "°R", "°C") == "491,67 gradi Rankine = 0 gradi Celsius"
    assert converti(32, "°F", "°C") == "32 gradi Fahrenheit = 0 gradi Celsius"
    assert converti(273.15, "K", "°C") == "273,15 kelvin = 0 gradi Celsius"

# il modulo degli strumenti, per provare `toolconvert` come lo vede il modello
from app import tools

# Verifica nome, argomenti e descrizione dello strumento: la descrizione chiede al modello di
# passare le unita' come scritte dall'utente, senza inventare.
def test_strumento_e_schema():
    assert tools.converti_unita.name == "toolconvert"
    assert set(tools.converti_unita.args) == {"valore", "da", "a"}
    d = tools.converti_unita.description
    assert "esattamente come scritto" in d and "senza inventare" in d

# Verifica che lo strumento restituisca sempre un testo, anche per gli errori: niente eccezioni
# verso il grafo, il modello riceve il messaggio da riferire.
def test_strumento_restituisce_testo_anche_per_errori():
    assert tools.converti_unita.invoke({"valore": 10, "da": "miglia", "a": "km"}) == \
        "10 miglia = 16,0934 chilometri"
    assert tools.converti_unita.invoke({"valore": 5, "da": "km", "a": "kg"}).startswith(
        "Conversione incompatibile")
    assert tools.converti_unita.invoke({"valore": 1, "da": "parsec", "a": "m"}).startswith(
        "Unità non ammessa")

# Verifica che un risultato troppo grande per un float (infinito) sia un errore esplicito.
def test_risultato_fuori_intervallo_e_un_errore():
    for valore, da, a in ((1e308, "ly", "nm"), (1e300, "TB", "bit"), (1e308, "m", "nm")):
        with pytest.raises(ErroreConversione, match="fuori dall'intervallo"):
            converti(valore, da, a)

# Verifica che lo zero assoluto esatto nell'unita' di partenza (-459,67 °F, -273,15 °C) sia
# ammesso e dia 0 nell'unita' di arrivo, senza falso errore "sotto lo zero assoluto".
def test_zero_assoluto_dal_lato_di_partenza():
    assert converti(-459.67, "°F", "K") == "-459,67 gradi Fahrenheit = 0 kelvin"
    assert converti(-459.67, "°F", "°R") == "-459,67 gradi Fahrenheit = 0 gradi Rankine"
    assert converti(-273.15, "°C", "K") == "-273,15 gradi Celsius = 0 kelvin"

# Verifica che "centigradi" e "°c" minuscolo valgano come gradi Celsius (modi d'uso comuni).
def test_centigradi_e_simbolo_minuscolo():
    for t in ("centigrado", "centigradi", "grado centigrado", "Gradi Centigradi", "°c"):
        assert riconosci(t).simbolo == "°C", t

# Verifica il caso opposto: un risultato vicino a zero ma non nullo non va scritto come 0.
def test_risultato_minuscolo_vero_non_azzerato():
    assert not converti(273.1500000001, "K", "°C").endswith(" = 0 gradi Celsius")
    assert not converti(-273.1499999999, "°C", "K").endswith(" = 0 kelvin")
