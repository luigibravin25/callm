"""Giorni e scadenze: calendario con le festivita' italiane lette da file locale.

Risultato non normativo: ogni risposta porta AVVISO.
"""
import json
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

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
