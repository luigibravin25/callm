"""Giorni e scadenze: calendario con le festivita' italiane lette da file locale.

Risultato non normativo: ogni risposta porta AVVISO.
"""
import calendar
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ANNO_MIN = 1900
ANNO_MAX = 2100
MAX_GIORNI = 3660          # circa 10 anni: limite per le scadenze
FUSO = "Europe/Rome"       # fuso per "oggi"
AVVISO = "Calcolo indicativo, non ha valore legale."
GIORNI_SETTIMANA = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato",
                    "domenica")
_MOBILI = ("pasqua", "pasquetta")


class ErroreData(ValueError):
    """Data o richiesta rifiutata: il messaggio spiega il motivo."""


@dataclass(frozen=True)
class Festivita:
    nome: str
    alias: tuple[str, ...]   # gia' normalizzati
    data: str | None         # "MM-GG" fissa
    mobile: str | None       # "pasqua" | "pasquetta"
    dal: int | None          # primo anno in cui vale


def normalizza(testo: str) -> str:
    """Minuscole, senza accenti, apostrofi e ordinali uniformi, spazi singoli."""
    testo = testo.replace("’", "'").replace("‘", "'").replace("º", "").replace("°", "")
    testo = unicodedata.normalize("NFD", testo.lower())
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    return " ".join(testo.split())


def _mm_gg_valida(valore) -> bool:
    if not isinstance(valore, str) or len(valore) != 5 or valore[2] != "-":
        return False
    try:
        date(2000, int(valore[:2]), int(valore[3:]))   # 2000 bisestile: 02-29 ammessa
    except ValueError:
        return False
    return True


def carica_festivita(percorso: Path) -> tuple[Festivita, ...]:
    """Legge e valida il file delle festivita'; ErroreData nomina la voce sbagliata."""
    try:
        contenuto = json.loads(Path(percorso).read_text(encoding="utf-8"))
        voci = contenuto["festivita"]
        if not isinstance(voci, list):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError) as errore:
        raise ErroreData(f"file delle festività non valido ({percorso}): JSON non leggibile "
                         f"o senza l'elenco 'festivita' ({errore})") from None
    festivita, visti = [], {}
    for indice, voce in enumerate(voci, start=1):
        nome = voce.get("nome") if isinstance(voce, dict) else None
        etichetta = f"voce {indice} ({nome})" if nome else f"voce {indice}"
        if not isinstance(nome, str) or not nome.strip():
            raise ErroreData(f"file delle festività: {etichetta} senza 'nome'")
        alias = voce.get("alias")
        if not isinstance(alias, list) or not alias or not all(isinstance(a, str) for a in alias):
            raise ErroreData(f"file delle festività: {etichetta} senza 'alias'")
        data, mobile, dal = voce.get("data"), voce.get("mobile"), voce.get("dal")
        if (data is None) == (mobile is None):
            raise ErroreData(f"file delle festività: {etichetta} deve avere 'data' oppure "
                             "'mobile', non entrambi né nessuno")
        if data is not None and not _mm_gg_valida(data):
            raise ErroreData(f"file delle festività: {etichetta} ha 'data' non valida: {data!r}")
        if mobile is not None and mobile not in _MOBILI:
            raise ErroreData(f"file delle festività: {etichetta} ha 'mobile' sconosciuto: "
                             f"{mobile!r} (ammessi: pasqua, pasquetta)")
        if dal is not None and (not isinstance(dal, int) or isinstance(dal, bool)):
            raise ErroreData(f"file delle festività: {etichetta} ha 'dal' non intero")
        normalizzati = tuple(normalizza(a) for a in alias)
        for a in normalizzati:
            if a in visti:
                raise ErroreData(f"file delle festività: alias {a!r} ripetuto in "
                                 f"{visti[a]} e {etichetta}")
            visti[a] = etichetta
        festivita.append(Festivita(nome.strip(), normalizzati, data, mobile, dal))
    return tuple(festivita)


FESTIVITA = carica_festivita(Path(__file__).with_name("festivita.json"))


def pasqua(anno: int) -> date:
    """Domenica di Pasqua nel calendario gregoriano (algoritmo anonimo, Meeus/Jones/Butcher)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = (h + l - 7 * m + 114) % 31 + 1
    return date(anno, mese, giorno)


def data_festivita(festivita: Festivita, anno: int) -> date | None:
    """Data della festivita' in quell'anno; None se non vale ancora (anno prima di 'dal')."""
    if festivita.dal is not None and anno < festivita.dal:
        return None
    if festivita.mobile == "pasqua":
        return pasqua(anno)
    if festivita.mobile == "pasquetta":
        return pasqua(anno) + timedelta(days=1)
    mese, giorno = int(festivita.data[:2]), int(festivita.data[3:])
    try:
        return date(anno, mese, giorno)
    except ValueError:      # 02-29 in un anno non bisestile
        return None


def festivita_del_giorno(giorno: date) -> list[str]:
    """Nomi delle festivita' che cadono in quel giorno (anche piu' di una)."""
    return [f.nome for f in FESTIVITA if data_festivita(f, giorno.year) == giorno]


def e_lavorativo(giorno: date) -> bool:
    """Da lunedi' a venerdi', escluse le festivita' del file."""
    return giorno.weekday() < 5 and not festivita_del_giorno(giorno)


# --- lettura delle date ---

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre")
_FORMATI = ("formati ammessi: 2026-12-25, 25/12/2026 (giorno/mese/anno), 25 dicembre 2026, "
            "oggi, domani o il nome di una festività (es. natale, pasqua 2027)")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_NUMERICA = re.compile(r"(\d{1,2})([/.-])(\d{1,2})\2(\d+)")
_SEPARATORI_MISTI = re.compile(r"\d{1,2}[/.-]\d{1,2}[/.-]\d+")
_A_PAROLE = re.compile(r"(\d{1,2}) ([a-z]+)(?: (\d{4}))?")
_FESTA = re.compile(r"(?:(?:il|lo|la) |l')?(.+?)(?: (\d{4}))?")
_ALIAS = {a: f for f in FESTIVITA for a in f.alias}


def _oggi() -> date:
    """Data corrente in Italia (funzione separata per poterla sostituire nei test)."""
    return datetime.now(ZoneInfo(FUSO)).date()


def _mostra(testo: str) -> str:
    """Testo per i messaggi: i caratteri non stampabili diventano U+XXXX."""
    return "".join(c if c.isprintable() else f"U+{ord(c):04X}" for c in testo)


def _controlla_anno(anno: int) -> None:
    if not ANNO_MIN <= anno <= ANNO_MAX:
        raise ErroreData(f"anno fuori intervallo: {anno} (ammessi dal {ANNO_MIN} al {ANNO_MAX})")


def _controlla_giorno_mese(giorno: int, mese: int, anno: int | None) -> None:
    """Giorno e mese possibili; con anno=None vale il massimo del mese (29 per febbraio)."""
    if not 1 <= mese <= 12:
        raise ErroreData(f"mese non valido: {mese} (da 1 a 12)")
    if giorno < 1:
        raise ErroreData(f"giorno non valido: {giorno}")
    nome = MESI[mese - 1]
    massimo = 29 if mese == 2 and anno is None else calendar.monthrange(anno or 2000, mese)[1]
    if giorno <= massimo:
        return
    if mese == 2 and giorno == 29:
        raise ErroreData(f"il {anno} non è bisestile: febbraio ha 28 giorni")
    if mese == 2:
        raise ErroreData(f"febbraio ha al massimo {massimo} giorni"
                         + (f" nel {anno}" if anno else ""))
    raise ErroreData(f"{nome} ha {massimo} giorni")


def _data_esatta(giorno: int, mese: int, anno: int) -> date:
    _controlla_anno(anno)
    _controlla_giorno_mese(giorno, mese, anno)
    return date(anno, mese, giorno)


def _prossima_fissa(giorno: int, mese: int, riferimento: date) -> date:
    """Prima data con quel giorno e mese da riferimento in poi (per il 29/02: anno bisestile)."""
    _controlla_giorno_mese(giorno, mese, None)
    for anno in range(riferimento.year, ANNO_MAX + 1):
        if mese == 2 and giorno == 29 and not calendar.isleap(anno):
            continue
        candidata = date(anno, mese, giorno)
        if candidata >= riferimento:
            return candidata
    raise ErroreData(f"la prossima ricorrenza cade oltre il {ANNO_MAX} (anni ammessi dal "
                     f"{ANNO_MIN} al {ANNO_MAX})")


def _data_festivita(festivita: Festivita, anno: int | None, riferimento: date) -> date:
    if anno is not None:
        _controlla_anno(anno)
        if festivita.dal is not None and anno < festivita.dal:
            raise ErroreData(f"{festivita.nome} è festività nazionale solo dal {festivita.dal}")
        trovata = data_festivita(festivita, anno)
        if trovata is None:
            raise ErroreData(f"{festivita.nome} non cade nel {anno}")
        return trovata
    for anno in range(max(riferimento.year, festivita.dal or ANNO_MIN), ANNO_MAX + 1):
        trovata = data_festivita(festivita, anno)
        if trovata is not None and trovata >= riferimento:
            return trovata
    raise ErroreData(f"la prossima ricorrenza di {festivita.nome} cade oltre il {ANNO_MAX} "
                     f"(anni ammessi dal {ANNO_MIN} al {ANNO_MAX})")


def leggi_data(testo: str | None, riferimento: date | None = None) -> date:
    """Legge una data in uno dei formati ammessi; senza anno vale la prossima ricorrenza
    da `riferimento` (compreso; predefinito oggi)."""
    if testo is None or not testo.strip():
        raise ErroreData("data vuota: " + _FORMATI)
    oggi = _oggi()
    riferimento = riferimento or oggi
    norma = normalizza(testo)
    if norma in ("oggi", "domani"):
        risultato = oggi if norma == "oggi" else oggi + timedelta(days=1)
        _controlla_anno(risultato.year)
        return risultato
    if trovato := _ISO.fullmatch(norma):
        anno, mese, giorno = map(int, trovato.groups())
        return _data_esatta(giorno, mese, anno)
    if trovato := _NUMERICA.fullmatch(norma):
        giorno, mese, cifre = int(trovato[1]), int(trovato[3]), trovato[4]
        if len(cifre) == 2:
            raise ErroreData(f"anno a 2 cifre in {_mostra(testo.strip())!r}: è ambiguo, "
                             "scrivilo per intero (es. 2026)")
        if len(cifre) != 4:
            raise ErroreData(f"formato non riconosciuto: {_mostra(testo.strip())!r}; " + _FORMATI)
        return _data_esatta(giorno, mese, int(cifre))
    if _SEPARATORI_MISTI.fullmatch(norma):
        raise ErroreData(f"separatori misti in {_mostra(testo.strip())!r}: usa sempre lo stesso "
                         "(/ oppure - oppure .)")
    if (trovato := _A_PAROLE.fullmatch(norma)) and trovato[2] in MESI:
        giorno, mese = int(trovato[1]), MESI.index(trovato[2]) + 1
        if trovato[3]:
            return _data_esatta(giorno, mese, int(trovato[3]))
        return _prossima_fissa(giorno, mese, riferimento)
    if (trovato := _FESTA.fullmatch(norma)) and trovato[1] in _ALIAS:
        anno = int(trovato[2]) if trovato[2] else None
        return _data_festivita(_ALIAS[trovato[1]], anno, riferimento)
    if re.fullmatch(r"[a-z' ]+(?: \d{4})?", norma):
        raise ErroreData(f"formato non riconosciuto o festività sconosciuta: "
                         f"{_mostra(testo.strip())!r}; scrivi la data, " + _FORMATI)
    raise ErroreData(f"formato non riconosciuto: {_mostra(testo.strip())!r}; " + _FORMATI)
