"""Convertitore di unità: elenco chiuso, riconoscimento dei nomi, conversione.

Modulo senza LangChain. Ogni unità converte verso l'unità di base della sua
grandezza con ``base = valore * fattore + offset`` (l'offset serve solo alle
temperature).
"""

import math
import unicodedata
from dataclasses import dataclass


class ErroreConversione(ValueError):
    """Errore di conversione; il messaggio è il testo da restituire al modello."""


@dataclass(frozen=True)
class Unita:
    simbolo: str  # simbolo principale, usato nei messaggi
    grandezza: str
    singolare: str
    plurale: str
    fattore: float
    offset: float = 0.0
    simboli: tuple[str, ...] = ()  # varianti esatte del simbolo
    nomi: tuple[str, ...] = ()  # alias in parole, confrontati dopo normalizza()


GRANDEZZE: tuple[str, ...] = (
    "lunghezza", "massa", "tempo", "temperatura", "area", "volume",
    "velocità", "accelerazione", "forza", "pressione", "energia", "potenza",
    "frequenza", "angolo", "densità", "portata", "dati digitali",
)


def _q(*simboli: str) -> tuple[str, ...]:
    """Varianti ASCII di simboli con ² e ³ (es. m² -> m2, m^2)."""
    varianti = []
    for s in simboli:
        for apice, cifra in (("²", "2"), ("³", "3")):
            if apice in s:
                varianti += [s.replace(apice, cifra), s.replace(apice, "^" + cifra)]
    return tuple(varianti)


_GAL_US = 3.785411784e-3
_FT3 = 0.028316846592
_BTU = 1055.05585262
_GALLONE = ("gallone", "galloni")
_PINTA = ("pinta", "pinte")

UNITA: tuple[Unita, ...] = (
    # lunghezza (m)
    Unita("nm", "lunghezza", "nanometro", "nanometri", 1e-9),
    Unita("µm", "lunghezza", "micrometro", "micrometri", 1e-6, simboli=("μm", "um"),
          nomi=("micron",)),
    Unita("mm", "lunghezza", "millimetro", "millimetri", 1e-3),
    Unita("cm", "lunghezza", "centimetro", "centimetri", 1e-2),
    Unita("dm", "lunghezza", "decimetro", "decimetri", 1e-1),
    Unita("m", "lunghezza", "metro", "metri", 1.0),
    Unita("km", "lunghezza", "chilometro", "chilometri", 1e3,
          nomi=("kilometro", "kilometri")),
    Unita("in", "lunghezza", "pollice", "pollici", 0.0254),
    Unita("ft", "lunghezza", "piede", "piedi", 0.3048),
    Unita("yd", "lunghezza", "iarda", "iarde", 0.9144),
    Unita("mi", "lunghezza", "miglio", "miglia", 1609.344),
    Unita("nmi", "lunghezza", "miglio nautico", "miglia nautiche", 1852.0),
    Unita("Å", "lunghezza", "ångström", "ångström", 1e-10, simboli=("Å",)),  # segno di ångström
    Unita("au", "lunghezza", "unità astronomica", "unità astronomiche", 149597870700.0,
          simboli=("UA",)),
    Unita("ly", "lunghezza", "anno luce", "anni luce", 9460730472580800.0),
    # massa (kg)
    Unita("µg", "massa", "microgrammo", "microgrammi", 1e-9, simboli=("μg", "ug")),
    Unita("mg", "massa", "milligrammo", "milligrammi", 1e-6),
    Unita("g", "massa", "grammo", "grammi", 1e-3),
    Unita("kg", "massa", "chilogrammo", "chilogrammi", 1.0,
          nomi=("kilogrammo", "kilogrammi", "chilo", "chili")),
    Unita("t", "massa", "tonnellata", "tonnellate", 1000.0,
          nomi=("tonnellata metrica", "tonnellate metriche")),
    Unita("oz", "massa", "oncia", "once", 0.028349523125),
    Unita("lb", "massa", "libbra", "libbre", 0.45359237, simboli=("lbs",)),
    Unita("st", "massa", "stone", "stone", 6.35029318),
    Unita("ton US", "massa", "tonnellata corta", "tonnellate corte", 907.18474,
          nomi=("tonnellata corta us", "tonnellate corte us")),
    # tempo (s)
    Unita("ns", "tempo", "nanosecondo", "nanosecondi", 1e-9),
    Unita("µs", "tempo", "microsecondo", "microsecondi", 1e-6, simboli=("μs", "us")),
    Unita("ms", "tempo", "millisecondo", "millisecondi", 1e-3),
    Unita("s", "tempo", "secondo", "secondi", 1.0),
    Unita("min", "tempo", "minuto", "minuti", 60.0),
    Unita("h", "tempo", "ora", "ore", 3600.0),
    Unita("giorno", "tempo", "giorno", "giorni", 86400.0, simboli=("d",)),
    Unita("settimana", "tempo", "settimana", "settimane", 604800.0),
    Unita("anno", "tempo", "anno", "anni", 31536000.0),
    # temperatura (K)
    Unita("K", "temperatura", "kelvin", "kelvin", 1.0),
    Unita("°C", "temperatura", "grado Celsius", "gradi Celsius", 1.0, 273.15,
          simboli=("ºC", "°c", "degC"),
          nomi=("celsius", "centigrado", "centigradi", "grado centigrado", "gradi centigradi")),
    Unita("°F", "temperatura", "grado Fahrenheit", "gradi Fahrenheit", 5 / 9, 459.67 * 5 / 9,
          simboli=("ºF", "degF"), nomi=("fahrenheit",)),
    Unita("°R", "temperatura", "grado Rankine", "gradi Rankine", 5 / 9,
          simboli=("ºR", "degR"), nomi=("rankine",)),
    # area (m²)
    Unita("mm²", "area", "millimetro quadrato", "millimetri quadrati", 1e-6, simboli=_q("mm²")),
    Unita("cm²", "area", "centimetro quadrato", "centimetri quadrati", 1e-4, simboli=_q("cm²")),
    Unita("m²", "area", "metro quadrato", "metri quadrati", 1.0, simboli=_q("m²")),
    Unita("km²", "area", "chilometro quadrato", "chilometri quadrati", 1e6, simboli=_q("km²")),
    Unita("a", "area", "ara", "are", 100.0),
    Unita("ha", "area", "ettaro", "ettari", 1e4),
    Unita("in²", "area", "pollice quadrato", "pollici quadrati", 0.00064516, simboli=_q("in²")),
    Unita("ft²", "area", "piede quadrato", "piedi quadrati", 0.09290304, simboli=_q("ft²")),
    Unita("yd²", "area", "iarda quadrata", "iarde quadrate", 0.83612736, simboli=_q("yd²")),
    Unita("ac", "area", "acro", "acri", 4046.8564224),
    Unita("mi²", "area", "miglio quadrato", "miglia quadrate", 2589988.110336, simboli=_q("mi²")),
    # volume (m³)
    Unita("mL", "volume", "millilitro", "millilitri", 1e-6, simboli=("ml",)),
    Unita("cL", "volume", "centilitro", "centilitri", 1e-5, simboli=("cl",)),
    Unita("dL", "volume", "decilitro", "decilitri", 1e-4, simboli=("dl",)),
    Unita("L", "volume", "litro", "litri", 1e-3, simboli=("l",)),
    Unita("hL", "volume", "ettolitro", "ettolitri", 1e-1, simboli=("hl",)),
    Unita("cm³", "volume", "centimetro cubo", "centimetri cubi", 1e-6, simboli=_q("cm³")),
    Unita("dm³", "volume", "decimetro cubo", "decimetri cubi", 1e-3, simboli=_q("dm³")),
    Unita("m³", "volume", "metro cubo", "metri cubi", 1.0, simboli=_q("m³")),
    Unita("in³", "volume", "pollice cubo", "pollici cubi", 16.387064e-6, simboli=_q("in³")),
    Unita("ft³", "volume", "piede cubo", "piedi cubi", _FT3, simboli=_q("ft³")),
    Unita("gal US", "volume", "gallone US", "galloni US", _GAL_US, nomi=_GALLONE),
    Unita("gal UK", "volume", "gallone imperiale", "galloni imperiali", 4.54609e-3,
          nomi=_GALLONE + ("gallone uk", "galloni uk")),
    Unita("pt US", "volume", "pinta US", "pinte US", 473.176473e-6, nomi=_PINTA),
    Unita("pt UK", "volume", "pinta imperiale", "pinte imperiali", 568.26125e-6,
          nomi=_PINTA + ("pinta uk", "pinte uk")),
    Unita("fl oz", "volume", "oncia fluida", "once fluide", 29.5735295625e-6,
          nomi=("oncia fluida us", "once fluide us")),
    # velocità (m/s)
    Unita("m/s", "velocità", "metro al secondo", "metri al secondo", 1.0),
    Unita("km/h", "velocità", "chilometro orario", "chilometri orari", 1 / 3.6,
          simboli=("kmh",), nomi=("chilometro all'ora", "chilometri all'ora")),
    Unita("mph", "velocità", "miglio orario", "miglia orarie", 0.44704,
          nomi=("miglio all'ora", "miglia all'ora")),
    Unita("ft/s", "velocità", "piede al secondo", "piedi al secondo", 0.3048),
    Unita("kn", "velocità", "nodo", "nodi", 1852 / 3600),
    # accelerazione (m/s²)
    Unita("m/s²", "accelerazione", "metro al secondo quadrato", "metri al secondo quadrato",
          1.0, simboli=_q("m/s²")),
    Unita("cm/s²", "accelerazione", "centimetro al secondo quadrato",
          "centimetri al secondo quadrato", 0.01, simboli=_q("cm/s²")),
    Unita("Gal", "accelerazione", "galileo", "galilei", 0.01),
    Unita("ft/s²", "accelerazione", "piede al secondo quadrato", "piedi al secondo quadrato",
          0.3048, simboli=_q("ft/s²")),
    Unita("g0", "accelerazione", "accelerazione di gravità", "accelerazioni di gravità",
          9.80665, simboli=("g₀",)),
    # forza (N)
    Unita("N", "forza", "newton", "newton", 1.0),
    Unita("kN", "forza", "chilonewton", "chilonewton", 1e3),
    Unita("dyn", "forza", "dina", "dine", 1e-5),
    Unita("kgf", "forza", "chilogrammo-forza", "chilogrammi-forza", 9.80665,
          nomi=("chilogrammo forza", "chilogrammi forza")),
    Unita("lbf", "forza", "libbra-forza", "libbre-forza", 4.4482216152605,
          nomi=("libbra forza", "libbre forza")),
    # pressione (Pa)
    Unita("Pa", "pressione", "pascal", "pascal", 1.0),
    Unita("hPa", "pressione", "ettopascal", "ettopascal", 100.0),
    Unita("kPa", "pressione", "chilopascal", "chilopascal", 1e3),
    Unita("MPa", "pressione", "megapascal", "megapascal", 1e6),
    Unita("bar", "pressione", "bar", "bar", 1e5),
    Unita("mbar", "pressione", "millibar", "millibar", 100.0),
    Unita("atm", "pressione", "atmosfera", "atmosfere", 101325.0),
    Unita("psi", "pressione", "psi", "psi", 6894.757293168),
    Unita("mmHg", "pressione", "millimetro di mercurio", "millimetri di mercurio",
          133.322387415),
    Unita("torr", "pressione", "torr", "torr", 101325 / 760),
    # energia (J)
    Unita("J", "energia", "joule", "joule", 1.0),
    Unita("kJ", "energia", "chilojoule", "chilojoule", 1e3),
    Unita("MJ", "energia", "megajoule", "megajoule", 1e6),
    Unita("Wh", "energia", "wattora", "wattora", 3600.0),
    Unita("kWh", "energia", "chilowattora", "chilowattora", 3.6e6),
    Unita("cal", "energia", "caloria", "calorie", 4.184),
    Unita("kcal", "energia", "chilocaloria", "chilocalorie", 4184.0),
    Unita("eV", "energia", "elettronvolt", "elettronvolt", 1.602176634e-19),
    Unita("BTU", "energia", "BTU", "BTU", _BTU),
    # potenza (W)
    Unita("W", "potenza", "watt", "watt", 1.0),
    Unita("kW", "potenza", "chilowatt", "chilowatt", 1e3),
    Unita("MW", "potenza", "megawatt", "megawatt", 1e6),
    Unita("CV", "potenza", "cavallo vapore", "cavalli vapore", 735.49875),
    Unita("hp", "potenza", "horsepower", "horsepower", 745.69987158227022),
    Unita("BTU/h", "potenza", "BTU all'ora", "BTU all'ora", _BTU / 3600),
    # frequenza (Hz)
    Unita("Hz", "frequenza", "hertz", "hertz", 1.0),
    Unita("kHz", "frequenza", "kilohertz", "kilohertz", 1e3, nomi=("chilohertz",)),
    Unita("MHz", "frequenza", "megahertz", "megahertz", 1e6),
    Unita("GHz", "frequenza", "gigahertz", "gigahertz", 1e9),
    Unita("rpm", "frequenza", "giro al minuto", "giri al minuto", 1 / 60),
    # angolo (rad)
    Unita("rad", "angolo", "radiante", "radianti", 1.0),
    Unita("°", "angolo", "grado", "gradi", math.pi / 180, simboli=("deg",),
          nomi=("grado sessagesimale", "gradi sessagesimali")),
    Unita("gon", "angolo", "gradiente", "gradienti", math.pi / 200),
    Unita("′", "angolo", "primo d'arco", "primi d'arco", math.pi / 10800, simboli=("arcmin",)),
    Unita("″", "angolo", "secondo d'arco", "secondi d'arco", math.pi / 648000,
          simboli=("arcsec",)),
    Unita("giro", "angolo", "giro", "giri", 2 * math.pi),
    # densità (kg/m³)
    Unita("kg/m³", "densità", "chilogrammo per metro cubo", "chilogrammi per metro cubo", 1.0,
          simboli=_q("kg/m³")),
    Unita("g/cm³", "densità", "grammo per centimetro cubo", "grammi per centimetro cubo",
          1000.0, simboli=_q("g/cm³")),
    Unita("g/L", "densità", "grammo per litro", "grammi per litro", 1.0, simboli=("g/l",)),
    Unita("kg/L", "densità", "chilogrammo per litro", "chilogrammi per litro", 1000.0,
          simboli=("kg/l",)),
    Unita("lb/ft³", "densità", "libbra per piede cubo", "libbre per piede cubo",
          0.45359237 / _FT3, simboli=_q("lb/ft³")),
    # portata (m³/s)
    Unita("m³/s", "portata", "metro cubo al secondo", "metri cubi al secondo", 1.0,
          simboli=_q("m³/s")),
    Unita("m³/h", "portata", "metro cubo all'ora", "metri cubi all'ora", 1 / 3600,
          simboli=_q("m³/h")),
    Unita("L/s", "portata", "litro al secondo", "litri al secondo", 1e-3, simboli=("l/s",)),
    Unita("L/min", "portata", "litro al minuto", "litri al minuto", 1e-3 / 60,
          simboli=("l/min",)),
    Unita("gpm", "portata", "gallone US al minuto", "galloni US al minuto", _GAL_US / 60),
    # dati digitali (bit)
    Unita("bit", "dati digitali", "bit", "bit", 1.0),
    Unita("B", "dati digitali", "byte", "byte", 8.0),
    Unita("kbit", "dati digitali", "kilobit", "kilobit", 1e3),
    Unita("Mbit", "dati digitali", "megabit", "megabit", 1e6),
    Unita("Gbit", "dati digitali", "gigabit", "gigabit", 1e9),
    Unita("kB", "dati digitali", "kilobyte", "kilobyte", 8e3),
    Unita("MB", "dati digitali", "megabyte", "megabyte", 8e6),
    Unita("GB", "dati digitali", "gigabyte", "gigabyte", 8e9),
    Unita("TB", "dati digitali", "terabyte", "terabyte", 8e12),
    Unita("KiB", "dati digitali", "kibibyte", "kibibyte", 8 * 1024),
    Unita("MiB", "dati digitali", "mebibyte", "mebibyte", 8 * 1024**2),
    Unita("GiB", "dati digitali", "gibibyte", "gibibyte", 8 * 1024**3),
    Unita("TiB", "dati digitali", "tebibyte", "tebibyte", 8 * 1024**4),
)


def normalizza(testo: str) -> str:
    """Minuscole, accenti tolti (NFKD), spazi multipli ridotti, strip."""
    scomposto = unicodedata.normalize("NFKD", testo)
    senza_segni = "".join(c for c in scomposto if not unicodedata.combining(c))
    return " ".join(senza_segni.lower().split())


def _indici() -> tuple[dict[str, Unita], dict[str, list[Unita]]]:
    per_simbolo: dict[str, Unita] = {}
    per_nome: dict[str, list[Unita]] = {}
    for u in UNITA:
        for s in (u.simbolo, *u.simboli):
            per_simbolo[s] = u
        for n in {normalizza(x) for x in (u.singolare, u.plurale, *u.nomi)}:
            per_nome.setdefault(n, []).append(u)
    return per_simbolo, per_nome


_PER_SIMBOLO, _PER_NOME = _indici()


def riconosci(testo: str) -> Unita:
    """Unità corrispondente al testo: simbolo esatto oppure nome in parole."""
    unita = _PER_SIMBOLO.get(testo.strip())
    if unita is not None:
        return unita
    candidati = _PER_NOME.get(normalizza(testo), [])
    if len(candidati) == 1:
        return candidati[0]
    if candidati:
        elenco = ", ".join(f"{u.singolare} ({u.simbolo})" for u in candidati)
        raise ErroreConversione(f"Unità ambigua: {testo!r}. Specifica una tra: {elenco}.")
    raise ErroreConversione(
        f"Unità non ammessa: {testo!r}. Grandezze disponibili: {', '.join(GRANDEZZE)}."
    )


def formatta_numero(x: float) -> str:
    """6 cifre significative, virgola decimale, notazione m × 10^e fuori da [1e-4, 1e12)."""
    if x == 0:
        return "0"
    mantissa, esponente = f"{x:.5e}".split("e")
    esponente = int(esponente)
    if -4 <= esponente < 12:
        testo = f"{float(f'{x:.5e}'):.{max(0, 5 - esponente)}f}"
        suffisso = ""
    else:
        testo = mantissa
        suffisso = f" × 10^{esponente}"
    if "." in testo:
        testo = testo.rstrip("0").rstrip(".")
    return testo.replace(".", ",") + suffisso


# soglia relativa per azzerare il residuo in virgola mobile degli offset di temperatura:
# il residuo reale e' ~2e-16 del valore, la soglia lascia ~50 volte di margine
_RESIDUO = 1e-14


def _nome(unita: Unita, numero: str) -> str:
    return unita.singolare if numero in ("1", "-1") else unita.plurale


def converti(valore: float, da: str, a: str) -> str:
    """Frase con il risultato della conversione; solleva ErroreConversione."""
    if not math.isfinite(valore):
        raise ErroreConversione("Valore non valido: serve un numero finito.")
    u_da, u_a = riconosci(da), riconosci(a)
    if u_da.grandezza != u_a.grandezza:
        raise ErroreConversione(
            f"Conversione incompatibile: {u_da.plurale} ({u_da.grandezza}) → "
            f"{u_a.plurale} ({u_a.grandezza})."
        )
    testo_valore = formatta_numero(valore)
    base = valore * u_da.fattore + u_da.offset
    # residuo in virgola mobile dovuto all'offset di partenza (es. -459,67 °F -> 0 K)
    if abs(base) < _RESIDUO * abs(u_da.offset):
        base = 0.0
    if u_da.grandezza == "temperatura" and base < -1e-9:
        raise ErroreConversione(
            f"Valore impossibile: {testo_valore} {_nome(u_da, testo_valore)} "
            "è sotto lo zero assoluto."
        )
    risultato = (base - u_a.offset) / u_a.fattore
    if not (math.isfinite(base) and math.isfinite(risultato)):
        raise ErroreConversione(
            "Valore non valido: risultato fuori dall'intervallo rappresentabile.")
    # residuo in virgola mobile dovuto all'offset (es. 32 °F -> 5,7e-14 °C)
    if abs(risultato) < _RESIDUO * (abs(base) + abs(u_a.offset)) / u_a.fattore:
        risultato = 0.0
    testo_risultato = formatta_numero(risultato)
    return (f"{testo_valore} {_nome(u_da, testo_valore)} = "
            f"{testo_risultato} {_nome(u_a, testo_risultato)}")
