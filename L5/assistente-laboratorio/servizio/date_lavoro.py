"""Giorni e scadenze: calendario con le festivita' italiane lette da file locale.

Risultato non normativo: ogni risposta porta AVVISO.
"""
# Librerie standard: calendar (anni bisestili, giorni del mese), json (file delle festivita'),
# re (riconoscere i formati delle date), unicodedata (togliere gli accenti),
# dataclass (classe dati), datetime (date e differenze), Path (percorso del file),
# ZoneInfo (fuso orario italiano per sapere che giorno e' oggi)
import calendar
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Intervallo di anni accettato: evita calcoli su date assurde (es. anno 99999)
ANNO_MIN = 1900
ANNO_MAX = 2100
MAX_GIORNI = 3660          # circa 10 anni: limite per le scadenze
FUSO = "Europe/Rome"       # fuso per "oggi"
# Frase aggiunta a ogni risposta: il calcolo non sostituisce un controllo ufficiale
AVVISO = "Calcolo indicativo, non ha valore legale."
# Nomi dei giorni nell'ordine di weekday(): 0 = lunedi', 6 = domenica
GIORNI_SETTIMANA = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato",
                    "domenica")
# Festivita' mobili ammesse nel file: la loro data si calcola ogni anno da quella di Pasqua
_MOBILI = ("pasqua", "pasquetta")


# Errore delle date: il servizio lo trasforma in una risposta 400 con il motivo
class ErroreData(ValueError):
    """Data o richiesta rifiutata: il messaggio spiega il motivo."""


# Una festivita' letta dal file festivita.json (con data fissa oppure mobile)
@dataclass(frozen=True)
class Festivita:
    nome: str
    alias: tuple[str, ...]   # gia' normalizzati
    data: str | None         # "MM-GG" fissa
    mobile: str | None       # "pasqua" | "pasquetta"
    dal: int | None          # primo anno in cui vale


# Rende confrontabili testi scritti in modi diversi ("Ferragosto", "ferragósto", "1º maggio")
def normalizza(testo: str) -> str:
    """Minuscole, senza accenti, apostrofi e ordinali uniformi, spazi singoli."""
    # Apostrofi tipografici diventano ' semplici; i simboli di ordinale (º, °) si tolgono
    testo = testo.replace("’", "'").replace("‘", "'").replace("º", "").replace("°", "")
    # NFD separa la lettera dal suo accento ("è" diventa "e" + accento)...
    testo = unicodedata.normalize("NFD", testo.lower())
    # ...e qui si scartano gli accenti (caratteri "combining"), tenendo le lettere
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    # split() + join riducono spazi multipli, iniziali e finali a spazi singoli
    return " ".join(testo.split())


# Controlla una data fissa del file nel formato "MM-GG" (es. "12-25")
def _mm_gg_valida(valore) -> bool:
    # Deve essere un testo di 5 caratteri con il trattino al centro
    if not isinstance(valore, str) or len(valore) != 5 or valore[2] != "-":
        return False
    # Si prova a costruire la data: se mese o giorno sono impossibili, date() solleva ValueError
    try:
        date(2000, int(valore[:2]), int(valore[3:]))   # 2000 bisestile: 02-29 ammessa
    except ValueError:
        return False
    return True


# Legge festivita.json una volta all'avvio e controlla ogni voce
def carica_festivita(percorso: Path) -> tuple[Festivita, ...]:
    """Legge e valida il file delle festivita'; ErroreData nomina la voce sbagliata."""
    # Lettura del file: qualsiasi problema (file mancante, JSON rotto, chiave assente)
    # diventa un unico ErroreData con la spiegazione
    try:
        contenuto = json.loads(Path(percorso).read_text(encoding="utf-8"))
        voci = contenuto["festivita"]
        if not isinstance(voci, list):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError) as errore:
        raise ErroreData(f"file delle festività non valido ({percorso}): JSON non leggibile "
                         f"o senza l'elenco 'festivita' ({errore})") from None
    # festivita: voci valide; visti: alias gia' incontrati -> voce che li usa (contro i doppioni)
    festivita, visti = [], {}
    # Controllo di ogni voce; indice parte da 1 per i messaggi d'errore
    for indice, voce in enumerate(voci, start=1):
        nome = voce.get("nome") if isinstance(voce, dict) else None
        # Etichetta della voce nei messaggi: numero e, se c'e', nome
        etichetta = f"voce {indice} ({nome})" if nome else f"voce {indice}"
        if not isinstance(nome, str) or not nome.strip():
            raise ErroreData(f"file delle festività: {etichetta} senza 'nome'")
        # alias: i modi in cui l'utente puo' chiamare la festivita' (es. "natale")
        alias = voce.get("alias")
        if not isinstance(alias, list) or not alias or not all(isinstance(a, str) for a in alias):
            raise ErroreData(f"file delle festività: {etichetta} senza 'alias'")
        data, mobile, dal = voce.get("data"), voce.get("mobile"), voce.get("dal")
        # Serve esattamente uno tra 'data' (fissa) e 'mobile' (calcolata da Pasqua)
        if (data is None) == (mobile is None):
            raise ErroreData(f"file delle festività: {etichetta} deve avere 'data' oppure "
                             "'mobile', non entrambi né nessuno")
        if data is not None and not _mm_gg_valida(data):
            raise ErroreData(f"file delle festività: {etichetta} ha 'data' non valida: {data!r}")
        if mobile is not None and mobile not in _MOBILI:
            raise ErroreData(f"file delle festività: {etichetta} ha 'mobile' sconosciuto: "
                             f"{mobile!r} (ammessi: pasqua, pasquetta)")
        # 'dal' deve essere un intero vero: bool e' una sottoclasse di int, quindi si esclude
        if dal is not None and (not isinstance(dal, int) or isinstance(dal, bool)):
            raise ErroreData(f"file delle festività: {etichetta} ha 'dal' non intero")
        # Alias normalizzati, cosi' il confronto con il testo dell'utente e' semplice
        normalizzati = tuple(normalizza(a) for a in alias)
        # Lo stesso alias in due festivita' renderebbe ambigua la ricerca: si rifiuta
        for a in normalizzati:
            if a in visti:
                raise ErroreData(f"file delle festività: alias {a!r} ripetuto in "
                                 f"{visti[a]} e {etichetta}")
            visti[a] = etichetta
        festivita.append(Festivita(nome.strip(), normalizzati, data, mobile, dal))
    # Tupla: elenco che non si puo' modificare per sbaglio
    return tuple(festivita)


# Elenco delle festivita', caricato all'importazione dal file accanto a questo modulo
FESTIVITA = carica_festivita(Path(__file__).with_name("festivita.json"))


# Calcola la data di Pasqua di un anno: serve per Pasqua e Pasquetta, che cambiano ogni anno.
# Pasqua e' la domenica dopo il primo plenilunio di primavera: l'algoritmo di Meeus lo ricava
# solo con divisioni intere (//) e resti (%), senza tabelle astronomiche.
def pasqua(anno: int) -> date:
    """Domenica di Pasqua nel calendario gregoriano (algoritmo anonimo, Meeus/Jones/Butcher)."""
    # a: posizione dell'anno nel ciclo lunare di 19 anni; b: secolo; c: anno nel secolo
    a, b, c = anno % 19, anno // 100, anno % 100
    # d, e: correzioni per gli anni bisestili secolari (il 1900 non e' bisestile, il 2000 si')
    d, e = b // 4, b % 4
    # f, g: correzione dell'orbita lunare lungo i secoli
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    # h: giorni tra l'equinozio e il plenilunio (l'"epatta")
    h = (19 * a + b - d - g + 15) % 30
    # i, k: correzioni bisestili dentro il secolo
    i, k = c // 4, c % 4
    # l: giorni da aggiungere per arrivare alla domenica successiva
    l = (32 + 2 * e + 2 * i - h - k) % 7
    # m: correzione per pochi casi limite in cui la data cadrebbe troppo tardi
    m = (a + 11 * h + 22 * l) // 451
    # Mese (3 = marzo, 4 = aprile) e giorno ricavati dallo stesso numero
    mese = (h + l - 7 * m + 114) // 31
    giorno = (h + l - 7 * m + 114) % 31 + 1
    return date(anno, mese, giorno)


# Data concreta di una festivita' in un certo anno (fissa, Pasqua o Pasquetta)
def data_festivita(festivita: Festivita, anno: int) -> date | None:
    """Data della festivita' in quell'anno; None se non vale ancora (anno prima di 'dal')."""
    if festivita.dal is not None and anno < festivita.dal:
        return None
    if festivita.mobile == "pasqua":
        return pasqua(anno)
    # Pasquetta e' sempre il lunedi' dopo Pasqua
    if festivita.mobile == "pasquetta":
        return pasqua(anno) + timedelta(days=1)
    # Data fissa: "MM-GG" diviso in mese e giorno
    mese, giorno = int(festivita.data[:2]), int(festivita.data[3:])
    try:
        return date(anno, mese, giorno)
    except ValueError:      # 02-29 in un anno non bisestile
        return None


# Cerca tra tutte le festivita' quelle che cadono proprio in quel giorno
def festivita_del_giorno(giorno: date) -> list[str]:
    """Nomi delle festivita' che cadono in quel giorno (anche piu' di una)."""
    return [f.nome for f in FESTIVITA if data_festivita(f, giorno.year) == giorno]


# Giorno lavorativo: weekday() < 5 vuol dire da lunedi' (0) a venerdi' (4), e niente festivita'
def e_lavorativo(giorno: date) -> bool:
    """Da lunedi' a venerdi', escluse le festivita' del file."""
    return giorno.weekday() < 5 and not festivita_del_giorno(giorno)


# --- lettura delle date ---

# Nomi dei mesi senza accenti: si confrontano con il testo gia' normalizzato
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre")
# Elenco dei formati, aggiunto ai messaggi d'errore per aiutare a correggere la richiesta
_FORMATI = ("formati ammessi: 2026-12-25, 25/12/2026 (giorno/mese/anno), 25 dicembre 2026, "
            "oggi, domani o il nome di una festività (es. natale, pasqua 2027)")
# Espressioni regolari dei formati riconosciuti:
# ISO anno-mese-giorno, es. 2026-12-25
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# giorno/mese/anno con lo stesso separatore due volte (\2 ripete il primo: / . oppure -)
_NUMERICA = re.compile(r"(\d{1,2})([/.-])(\d{1,2})\2(\d+)")
# stessa forma ma con separatori diversi (es. 25/12-2026): serve solo a dare un errore chiaro
_SEPARATORI_MISTI = re.compile(r"\d{1,2}[/.-]\d{1,2}[/.-]\d+")
# a parole, es. "25 dicembre" o "25 dicembre 2026" (anno facoltativo)
_A_PAROLE = re.compile(r"(\d{1,2}) ([a-z]+)(?: (\d{4}))?")
# nome di festivita' con articolo facoltativo e anno facoltativo, es. "la pasqua 2027"
_FESTA = re.compile(r"(?:(?:il|lo|la) |l')?(.+?)(?: (\d{4}))?")
# Dizionario alias -> festivita', per trovare subito la festivita' dal nome scritto
_ALIAS = {a: f for f in FESTIVITA for a in f.alias}


# Data di oggi secondo il fuso italiano
def _oggi() -> date:
    """Data corrente in Italia (funzione separata per poterla sostituire nei test)."""
    return datetime.now(ZoneInfo(FUSO)).date()


# Prepara il testo dell'utente da mostrare in un messaggio d'errore senza caratteri invisibili
def _mostra(testo: str) -> str:
    """Testo per i messaggi: i caratteri non stampabili diventano U+XXXX."""
    return "".join(c if c.isprintable() else f"U+{ord(c):04X}" for c in testo)


# Rifiuta gli anni fuori da ANNO_MIN..ANNO_MAX
def _controlla_anno(anno: int) -> None:
    if not ANNO_MIN <= anno <= ANNO_MAX:
        raise ErroreData(f"anno fuori intervallo: {anno} (ammessi dal {ANNO_MIN} al {ANNO_MAX})")


# Controlla che giorno e mese esistano, con un messaggio preciso (es. "aprile ha 30 giorni")
def _controlla_giorno_mese(giorno: int, mese: int, anno: int | None) -> None:
    """Giorno e mese possibili; con anno=None vale il massimo del mese (29 per febbraio)."""
    if not 1 <= mese <= 12:
        raise ErroreData(f"mese non valido: {mese} (da 1 a 12)")
    if giorno < 1:
        raise ErroreData(f"giorno non valido: {giorno}")
    nome = MESI[mese - 1]
    # Giorni del mese: monthrange restituisce (primo giorno della settimana, numero di giorni).
    # Senza anno si usa il 2000, bisestile; per febbraio senza anno il massimo e' 29
    massimo = 29 if mese == 2 and anno is None else calendar.monthrange(anno or 2000, mese)[1]
    if giorno <= massimo:
        return
    # Da qui il giorno e' troppo grande: si sceglie il messaggio piu' utile
    if mese == 2 and giorno == 29:
        raise ErroreData(f"il {anno} non è bisestile: febbraio ha 28 giorni")
    if mese == 2:
        raise ErroreData(f"febbraio ha al massimo {massimo} giorni"
                         + (f" nel {anno}" if anno else ""))
    raise ErroreData(f"{nome} ha {massimo} giorni")


# Costruisce una data completa (giorno, mese, anno) dopo averla controllata
def _data_esatta(giorno: int, mese: int, anno: int) -> date:
    _controlla_anno(anno)
    _controlla_giorno_mese(giorno, mese, anno)
    return date(anno, mese, giorno)


# Data senza anno (es. "25 dicembre"): la prossima volta che capita, da riferimento in poi
def _prossima_fissa(giorno: int, mese: int, riferimento: date) -> date:
    """Prima data con quel giorno e mese da riferimento in poi (per il 29/02: anno bisestile)."""
    _controlla_giorno_mese(giorno, mese, None)
    # Prova un anno dopo l'altro, a partire da quello di riferimento
    for anno in range(riferimento.year, ANNO_MAX + 1):
        # Il 29 febbraio esiste solo negli anni bisestili: gli altri si saltano
        if mese == 2 and giorno == 29 and not calendar.isleap(anno):
            continue
        candidata = date(anno, mese, giorno)
        # Se quest'anno la data e' gia' passata, il ciclo prova l'anno dopo
        if candidata >= riferimento:
            return candidata
    raise ErroreData(f"la prossima ricorrenza cade oltre il {ANNO_MAX} (anni ammessi dal "
                     f"{ANNO_MIN} al {ANNO_MAX})")


# Data di una festivita' chiesta per nome: dell'anno indicato oppure la prossima ricorrenza
def _data_festivita(festivita: Festivita, anno: int | None, riferimento: date) -> date:
    # Anno indicato (es. "pasqua 2027"): si controlla e si calcola solo quello
    if anno is not None:
        _controlla_anno(anno)
        if festivita.dal is not None and anno < festivita.dal:
            raise ErroreData(f"{festivita.nome} è festività nazionale solo dal {festivita.dal}")
        trovata = data_festivita(festivita, anno)
        if trovata is None:
            raise ErroreData(f"{festivita.nome} non cade nel {anno}")
        return trovata
    # Senza anno: si cerca dal primo anno utile (riferimento o 'dal') la prima data non passata
    for anno in range(max(riferimento.year, festivita.dal or ANNO_MIN), ANNO_MAX + 1):
        trovata = data_festivita(festivita, anno)
        if trovata is not None and trovata >= riferimento:
            return trovata
    raise ErroreData(f"la prossima ricorrenza di {festivita.nome} cade oltre il {ANNO_MAX} "
                     f"(anni ammessi dal {ANNO_MIN} al {ANNO_MAX})")


# Trasforma il testo dell'utente in una data, provando i formati uno dopo l'altro
def leggi_data(testo: str | None, riferimento: date | None = None) -> date:
    """Legge una data in uno dei formati ammessi; senza anno vale la prossima ricorrenza
    da `riferimento` (compreso; predefinito oggi)."""
    if testo is None or not testo.strip():
        raise ErroreData("data vuota: " + _FORMATI)
    oggi = _oggi()
    riferimento = riferimento or oggi
    # Testo uniforme (minuscole, senza accenti) per i confronti seguenti
    norma = normalizza(testo)
    # Parole speciali: "oggi" e "domani"
    if norma in ("oggi", "domani"):
        risultato = oggi if norma == "oggi" else oggi + timedelta(days=1)
        _controlla_anno(risultato.year)
        return risultato
    # Formato ISO (2026-12-25); ":=" assegna e controlla nello stesso momento
    if trovato := _ISO.fullmatch(norma):
        anno, mese, giorno = map(int, trovato.groups())
        return _data_esatta(giorno, mese, anno)
    # Formato numerico italiano giorno/mese/anno (25/12/2026, 25.12.2026, 25-12-2026)
    if trovato := _NUMERICA.fullmatch(norma):
        giorno, mese, cifre = int(trovato[1]), int(trovato[3]), trovato[4]
        # "26" potrebbe essere 1926 o 2026: si chiede l'anno completo
        if len(cifre) == 2:
            raise ErroreData(f"anno a 2 cifre in {_mostra(testo.strip())!r}: è ambiguo, "
                             "scrivilo per intero (es. 2026)")
        if len(cifre) != 4:
            raise ErroreData(f"formato non riconosciuto: {_mostra(testo.strip())!r}; " + _FORMATI)
        return _data_esatta(giorno, mese, int(cifre))
    # Separatori diversi nella stessa data: errore dedicato, piu' chiaro di uno generico
    if _SEPARATORI_MISTI.fullmatch(norma):
        raise ErroreData(f"separatori misti in {_mostra(testo.strip())!r}: usa sempre lo stesso "
                         "(/ oppure - oppure .)")
    # Formato a parole ("25 dicembre [2026]"), solo se la parola e' davvero un mese
    if (trovato := _A_PAROLE.fullmatch(norma)) and trovato[2] in MESI:
        # Il numero del mese e' la posizione nell'elenco piu' 1 (gennaio = 1)
        giorno, mese = int(trovato[1]), MESI.index(trovato[2]) + 1
        if trovato[3]:
            return _data_esatta(giorno, mese, int(trovato[3]))
        # Senza anno: la prossima ricorrenza
        return _prossima_fissa(giorno, mese, riferimento)
    # Nome di una festivita' conosciuta ("natale", "la pasqua 2027")
    if (trovato := _FESTA.fullmatch(norma)) and trovato[1] in _ALIAS:
        anno = int(trovato[2]) if trovato[2] else None
        return _data_festivita(_ALIAS[trovato[1]], anno, riferimento)
    # Solo lettere (ed eventualmente un anno): probabilmente una festivita' che non conosciamo
    if re.fullmatch(r"[a-z' ]+(?: \d{4})?", norma):
        raise ErroreData(f"formato non riconosciuto o festività sconosciuta: "
                         f"{_mostra(testo.strip())!r}; scrivi la data, " + _FORMATI)
    # Nessun formato riconosciuto
    raise ErroreData(f"formato non riconosciuto: {_mostra(testo.strip())!r}; " + _FORMATI)


# --- le tre operazioni (ogni risultato porta l'avviso non normativo) ---

# Nome italiano del giorno della settimana di una data
def _giorno(d: date) -> str:
    return GIORNI_SETTIMANA[d.weekday()]


# Vero se l'argomento manca o contiene solo spazi
def _vuoto(testo: str | None) -> bool:
    return testo is None or not testo.strip()


# Giorno dopo d, con errore se si supera l'ultimo anno ammesso
def _successivo(d: date) -> date:
    d += timedelta(days=1)
    if d.year > ANNO_MAX:
        raise ErroreData(f"il risultato cade oltre il {ANNO_MAX} (anni ammessi dal {ANNO_MIN} "
                         f"al {ANNO_MAX})")
    return d


# Operazione "giorni": quanti giorni (di calendario e lavorativi) mancano a una data
def conta_giorni(data: str | None, da: str | None = None) -> dict:
    """Giorni di calendario e lavorativi fino a `data`.
    `da` vuota o "oggi": (oggi, data], oggi escluso; altrimenti [da, data], estremi compresi."""
    if _vuoto(data):
        raise ErroreData("manca la data di arrivo")
    # Partenza da oggi se 'da' manca o e' "oggi": in quel caso oggi non si conta
    da_oggi = _vuoto(da) or normalizza(da) == "oggi"
    partenza = _oggi() if da_oggi else leggi_data(da)
    # Una data senza anno si interpreta come la prossima ricorrenza dopo la partenza
    arrivo = leggi_data(data, partenza)
    if arrivo < partenza:
        raise ErroreData(f"la data {arrivo.isoformat()} è già passata rispetto alla partenza "
                         f"{partenza.isoformat()}")
    # Primo giorno da contare: domani se si parte da oggi, altrimenti la partenza stessa
    primo = partenza + timedelta(days=1) if da_oggi else partenza
    # Elenco di tutti i giorni da contare, dal primo all'arrivo compreso
    giorni = [primo + timedelta(days=n) for n in range((arrivo - primo).days + 1)]
    # Festivita' che cadono da lunedi' a venerdi': sono quelle che tolgono giorni lavorativi
    festivita = [{"data": d.isoformat(), "nome": nome}
                 for d in giorni if d.weekday() < 5 for nome in festivita_del_giorno(d)]
    # Risultato come dizionario: FastAPI lo restituisce in JSON
    return {
        "operazione": "giorni",
        "da": partenza.isoformat(), "da_giorno": _giorno(partenza),
        "a": arrivo.isoformat(), "a_giorno": _giorno(arrivo),
        "conteggio": "oggi escluso" if da_oggi else "estremi compresi",
        "giorni_calendario": len(giorni),
        # Conta solo i giorni lavorativi dell'elenco
        "giorni_lavorativi": sum(1 for d in giorni if e_lavorativo(d)),
        "festivita": festivita,
        "avviso": AVVISO,
    }


# Operazione "scadenza": la data che si raggiunge dopo N giorni da una partenza
def calcola_scadenza(giorni: int | None, da: str | None = None,
                     tipo: str = "lavorativi") -> dict:
    """Data dopo `giorni` giorni lavorativi o di calendario da `da` (predefinita oggi).
    Di calendario: se cade in un giorno non lavorativo slitta al primo lavorativo."""
    # Controlli sugli argomenti, ognuno con il suo messaggio
    if giorni is None:
        raise ErroreData("manca il numero di giorni della scadenza")
    if giorni < 0:
        raise ErroreData(f"numero di giorni negativo: {giorni}")
    if giorni > MAX_GIORNI:
        raise ErroreData(f"troppi giorni: {giorni} (massimo {MAX_GIORNI}, circa 10 anni)")
    if tipo not in ("lavorativi", "calendario"):
        raise ErroreData(f"tipo non valido: {tipo!r} (ammessi: lavorativi, calendario)")
    partenza = _oggi() if _vuoto(da) else leggi_data(da)
    # Restano None se la scadenza non deve slittare
    slittata_da, motivo = None, None
    if tipo == "lavorativi":
        # Si avanza un giorno alla volta e si contano solo i giorni lavorativi;
        # la partenza non conta, e la scadenza e' sempre un giorno lavorativo
        scadenza, contati = partenza, 0
        while contati < giorni:
            scadenza = _successivo(scadenza)
            # True vale 1 e False vale 0: si aggiunge 1 solo nei giorni lavorativi
            contati += e_lavorativo(scadenza)
    else:
        # Giorni di calendario: si sommano tutti in un colpo solo
        originale = partenza + timedelta(days=giorni)
        if originale.year > ANNO_MAX:
            raise ErroreData(f"il risultato cade oltre il {ANNO_MAX} (anni ammessi dal "
                             f"{ANNO_MIN} al {ANNO_MAX})")
        scadenza = originale
        # Se cade di sabato, domenica o in una festivita', slitta al primo giorno lavorativo
        while not e_lavorativo(scadenza):
            scadenza = _successivo(scadenza)
        # Slittamento avvenuto: si annotano la data originale e il motivo
        # (nome della festivita' oppure, se non c'e', il giorno della settimana)
        if scadenza != originale:
            slittata_da = originale.isoformat()
            motivo = " e ".join(festivita_del_giorno(originale)) or _giorno(originale)
    return {
        "operazione": "scadenza",
        "da": partenza.isoformat(), "da_giorno": _giorno(partenza),
        "giorni": giorni, "tipo": tipo,
        "scadenza": scadenza.isoformat(), "scadenza_giorno": _giorno(scadenza),
        "slittata_da": slittata_da, "motivo_slittamento": motivo,
        "avviso": AVVISO,
    }


# Operazione "giorno": tutte le informazioni su una singola data
def info_giorno(data: str | None) -> dict:
    """Giorno della settimana, lavorativo, festivo (con i nomi), fine settimana."""
    if _vuoto(data):
        raise ErroreData("manca la data")
    giorno = leggi_data(data)
    # weekday() >= 5: sabato (5) o domenica (6)
    return {
        "operazione": "giorno",
        "data": giorno.isoformat(), "giorno_settimana": _giorno(giorno),
        "lavorativo": e_lavorativo(giorno),
        "fine_settimana": giorno.weekday() >= 5,
        "festivita": festivita_del_giorno(giorno),
        "avviso": AVVISO,
    }
