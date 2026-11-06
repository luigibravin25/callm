"""Traduzione del meteo: dalla domanda (citta', giorni) alle richieste e dalla risposta al testo.

La logica meteo resta in Open-Meteo; qui si decide soltanto:
- quale citta' usare: solo citta' italiane (il geocoding cerca con countryCode=IT), nome
  esatto, la piu' popolosa tra gli omonimi, citta' predefinita, precisazione dopo la virgola;
- come presentare la risposta (unita' dalla risposta, condizioni in italiano, date in
  italiano, fonte dei dati);
- quali dati sono validi (campi mancanti o di tipo sbagliato -> RispostaNonValida).
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from mcp_meteo.errori import (ArgomentoNonValido, CittaNonTrovata, RispostaNonValida)
from mcp_meteo.open_meteo import cerca_citta, meteo
# lettura delle date gia' scritta e testata nell'esercizio 3 (giorni e scadenze): si riusa
from servizio.date_lavoro import (GIORNI_SETTIMANA, MESI, ErroreData, leggi_data, normalizza)

GIORNI_MAX = 7  # previsioni fino a 7 giorni, oggi compreso (Open-Meteo arriverebbe a 16)
# con date ("tra 7 giorni", "12 novembre") si arriva fino a oggi + 7: "tra 7 giorni" sono i
# 7 giorni da domani, quindi a Open-Meteo si chiedono 8 giorni (oggi compreso)
GIORNI_AVANTI_MAX = 7
LUNGHEZZA_MAX_CITTA = 100  # caratteri: oltre e' certamente un errore dell'argomento
CITTA_RISERVA = "Roma"  # citta' predefinita se CITTA_PREDEFINITA non e' impostata
FONTE = "Fonte: Open-Meteo.com (CC BY 4.0)"  # la licenza dei dati chiede di citare la fonte
# omonimi elencati al massimo (gli altri sono solo contati: "e altre N")
MAX_ALTERNATIVE = 3
# un omonimo e' un'alternativa solo se ha almeno il 5% degli abitanti della citta' scelta:
# cosi' Roma (2,3 milioni) non elenca la frazione Roma in provincia di Mantova (87 abitanti)
SOGLIA_ALTERNATIVE = 0.05
# sotto questi abitanti la localita' scelta si dichiara "piccola": in Italia esistono frazioni
# con nomi di citta' estere ("Parigi", 31 abitanti, in provincia di Vicenza)
ABITANTI_PICCOLA_LOCALITA = 1000
# inizio del nome della provincia nel geocoding ("Provincia di Mantova", "Città Metropolitana
# di Bologna", "Provincia dell'Aquila"): si toglie per scrivere solo "Mantova"
_PREFISSO_PROVINCIA = re.compile(
    r"^(?:provincia|città metropolitana|citta metropolitana|libero consorzio comunale)"
    r"\s+(?:dell'|della|degli|dei|del|di)\s*", re.IGNORECASE)  # le forme lunghe prima

# codici meteo WMO usati da Open-Meteo -> condizione in italiano
CONDIZIONI_WMO = {
    0: "sereno", 1: "prevalentemente sereno", 2: "poco nuvoloso", 3: "coperto",
    45: "nebbia", 48: "nebbia con brina",
    51: "pioggerella debole", 53: "pioggerella moderata", 55: "pioggerella intensa",
    56: "pioggerella gelata debole", 57: "pioggerella gelata intensa",
    61: "pioggia debole", 63: "pioggia moderata", 65: "pioggia forte",
    66: "pioggia gelata debole", 67: "pioggia gelata forte",
    71: "neve debole", 73: "neve moderata", 75: "neve forte", 77: "granelli di neve",
    80: "rovesci di pioggia deboli", 81: "rovesci di pioggia moderati",
    82: "rovesci di pioggia violenti", 85: "rovesci di neve deboli", 86: "rovesci di neve forti",
    95: "temporale", 96: "temporale con grandine debole", 99: "temporale con grandine forte",
}


# formati della data accettati dal tool (gli ultimi li legge leggi_data dell'esercizio 3)
FORMATI_DATA = ("formati ammessi: oggi, domani, dopodomani, tra N giorni, un giorno della "
                "settimana (sabato), 2026-11-15, 15/11/2026, 15 novembre, 15 novembre 2026, "
                "una festività (natale)")
# parole di contorno che il modello puo' lasciare intorno alla data ("il 15 novembre",
# "sabato prossimo", "per domani"): si tolgono prima di leggerla
_PAROLE_INIZIALI = ("il ", "lo ", "la ", "l'", "per ", "di ", "a ")
# "prossimo" cambia il significato quando il giorno della settimana e' oggi: si ricorda a parte
_PROSSIMO_INIZIALE = ("prossimo ", "prossima ")
_PROSSIMO_FINALE = (" prossimo", " prossima")
# "tra 3 giorni", "fra 1 giorno", "tra due giorni": il numero in cifre o in lettere
_TRA_N_GIORNI = re.compile(r"(?:tra|fra) (\w+) giorn[oi]")
_NUMERI_IN_LETTERE = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4,
                      "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
                      "quindici": 15, "venti": 20, "trenta": 30}
_MAX_GIORNI_AVANTI = 3660  # "tra 99999 giorni": oltre circa 10 anni e' un errore di argomento
# accento scritto con l'apostrofo ("venerdi'", "lunedi'"): si toglie l'apostrofo
_ACCENTO_APOSTROFO = re.compile(r"([aeiou])'(?=\s|$)")
_SETTIMANA = tuple(normalizza(g) for g in GIORNI_SETTIMANA)  # "lunedi", "martedi"...


def _adesso() -> datetime:
    """Istante corrente in UTC (funzione separata per poterla sostituire nei test)."""
    return datetime.now(timezone.utc)


def citta_predefinita() -> str:
    """Citta' da CITTA_PREDEFINITA; non impostata o vuota -> Roma."""
    return os.environ.get("CITTA_PREDEFINITA", "").strip() or CITTA_RISERVA


def condizione(codice: int) -> str:
    """Codice WMO -> condizione in italiano; un codice sconosciuto non e' un errore."""
    return CONDIZIONI_WMO.get(codice, f"condizione non riconosciuta (codice WMO {codice})")


def provincia(luogo: dict) -> str:
    """Provincia del luogo senza "Provincia di" ("Provincia di Mantova" -> "Mantova"); "" se manca."""
    testo = luogo.get("admin2")
    if not isinstance(testo, str):
        return ""  # alcune frazioni non hanno la provincia
    # Open-Meteo usa anche l'apostrofo tipografico ("Provincia dell’Aquila")
    testo = testo.replace("’", "'").replace("‘", "'")
    return _PREFISSO_PROVINCIA.sub("", testo.strip())


def etichetta(luogo: dict) -> str:
    """"Nome (provincia, regione)": distingue gli omonimi italiani.

    La provincia si omette se ha lo stesso nome della citta' ("Roma (Lazio)", non
    "Roma (Roma, Lazio)"); le parti mancanti si saltano ("Nome" se mancano entrambe).
    """
    prov = provincia(luogo)
    # confronto senza l'articolo iniziale: "Provincia dell'Aquila" -> "Aquila" e' L'Aquila
    if normalizza(prov) == normalizza(luogo["name"]).removeprefix("l'"):
        prov = ""  # capoluogo: la provincia ripeterebbe il nome
    parti = [p for p in (prov, luogo.get("admin1")) if p]
    return f"{luogo['name']} ({', '.join(parti)})" if parti else luogo["name"]


def _abitanti(luogo: dict) -> int:
    """Abitanti del luogo (campo population); mancanti o non validi valgono 0."""
    valore = luogo.get("population")
    return valore if _numero(valore) and valore > 0 else 0


def _numero(valore) -> bool:
    """Vero per int e float, falso per i booleani (True e' un int in Python)."""
    return isinstance(valore, (int, float)) and not isinstance(valore, bool)


def _decimale(valore: float) -> str:
    """Una cifra decimale con la virgola italiana: 10.5 -> "10,5"."""
    return f"{valore:.1f}".replace(".", ",")


def _leggi_citta(city: str) -> tuple[str, str, bool]:
    """(nome, precisazione, predefinita): divide sulla prima virgola; vuota -> predefinita."""
    if not isinstance(city, str):
        raise ArgomentoNonValido("city deve essere un testo.")
    testo = city.strip()
    if len(testo) > LUNGHEZZA_MAX_CITTA:
        raise ArgomentoNonValido(f"city troppo lunga (massimo {LUNGHEZZA_MAX_CITTA} caratteri).")
    if not testo:
        return citta_predefinita(), "", True
    # "San Giovanni, Sicilia" -> nome "San Giovanni", precisazione "Sicilia"
    nome, _, precisazione = testo.partition(",")
    nome, precisazione = nome.strip(), precisazione.strip()
    if not nome:
        raise ArgomentoNonValido("manca il nome della città prima della virgola.")
    return nome, precisazione, False


def _controlla_days(days) -> None:
    """days deve essere un intero da 0 a 7 (i booleani non sono numeri di giorni)."""
    if not _numero(days) or isinstance(days, float) or not 0 <= days <= GIORNI_MAX:
        raise ArgomentoNonValido(f"days deve essere un intero da 0 a {GIORNI_MAX}, "
                                 f"ricevuto {days!r}.")


def _controlla_luogo(luogo: dict) -> None:
    """Un luogo del geocoding deve avere nome (testo), latitudine e longitudine (numeri)."""
    if not isinstance(luogo.get("name"), str) or not luogo["name"].strip():
        raise RispostaNonValida("un luogo del geocoding non ha il nome.")
    for campo in ("latitude", "longitude"):
        if not _numero(luogo.get(campo)):
            raise RispostaNonValida(f"il luogo {luogo['name']} non ha il campo {campo}.")


def scegli_citta(risultati: list[dict], nome: str,
                 precisazione: str) -> tuple[dict, list[dict]]:
    """Sceglie la citta' italiana tra i risultati del geocoding: restituisce (scelta, alternative).

    1. Candidati: solo i luoghi con lo stesso nome cercato (senza maiuscole e accenti). La
       ricerca di Open-Meteo e' anche per prefisso: "Paris" in Italia trova la frazione
       "Parise", "Roma" trova "Romana"; questi non sono la citta' cercata e si scartano.
       Nessun candidato -> CittaNonTrovata (anche una citta' estera finisce qui).
    2. Precisazione (dopo la virgola): restano i candidati con quella regione o provincia;
       nessuno -> CittaNonTrovata con l'elenco dei candidati, mai un ripiego silenzioso.
    3. Scelta: il candidato piu' popoloso (Open-Meteo non li ordina sempre per abitanti).
    4. Alternative: gli altri candidati con almeno il 5% degli abitanti della scelta, dal piu'
       popoloso; le frazioni minuscole non rendono "ambigua" una citta' grande.
    """
    if not risultati:
        # geocoding vuoto: nome sbagliato o citta' estera (la ricerca e' solo in Italia).
        # Prima il "non trovata": il modello non deve ridurlo a "copre solo l'Italia"
        raise CittaNonTrovata(f"nessuna città italiana chiamata «{nome}»: controlla il nome; "
                              "il servizio meteo copre solo l'Italia.")
    for luogo in risultati:
        _controlla_luogo(luogo)  # nome e coordinate presenti, altrimenti RispostaNonValida
    cercato = normalizza(nome)
    candidati, viste = [], set()
    for luogo in risultati:
        if normalizza(luogo["name"]) != cercato:
            continue  # nome diverso, trovato per prefisso: non e' la citta' cercata
        if etichetta(luogo) in viste:
            continue  # stessa localita' ripetuta (stesso nome, provincia e regione)
        viste.add(etichetta(luogo))
        candidati.append(luogo)
    if not candidati:
        simili = ", ".join(sorted({luogo["name"] for luogo in risultati}))
        raise CittaNonTrovata(f"nessuna città italiana chiamata «{nome}» (trovate solo "
                              f"località con nomi simili: {simili}). Il servizio meteo è "
                              "disponibile solo per le città italiane.")
    if precisazione:
        cercata = normalizza(precisazione)
        # la precisazione puo' essere la regione, la provincia o la provincia con "Provincia di"
        filtrati = [luogo for luogo in candidati
                    if cercata in {normalizza(str(luogo.get("admin1") or "")),
                                   normalizza(str(luogo.get("admin2") or "")),
                                   normalizza(provincia(luogo))}]
        if not filtrati:
            elenco = "; ".join(etichetta(luogo) for luogo in candidati)
            raise CittaNonTrovata(f"«{nome}, {precisazione}»: nessuna località con quella "
                                  f"precisazione. Località trovate con questo nome: {elenco}.")
        candidati = filtrati
    # ordinamento stabile: a parita' di abitanti resta l'ordine di Open-Meteo
    candidati.sort(key=_abitanti, reverse=True)
    scelto = candidati[0]
    soglia = _abitanti(scelto) * SOGLIA_ALTERNATIVE
    alternative = [luogo for luogo in candidati[1:] if _abitanti(luogo) >= soglia]
    return scelto, alternative


def _campo(dati: dict, sezione: str, chiave: str):
    """dati[sezione][chiave], oppure RispostaNonValida con il nome del campo mancante."""
    blocco = dati.get(sezione)
    if not isinstance(blocco, dict) or chiave not in blocco:
        raise RispostaNonValida(f"manca il campo {sezione}.{chiave} nella risposta del meteo.")
    return blocco[chiave]


def _testo(valore, nome: str) -> str:
    """Il valore deve essere un testo non vuoto."""
    if not isinstance(valore, str) or not valore:
        raise RispostaNonValida(f"il campo {nome} non è un testo.")
    return valore


def _codice(valore, nome: str) -> int:
    """Il valore deve essere un codice WMO intero."""
    if not _numero(valore) or valore != int(valore):
        raise RispostaNonValida(f"il campo {nome} non è un codice WMO.")
    return int(valore)


def _misura(valore, nome: str) -> float:
    """Il valore deve essere un numero."""
    if not _numero(valore):
        raise RispostaNonValida(f"il campo {nome} non è un numero.")
    return valore


def _oggi_locale(dati: dict) -> date:
    """Data di oggi nel fuso della citta' (campo timezone della risposta del meteo)."""
    fuso = _testo(dati.get("timezone"), "timezone")
    try:
        return _adesso().astimezone(ZoneInfo(fuso)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise RispostaNonValida(f"fuso orario sconosciuto: {fuso!r}.") from None


def _pulisci_data(testo: str) -> tuple[str, bool]:
    """(testo normalizzato senza articoli e parole di contorno, c'era "prossimo"?)."""
    # minuscole, senza accenti; "venerdi'" (accento con l'apostrofo) -> "venerdi"
    norma = _ACCENTO_APOSTROFO.sub(r"\1", normalizza(testo))
    norma = norma.replace("dopo domani", "dopodomani")  # scritto in due parole
    prossimo = False
    cambiato = True
    while cambiato:  # piu' parole insieme: "per il prossimo sabato", "a natale"
        cambiato = False
        for parola in _PAROLE_INIZIALI:
            if norma.startswith(parola):
                norma, cambiato = norma[len(parola):].strip(), True
        for parola in _PROSSIMO_INIZIALE:
            if norma.startswith(parola):
                norma, cambiato, prossimo = norma[len(parola):].strip(), True, True
        for parola in _PROSSIMO_FINALE:
            if norma.endswith(parola):
                norma, cambiato, prossimo = norma[:-len(parola)].strip(), True, True
    return norma, prossimo


def leggi_giorno(testo: str, oggi: date) -> date:
    """Legge il giorno chiesto dall'utente rispetto a `oggi` (data locale della citta').

    Il server legge "oggi", "domani", "dopodomani", "tra N giorni" e i giorni della settimana
    (il prossimo, oggi compreso); gli altri formati passano a leggi_data dell'esercizio 3.
    Testo non leggibile -> ArgomentoNonValido con i formati ammessi.
    """
    if not isinstance(testo, str):
        raise ArgomentoNonValido(f"date deve essere un testo; {FORMATI_DATA}.")
    norma, prossimo = _pulisci_data(testo)
    if not norma:
        raise ArgomentoNonValido(f"data vuota; {FORMATI_DATA}.")
    relativi = {"oggi": 0, "domani": 1, "dopodomani": 2}  # giorni da aggiungere a oggi
    if norma in relativi:
        return oggi + timedelta(days=relativi[norma])
    if trovato := _TRA_N_GIORNI.fullmatch(norma):
        # "tra 3 giorni" o "tra tre giorni": l'ultimo giorno e' oggi + 3 (il periodo da domani
        # lo costruisce leggi_periodo; oltre oggi + 7 lo segnala testo_meteo)
        quanti = (int(trovato[1]) if trovato[1].isdigit()
                  else _NUMERI_IN_LETTERE.get(trovato[1]))
        # "tra 0 giorni" non indica nessun giorno da domani: e' un errore come un numero illeggibile
        if quanti is None or quanti < 1 or quanti > _MAX_GIORNI_AVANTI:
            raise ArgomentoNonValido(f"numero di giorni non leggibile in «{testo.strip()}»; "
                                     f"{FORMATI_DATA}.")
        return oggi + timedelta(days=quanti)
    primo, _, resto = norma.partition(" ")
    if primo in _SETTIMANA and resto:
        # "sabato 7 novembre": conta la data, il nome del giorno e' solo di contorno
        norma = resto
    elif norma in _SETTIMANA:
        # giorni da aggiungere per arrivare al prossimo giorno con quel nome (0 = oggi)
        avanti = (_SETTIMANA.index(norma) - oggi.weekday()) % 7
        if avanti == 0 and prossimo:
            avanti = 7  # "giovedi' prossimo" detto di giovedi': la settimana dopo, non oggi
        return oggi + timedelta(days=avanti)
    try:
        # senza anno ("15 novembre") vale la prossima ricorrenza a partire da oggi
        return leggi_data(norma, riferimento=oggi)
    except ErroreData as errore:
        raise ArgomentoNonValido(f"data non leggibile «{testo.strip()}» ({errore}); "
                                 f"{FORMATI_DATA}.") from None


def leggi_periodo(testo: str, oggi: date) -> tuple[date, date]:
    """(primo, ultimo) giorno da mostrare per la data scritta dall'utente.

    "tra N giorni" sono gli N giorni da domani, oggi escluso (oggi e' sottinteso: e' il giorno
    in cui si scrive): il 2 ottobre "tra 2 giorni" -> (3 ottobre, 4 ottobre). Ogni altra data
    ("domani", "sabato", "15 novembre") e' un giorno solo: primo == ultimo.
    """
    # leggi_giorno controlla il testo e calcola l'ultimo giorno (per "tra N giorni": oggi + N)
    ultimo = leggi_giorno(testo, oggi)
    norma, _ = _pulisci_data(testo)  # stessa pulizia di leggi_giorno ("per tra 2 giorni"...)
    if _TRA_N_GIORNI.fullmatch(norma):
        return oggi + timedelta(days=1), ultimo  # da domani all'ultimo giorno compreso
    return ultimo, ultimo  # un giorno solo


def _oggi_della_citta(luogo: dict) -> date:
    """Data di oggi nel fuso della citta' scelta (campo timezone del geocoding)."""
    fuso = luogo.get("timezone")
    if not isinstance(fuso, str) or not fuso:
        raise RispostaNonValida(f"il luogo {luogo['name']} non ha il fuso orario.")
    try:
        return _adesso().astimezone(ZoneInfo(fuso)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise RispostaNonValida(f"fuso orario sconosciuto: {fuso!r}.") from None


def data_in_italiano(giorno: date) -> str:
    """date(2026, 11, 5) -> "giovedì 5 novembre 2026"."""
    return (f"{GIORNI_SETTIMANA[giorno.weekday()]} {giorno.day} {MESI[giorno.month - 1]} "
            f"{giorno.year}")


def _attuale(scelto: dict, dati: dict) -> list[str]:
    """Righe del meteo attuale: citta', temperatura con unita', condizioni, ora con fuso."""
    # ogni campo e' controllato: mancante o di tipo sbagliato -> RispostaNonValida
    temperatura = _misura(_campo(dati, "current", "temperature_2m"), "current.temperature_2m")
    codice = _codice(_campo(dati, "current", "weather_code"), "current.weather_code")
    # "2026-11-05T19:45" -> "2026-11-05 19:45" (ora locale della citta': timezone=auto)
    ora = _testo(_campo(dati, "current", "time"), "current.time").replace("T", " ")
    # unita' dalla risposta (es. "°C"): non scritte a mano nel codice
    unita = _testo(_campo(dati, "current_units", "temperature_2m"),
                   "current_units.temperature_2m")
    fuso = _testo(dati.get("timezone"), "timezone")
    sigla = dati.get("timezone_abbreviation")  # es. "GMT+1": facoltativa
    fuso_testo = f"{fuso} ({sigla})" if isinstance(sigla, str) and sigla else fuso
    return [f"Meteo attuale a {etichetta(scelto)}",
            f"- Temperatura: {_decimale(temperatura)} {unita}",
            f"- Condizioni: {condizione(codice)}",
            f"- Ora di riferimento: {ora}, ora locale {fuso_testo}"]


def _giorni_previsti(dati: dict) -> list[dict]:
    """Le previsioni giornaliere come elenco di giorni, dopo aver controllato le liste."""
    chiavi = ("time", "weather_code", "temperature_2m_max", "temperature_2m_min",
              "precipitation_probability_max")
    liste = {k: _campo(dati, "daily", k) for k in chiavi}
    if not all(isinstance(v, list) for v in liste.values()):
        raise RispostaNonValida("le previsioni giornaliere non sono elenchi.")
    if len({len(v) for v in liste.values()}) != 1:
        # liste parallele: un giorno per posizione, devono avere la stessa lunghezza
        raise RispostaNonValida("le previsioni giornaliere hanno elenchi di lunghezza diversa.")
    giorni = []
    for i, testo_data in enumerate(liste["time"]):  # posizione i = un giorno in tutte le liste
        try:
            giorno = date.fromisoformat(_testo(testo_data, "daily.time"))
        except ValueError:
            raise RispostaNonValida(f"data non valida nelle previsioni: {testo_data!r}.") from None
        pioggia = liste["precipitation_probability_max"][i]
        if pioggia is not None:  # None: dato non disponibile per quel giorno (Review Focus 1)
            _misura(pioggia, "daily.precipitation_probability_max")
        giorni.append({"giorno": giorno,
                       "codice": _codice(liste["weather_code"][i], "daily.weather_code"),
                       # temperature nulle (capita nell'ultimo giorno): "n.d.", come la pioggia
                       "massima": _misura_o_nulla(liste["temperature_2m_max"][i],
                                                  "daily.temperature_2m_max"),
                       "minima": _misura_o_nulla(liste["temperature_2m_min"][i],
                                                 "daily.temperature_2m_min"),
                       "pioggia": pioggia})
    return giorni


def _misura_o_nulla(valore, nome: str):
    """Un numero oppure None (dato non disponibile); qualsiasi altro valore non e' valido."""
    return None if valore is None else _misura(valore, nome)


def _temperatura(valore, unita: str) -> str:
    """"9,1 °C", oppure "n.d." se il valore non e' disponibile."""
    return "n.d." if valore is None else f"{_decimale(valore)} {unita}"


def _riga_giorno(previsto: dict, oggi: date, unita_t: str, unita_p: str) -> str:
    """"- oggi, giovedì 5 novembre 2026: coperto, minima 9,1 °C, massima 17,4 °C, pioggia 10 %"."""
    distanza = (previsto["giorno"] - oggi).days  # 0 = oggi, 1 = domani...
    prefisso = {0: "oggi, ", 1: "domani, "}.get(distanza, "")  # gli altri giorni senza prefisso
    # probabilita' di pioggia mancante -> "n.d." (non disponibile), non un errore
    pioggia = ("n.d." if previsto["pioggia"] is None
               else f"{round(previsto['pioggia'])} {unita_p}")
    return (f"- {prefisso}{data_in_italiano(previsto['giorno'])}: "
            f"{condizione(previsto['codice'])}, "
            f"minima {_temperatura(previsto['minima'], unita_t)}, "
            f"massima {_temperatura(previsto['massima'], unita_t)}, pioggia {pioggia}")


def _previsioni(dati: dict, giorni_previsti: list[dict]) -> list[str]:
    """Righe "Previsioni:" per i giorni indicati, con le unita' prese dalla risposta."""
    unita_t = _testo(_campo(dati, "daily_units", "temperature_2m_max"),
                     "daily_units.temperature_2m_max")
    unita_p = _testo(_campo(dati, "daily_units", "precipitation_probability_max"),
                     "daily_units.precipitation_probability_max")
    oggi = _oggi_locale(dati)  # per scrivere "oggi" e "domani" nel fuso della citta'
    return ["Previsioni:"] + [_riga_giorno(p, oggi, unita_t, unita_p) for p in giorni_previsti]


def _righe_piccola_localita(scelto: dict) -> list[str]:
    """Avviso per una localita' piccola (o senza abitanti): forse l'utente intendeva altro.

    Nessuna scelta silenziosa: "Parigi" in Italia e' una frazione di 31 abitanti, il modello
    deve poter dire che il meteo copre solo l'Italia.
    """
    abitanti = _abitanti(scelto)
    if abitanti >= ABITANTI_PICCOLA_LOCALITA:
        return []  # citta' abbastanza grande: nessun avviso
    quanti = f"{abitanti} abitanti" if abitanti else "abitanti non indicati"
    return [f"Attenzione: {etichetta(scelto)} è una piccola località ({quanti}): se l'utente "
            "intendeva una città estera, il servizio meteo copre solo l'Italia."]


def _righe_alternative(alternative: list[dict]) -> list[str]:
    """Omonimi dichiarati e domanda all'utente (nessuna riga se non ci sono alternative)."""
    if not alternative:
        return []
    primo = alternative[0]
    # esempio di scelta: "San Giovanni, Pordenone" (provincia, altrimenti regione)
    esempio = f"{primo['name']}, {provincia(primo) or primo.get('admin1') or ''}".rstrip(", ")
    elenco = "; ".join(etichetta(luogo) for luogo in alternative[:MAX_ALTERNATIVE])
    restanti = len(alternative) - MAX_ALTERNATIVE
    if restanti > 0:
        elenco += f" e altre {restanti}"  # quante non sono elencate
    return [f"Altre località con questo nome: {elenco}.",
            f'Chiedi all\'utente quale preferisce: può scrivere per esempio "{esempio}".']


def testo_meteo(city: str, days: int, data: str, client: httpx.Client, contatore) -> str:
    """Risultato del tool get_weather: meteo attuale, previsioni, alternative e fonte.

    Passi: argomenti -> geocoding -> scelta della citta' -> meteo -> testo. Ogni problema
    solleva un ErroreMeteo con la sua categoria.
    """
    # 1. argomenti: citta' (o predefinita), giorni, data
    nome, precisazione, predefinita = _leggi_citta(city)
    if not isinstance(data, str):
        raise ArgomentoNonValido(f"date deve essere un testo; {FORMATI_DATA}.")
    if not data.strip():
        # con una data days e' ignorato: il modello piccolo puo' riempire entrambi
        _controlla_days(days)
    righe = []  # righe del risultato, unite alla fine con un a capo
    if predefinita:
        # nessuna scelta silenziosa: si dichiara che si usa la citta' predefinita
        righe.append(f"Nessuna città indicata: uso la città predefinita, {nome}.")
    # 2. geocoding (solo Italia) e scelta della citta' tra gli omonimi
    scelto, alternative = scegli_citta(cerca_citta(client, contatore, nome), nome, precisazione)
    if predefinita:
        # citta' predefinita: scelta voluta, non si chiede all'utente quale omonimo intende
        alternative = []
    # 3. data precisa: oltre oggi + 7 si risponde subito, senza chiedere il meteo
    primo = giorno = None  # periodo chiesto dall'utente, dal primo al giorno (None = nessuno)
    if data.strip():
        # con una data, days e' ignorato: si chiedono i giorni fino a quella data
        oggi = _oggi_della_citta(scelto)
        # "tra 2 giorni" -> da domani a oggi + 2; le altre date -> primo == giorno
        primo, giorno = leggi_periodo(data, oggi)
        ultimo = oggi + timedelta(days=GIORNI_AVANTI_MAX)  # ultimo giorno con previsioni
        fuori = None
        if giorno > ultimo:
            fuori = (f"Nessuna previsione affidabile per {data_in_italiano(giorno)}: oltre "
                     f"{data_in_italiano(ultimo)} non ci sono previsioni affidabili.")
        elif giorno < oggi:
            fuori = (f"Il {giorno.day} {MESI[giorno.month - 1]} {giorno.year} è già passato: "
                     "sono disponibili solo il meteo attuale e le previsioni fino a "
                     f"{data_in_italiano(ultimo)}.")
        if fuori:
            # risultato normale, non un errore: nessuna chiamata al meteo, nessun valore
            return "\n".join(righe + [f"Località: {etichetta(scelto)}", fuori]
                             + _righe_piccola_localita(scelto)
                             + _righe_alternative(alternative) + [FONTE])
        days = (giorno - oggi).days + 1  # forecast_days: fino al giorno chiesto compreso
    # 4. meteo attuale (e previsioni) con le coordinate della citta' scelta
    dati = meteo(client, contatore, scelto["latitude"], scelto["longitude"], days)
    # 5. testo: meteo attuale, avviso, previsioni, alternative, fonte
    righe += _attuale(scelto, dati)
    righe += _righe_piccola_localita(scelto)  # subito dopo il nome della localita'
    if giorno is not None:
        # solo le righe del periodo chiesto (una sola riga se primo == giorno)
        scelti = [p for p in _giorni_previsti(dati) if primo <= p["giorno"] <= giorno]
        if not scelti or scelti[-1]["giorno"] != giorno:
            raise RispostaNonValida(f"le previsioni non contengono il {giorno.isoformat()}.")
        righe += _previsioni(dati, scelti)
    elif days:
        # la risposta vera ha `days` giorni; se ne ha di piu' si mostrano solo i primi `days`
        righe += _previsioni(dati, _giorni_previsti(dati)[:days])
    righe += _righe_alternative(alternative)
    righe.append(FONTE)
    return "\n".join(righe)
