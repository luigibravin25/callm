# Test della logica dei giorni lavorativi (servizio/date_lavoro.py), senza HTTP:
# festivita', lettura delle date, conteggio dei giorni, scadenze, informazioni su un giorno.
# date costruisce le date attese; pytest per i test parametrizzati
from datetime import date

import pytest

# il modulo da provare e le sue funzioni del calendario
from servizio import date_lavoro
from servizio.date_lavoro import (
    FESTIVITA, ErroreData, carica_festivita, e_lavorativo, festivita_del_giorno, normalizza,
    pasqua,
)


# --- Task 1: calendario e file delle festivita' ---

# Verifica il calcolo della data di Pasqua su anni noti (da cui dipende anche Pasquetta).
@pytest.mark.parametrize("anno, attesa", [
    (2000, date(2000, 4, 23)), (2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2038, date(2038, 4, 25)),
])
def test_pasqua(anno, attesa):
    assert pasqua(anno) == attesa


# Verifica che Pasquetta (Lunedi' dell'Angelo) sia il giorno dopo Pasqua.
def test_pasquetta_giorno_dopo():
    assert festivita_del_giorno(date(2027, 3, 29)) == ["Lunedì dell'Angelo"]


# Verifica che un giorno con due feste (25 aprile 2011 = Pasquetta) le riporti entrambe.
def test_doppia_festivita_2011():
    assert set(festivita_del_giorno(date(2011, 4, 25))) == {
        "Festa della Liberazione", "Lunedì dell'Angelo"}


# Verifica le 11 festivita' a data fissa del 2026: (mese, giorno) e nome atteso.
@pytest.mark.parametrize("giorno, nome", [
    ((1, 1), "Capodanno"), ((1, 6), "Epifania"), ((4, 25), "Festa della Liberazione"),
    ((5, 1), "Festa del Lavoro"), ((6, 2), "Festa della Repubblica"), ((8, 15), "Ferragosto"),
    ((10, 4), "San Francesco d'Assisi"), ((11, 1), "Ognissanti"),
    ((12, 8), "Immacolata Concezione"), ((12, 25), "Natale"), ((12, 26), "Santo Stefano"),
])
def test_festivita_fisse_2026(giorno, nome):
    # *giorno spacchetta la coppia (mese, giorno) negli argomenti di date()
    assert nome in festivita_del_giorno(date(2026, *giorno))


# Verifica che anche Pasqua sia elencata tra le festivita'.
def test_pasqua_e_festivita():
    assert festivita_del_giorno(date(2027, 3, 28)) == ["Pasqua"]


# Verifica che San Francesco (4 ottobre) sia festa solo dal 2026, anno della nuova legge.
def test_san_francesco_dal_2026():
    assert festivita_del_giorno(date(2025, 10, 4)) == []          # 2025: non ancora festa
    assert festivita_del_giorno(date(2026, 10, 4)) == ["San Francesco d'Assisi"]
    assert e_lavorativo(date(2026, 10, 5))                         # lunedi' dopo: lavorativo


# Verifica la regola del giorno lavorativo: non sabato, non domenica, non festivo.
def test_lavorativo():
    assert e_lavorativo(date(2026, 11, 3))          # martedi'
    assert not e_lavorativo(date(2026, 11, 7))      # sabato
    assert not e_lavorativo(date(2026, 11, 8))      # domenica
    assert not e_lavorativo(date(2026, 12, 8))      # martedi' festivo


# Verifica che il file vero servizio/festivita.json si carichi con tutte le 13 festivita'.
def test_file_valido_ha_13_voci():
    assert len(FESTIVITA) == 13


# Verifica che un file delle festivita' sbagliato sia rifiutato con un motivo preciso:
# JSON rotto, data impossibile, festa mobile sconosciuta, alias doppio, ne' data ne' mobile,
# sia data sia mobile, nome mancante. Ogni riga: contenuto del file, parola attesa nel messaggio.
@pytest.mark.parametrize("contenuto, motivo", [
    ("{rotto", "JSON"),
    ('{"festivita": [{"nome": "X", "alias": ["x"], "data": "02-30"}]}', "X"),
    ('{"festivita": [{"nome": "X", "alias": ["x"], "mobile": "luna"}]}', "luna"),
    ('{"festivita": [{"nome": "A", "alias": ["uno"], "data": "01-01"}, '
     '{"nome": "B", "alias": ["uno"], "data": "01-02"}]}', "uno"),
    ('{"festivita": [{"nome": "X", "alias": ["x"]}]}', "X"),
    ('{"festivita": [{"nome": "X", "alias": ["x"], "data": "01-01", "mobile": "pasqua"}]}', "X"),
    ('{"festivita": [{"alias": ["x"], "data": "01-01"}]}', "nome"),
])
def test_file_non_valido(tmp_path, contenuto, motivo):
    # preparazione: scrive il file finto nella cartella temporanea data da pytest (tmp_path)
    percorso = tmp_path / "festivita.json"
    percorso.write_text(contenuto, encoding="utf-8")
    # azione e controllo: il caricamento solleva ErroreData con il motivo atteso
    with pytest.raises(ErroreData) as errore:
        carica_festivita(percorso)
    assert motivo in str(errore.value)


# Verifica che "02-29" sia accettato nel file: esiste negli anni bisestili.
def test_29_febbraio_ammesso_nel_file(tmp_path):
    percorso = tmp_path / "festivita.json"
    percorso.write_text('{"festivita": [{"nome": "X", "alias": ["x"], "data": "02-29"}]}',
                        encoding="utf-8")
    assert carica_festivita(percorso)[0].data == "02-29"


# Verifica la normalizzazione dei nomi: minuscole, niente accenti, spazi singoli, apostrofo
# dritto, "1º" e "1°" come "1". Serve a riconoscere le feste scritte in modi diversi.
def test_normalizza():
    assert normalizza("  Lunedì  dell’Angelo ") == "lunedi dell'angelo"
    assert normalizza("1º Maggio") == "1 maggio"
    assert normalizza("1° maggio") == "1 maggio"


# --- Task 2: lettura delle date ---

# la funzione che trasforma un testo in una data
from servizio.date_lavoro import leggi_data  # noqa: E402


# Fixture: "oggi" fisso, cosi' "domani", "natale" o "25 dicembre" danno sempre la stessa data.
@pytest.fixture
def oggi_fisso(monkeypatch):
    """Oggi = martedi' 3 novembre 2026."""
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2026, 11, 3))


# Supporto: si aspetta che leggi_data rifiuti il testo e restituisce il messaggio d'errore.
def rifiuto(testo, riferimento=None):
    with pytest.raises(ErroreData) as errore:
        leggi_data(testo, riferimento)
    return str(errore.value)


# Verifica i formati accettati: ISO, giorno/mese/anno con / - o ., mese a parole, date senza
# anno (la prossima a partire da oggi), oggi e domani, nomi di feste, 29 febbraio bisestile,
# limiti 1900 e 2100. Ogni riga: testo scritto dall'utente, data attesa.
@pytest.mark.parametrize("testo, attesa", [
    ("2026-12-25", date(2026, 12, 25)), ("25/12/2026", date(2026, 12, 25)),
    ("25-12-2026", date(2026, 12, 25)), ("25.12.2026", date(2026, 12, 25)),
    ("5/1/2027", date(2027, 1, 5)), ("03/04/2026", date(2026, 4, 3)),
    ("25 dicembre 2026", date(2026, 12, 25)), ("25 Dicembre 2026", date(2026, 12, 25)),
    ("1° maggio 2027", date(2027, 5, 1)), ("1º maggio 2027", date(2027, 5, 1)),
    ("25 dicembre", date(2026, 12, 25)), ("1 gennaio", date(2027, 1, 1)),
    ("3 novembre", date(2026, 11, 3)), ("oggi", date(2026, 11, 3)),
    ("domani", date(2026, 11, 4)), (" Oggi ", date(2026, 11, 3)),
    ("natale", date(2026, 12, 25)), ("Natale 2027", date(2027, 12, 25)),
    ("pasqua", date(2027, 3, 28)), ("pasqua 2026", date(2026, 4, 5)),
    ("pasquetta 2027", date(2027, 3, 29)), ("la Liberazione 2026", date(2026, 4, 25)),
    ("lunedì dell’angelo 2027", date(2027, 3, 29)), ("befana", date(2027, 1, 6)),
    ("ognissanti", date(2027, 11, 1)), ("san francesco", date(2027, 10, 4)),
    ("29/02/2024", date(2024, 2, 29)), ("29/02/2000", date(2000, 2, 29)),
    ("29 febbraio", date(2028, 2, 29)), ("1/1/1900", date(1900, 1, 1)),
    ("31/12/2100", date(2100, 12, 31)), ("l'immacolata", date(2026, 12, 8)),
])
def test_formati(oggi_fisso, testo, attesa):
    assert leggi_data(testo) == attesa


# Verifica i rifiuti con un motivo chiaro: testo vuoto o non riconosciuto, giorno o mese
# impossibili, 29 febbraio non bisestile, anno a 2 cifre, separatori misti, fuori 1900-2100,
# festa sconosciuta. Ogni riga: testo, parola attesa nel messaggio d'errore.
@pytest.mark.parametrize("testo, motivo", [
    ("", "vuota"), ("   ", "vuota"),
    ("domattina", "formato non riconosciuto"),
    ("2026-12-25T10:00", "formato non riconosciuto"),
    ("31/02/2026", "febbraio"), ("31/04/2026", "aprile ha 30 giorni"),
    ("00/01/2026", "giorno"), ("2026-13-01", "mese"),
    ("29/02/2027", "il 2027 non è bisestile"), ("29/02/1900", "il 1900 non è bisestile"),
    ("29/02/2100", "il 2100 non è bisestile"),
    ("25/12/26", "anno a 2 cifre"), ("25/12-2026", "separatori"),
    ("31/12/1899", "1900"), ("1/1/2101", "2100"),
    ("festa della mamma", "festività sconosciuta"),
    ("san francesco 2025", "dal 2026"), ("31 aprile", "aprile ha 30 giorni"),
    ("32 dicembre 2026", "dicembre ha 31 giorni"),
])
def test_rifiuti_date(oggi_fisso, testo, motivo):
    assert motivo in rifiuto(testo)


# Verifica che una data senza anno si cerchi a partire dalla data di riferimento passata
# (non da oggi): il 29 febbraio dopo marzo 2028 e' quello del 2032.
def test_riferimento_per_le_date_senza_anno(oggi_fisso):
    assert leggi_data("ferragosto", date(2027, 3, 1)) == date(2027, 8, 15)
    assert leggi_data("natale", date(2027, 1, 1)) == date(2027, 12, 25)
    assert leggi_data("29 febbraio", date(2028, 3, 1)) == date(2032, 2, 29)


# Verifica che il giorno stesso di Pasqua "pasqua" sia oggi, non la Pasqua dell'anno dopo.
def test_pasqua_il_giorno_di_pasqua(monkeypatch):
    # preparazione: oggi e' Pasqua 2027
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2027, 3, 28))
    assert leggi_data("pasqua") == date(2027, 3, 28)


# Verifica che il prossimo Natale, se cade oltre il 2100, sia rifiutato (limite del calendario).
def test_natale_oltre_il_2100(monkeypatch):
    # preparazione: oggi e' il 26 dicembre 2100, il prossimo Natale sarebbe nel 2101
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2100, 12, 26))
    assert "2100" in rifiuto("natale")


# Verifica che un carattere di controllo sia mostrato nel messaggio come codice U+0001.
def test_carattere_non_stampabile_nel_messaggio(oggi_fisso):
    assert "U+0001" in rifiuto("25\x01dicembre")


# --- Task 3: le tre operazioni (oggi = martedi' 2026-11-03) ---

# le tre operazioni (giorni, scadenza, giorno) e l'avviso di risultato non normativo
from servizio.date_lavoro import AVVISO, calcola_scadenza, conta_giorni, info_giorno  # noqa: E402


# Supporto: chiama una delle operazioni, si aspetta un ErroreData e ne restituisce il messaggio.
def rifiuto_op(funzione, *args, **kwargs):
    with pytest.raises(ErroreData) as errore:
        funzione(*args, **kwargs)
    return str(errore.value)


# Verifica il conteggio di dicembre 2026 con entrambe le date: 31 giorni di calendario,
# 21 lavorativi, festivita' feriali elencate, giorni della settimana e avviso.
def test_dicembre_estremi_compresi(oggi_fisso):
    r = conta_giorni("31/12/2026", "1/12/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"], r["conteggio"]) == (
        31, 21, "estremi compresi")
    assert r["festivita"] == [{"data": "2026-12-08", "nome": "Immacolata Concezione"},
                              {"data": "2026-12-25", "nome": "Natale"}]
    assert (r["da"], r["da_giorno"], r["a"], r["a_giorno"]) == (
        "2026-12-01", "martedì", "2026-12-31", "giovedì")
    assert r["operazione"] == "giorni" and r["avviso"] == AVVISO


# Verifica "quanti giorni mancano": partendo da oggi (sottinteso o scritto), oggi non si conta.
def test_mancano_oggi_escluso(oggi_fisso):
    r = conta_giorni("6/11/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"], r["conteggio"]) == (
        3, 3, "oggi escluso")
    assert conta_giorni("6/11/2026", "oggi")["conteggio"] == "oggi escluso"
    assert conta_giorni("6/11/2026", " Oggi ")["giorni_lavorativi"] == 3


# Verifica che partendo da "domani" si contino entrambi gli estremi.
def test_domani_conta_estremi_compresi(oggi_fisso):
    r = conta_giorni("6/11/2026", "domani")
    assert (r["conteggio"], r["giorni_lavorativi"]) == ("estremi compresi", 3)


# Verifica i casi di un giorno solo: da oggi a oggi fa 0; stessa data esplicita fa 1
# (0 lavorativi se e' sabato).
def test_stesso_giorno(oggi_fisso):
    r = conta_giorni("oggi")
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (0, 0)
    r = conta_giorni("3/11/2026", "3/11/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (1, 1)
    r = conta_giorni("7/11/2026", "7/11/2026")      # sabato
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (1, 0)


# Verifica che si elenchino solo le feste che cadono in giorni feriali (gia' di riposo altrimenti).
def test_festivita_solo_feriali(oggi_fisso):
    r = conta_giorni("31/10/2026", "1/10/2026")     # 4 ottobre 2026 e' domenica
    assert r["festivita"] == []


# Verifica che contare fino a una data gia' passata sia un errore esplicito.
def test_data_passata(oggi_fisso):
    assert "già passata" in rifiuto_op(conta_giorni, "1/11/2026")


# Verifica che la data d'arrivo senza anno sia cercata dopo la data di partenza.
def test_data_senza_anno_da_partenza(oggi_fisso):
    assert conta_giorni("ferragosto", "1/3/2027")["a"] == "2027-08-15"


# Verifica che il 29 febbraio di un anno bisestile sia contato (28/2, 29/2, 1/3 = 3 giorni).
def test_attraversa_29_febbraio(oggi_fisso):
    assert conta_giorni("1/3/2024", "28/2/2024")["giorni_calendario"] == 3


# Verifica che senza data d'arrivo l'operazione dica cosa manca.
def test_manca_la_data(oggi_fisso):
    assert "manca la data" in rifiuto_op(conta_giorni, None)


# Verifica la scadenza in giorni lavorativi: salta il fine settimana e la festa dell'8 dicembre.
def test_scadenza_lavorativi(oggi_fisso):
    r = calcola_scadenza(3, "4/12/2026")            # ven 4: lun 7, (mar 8 festivo), mer 9, gio 10
    assert (r["scadenza"], r["scadenza_giorno"], r["slittata_da"]) == (
        "2026-12-10", "giovedì", None)
    assert (r["operazione"], r["giorni"], r["tipo"], r["avviso"]) == (
        "scadenza", 3, "lavorativi", AVVISO)


# Verifica che senza data di partenza la scadenza si conti da oggi.
def test_scadenza_da_oggi(oggi_fisso):
    assert calcola_scadenza(1)["scadenza"] == "2026-11-04"


# Verifica che una scadenza di calendario che cade di domenica slitti al lunedi'.
def test_scadenza_calendario_slitta_domenica(oggi_fisso):
    r = calcola_scadenza(5, tipo="calendario")       # 2026-11-08 domenica
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-11-09", "2026-11-08", "domenica")


# Verifica lo slittamento oltre piu' giorni non lavorativi: Natale (venerdi'), sabato, domenica;
# il motivo riportato e' la festa del giorno calcolato.
def test_scadenza_calendario_slitta_festivita(oggi_fisso):
    r = calcola_scadenza(5, "20/12/2026", "calendario")   # 2026-12-25 venerdi'
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-12-28", "2026-12-25", "Natale")


# Verifica zero giorni: in lavorativi la data resta quella di partenza; in calendario, se e'
# sabato, slitta al lunedi'.
def test_scadenza_zero(oggi_fisso):
    assert calcola_scadenza(0, "7/11/2026")["scadenza"] == "2026-11-07"
    r = calcola_scadenza(0, "7/11/2026", "calendario")
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-11-09", "2026-11-07", "sabato")


# Verifica che il giorno dopo il 28 febbraio 2024 (bisestile) sia il 29.
def test_scadenza_29_febbraio(oggi_fisso):
    r = calcola_scadenza(1, "28/2/2024", "calendario")
    assert (r["scadenza"], r["scadenza_giorno"]) == ("2024-02-29", "giovedì")


# Verifica i rifiuti sul numero di giorni: mancante, negativo, oltre il massimo di 3660.
@pytest.mark.parametrize("giorni, motivo", [
    (None, "manca il numero di giorni"), (-1, "negativo"), (3661, "3660")])
def test_scadenza_rifiuti(oggi_fisso, giorni, motivo):
    assert motivo in rifiuto_op(calcola_scadenza, giorni)


# Verifica che una scadenza oltre il 2100 sia rifiutata (limite del calendario).
def test_scadenza_oltre_2100(oggi_fisso):
    assert "2100" in rifiuto_op(calcola_scadenza, 1, "31/12/2100", "calendario")


# Verifica che un tipo diverso da "lavorativi" o "calendario" sia rifiutato.
def test_tipo_non_valido(oggi_fisso):
    assert "tipo" in rifiuto_op(calcola_scadenza, 1, tipo="mesi")


# Verifica le informazioni su un martedi' qualunque: lavorativo, non fine settimana, nessuna festa.
def test_info_feriale(oggi_fisso):
    r = info_giorno("3/11/2026")
    assert (r["data"], r["giorno_settimana"], r["lavorativo"], r["fine_settimana"],
            r["festivita"]) == ("2026-11-03", "martedì", True, False, [])
    assert r["operazione"] == "giorno" and r["avviso"] == AVVISO


# Verifica il sabato: fine settimana e non lavorativo.
def test_info_sabato(oggi_fisso):
    r = info_giorno("7/11/2026")
    assert (r["giorno_settimana"], r["lavorativo"], r["fine_settimana"]) == (
        "sabato", False, True)


# Verifica un festivo in settimana (2 giugno 2026, martedi'): non lavorativo, con il nome.
def test_info_festivo(oggi_fisso):
    r = info_giorno("2/6/2026")
    assert (r["giorno_settimana"], r["lavorativo"], r["festivita"]) == (
        "martedì", False, ["Festa della Repubblica"])


# Verifica il giorno con due feste (25 aprile 2011): entrambe nell'elenco.
def test_info_doppia(oggi_fisso):
    assert len(info_giorno("25/4/2011")["festivita"]) == 2


# Verifica che una data vuota sia rifiutata con "manca la data".
def test_info_manca_la_data(oggi_fisso):
    assert "manca la data" in rifiuto_op(info_giorno, "")
