from datetime import date

import pytest

from servizio import date_lavoro
from servizio.date_lavoro import (
    FESTIVITA, ErroreData, carica_festivita, e_lavorativo, festivita_del_giorno, normalizza,
    pasqua,
)


# --- Task 1: calendario e file delle festivita' ---

@pytest.mark.parametrize("anno, attesa", [
    (2000, date(2000, 4, 23)), (2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2038, date(2038, 4, 25)),
])
def test_pasqua(anno, attesa):
    assert pasqua(anno) == attesa


def test_pasquetta_giorno_dopo():
    assert festivita_del_giorno(date(2027, 3, 29)) == ["Lunedì dell'Angelo"]


def test_doppia_festivita_2011():
    assert set(festivita_del_giorno(date(2011, 4, 25))) == {
        "Festa della Liberazione", "Lunedì dell'Angelo"}


@pytest.mark.parametrize("giorno, nome", [
    ((1, 1), "Capodanno"), ((1, 6), "Epifania"), ((4, 25), "Festa della Liberazione"),
    ((5, 1), "Festa del Lavoro"), ((6, 2), "Festa della Repubblica"), ((8, 15), "Ferragosto"),
    ((10, 4), "San Francesco d'Assisi"), ((11, 1), "Ognissanti"),
    ((12, 8), "Immacolata Concezione"), ((12, 25), "Natale"), ((12, 26), "Santo Stefano"),
])
def test_festivita_fisse_2026(giorno, nome):
    assert nome in festivita_del_giorno(date(2026, *giorno))


def test_pasqua_e_festivita():
    assert festivita_del_giorno(date(2027, 3, 28)) == ["Pasqua"]


def test_san_francesco_dal_2026():
    assert festivita_del_giorno(date(2025, 10, 4)) == []          # 2025: non ancora festa
    assert festivita_del_giorno(date(2026, 10, 4)) == ["San Francesco d'Assisi"]
    assert e_lavorativo(date(2026, 10, 5))                         # lunedi' dopo: lavorativo


def test_lavorativo():
    assert e_lavorativo(date(2026, 11, 3))          # martedi'
    assert not e_lavorativo(date(2026, 11, 7))      # sabato
    assert not e_lavorativo(date(2026, 11, 8))      # domenica
    assert not e_lavorativo(date(2026, 12, 8))      # martedi' festivo


def test_file_valido_ha_13_voci():
    assert len(FESTIVITA) == 13


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
    percorso = tmp_path / "festivita.json"
    percorso.write_text(contenuto, encoding="utf-8")
    with pytest.raises(ErroreData) as errore:
        carica_festivita(percorso)
    assert motivo in str(errore.value)


def test_29_febbraio_ammesso_nel_file(tmp_path):
    percorso = tmp_path / "festivita.json"
    percorso.write_text('{"festivita": [{"nome": "X", "alias": ["x"], "data": "02-29"}]}',
                        encoding="utf-8")
    assert carica_festivita(percorso)[0].data == "02-29"


def test_normalizza():
    assert normalizza("  Lunedì  dell’Angelo ") == "lunedi dell'angelo"
    assert normalizza("1º Maggio") == "1 maggio"
    assert normalizza("1° maggio") == "1 maggio"


# --- Task 2: lettura delle date ---

from servizio.date_lavoro import leggi_data  # noqa: E402


@pytest.fixture
def oggi_fisso(monkeypatch):
    """Oggi = martedi' 3 novembre 2026."""
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2026, 11, 3))


def rifiuto(testo, riferimento=None):
    with pytest.raises(ErroreData) as errore:
        leggi_data(testo, riferimento)
    return str(errore.value)


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


def test_riferimento_per_le_date_senza_anno(oggi_fisso):
    assert leggi_data("ferragosto", date(2027, 3, 1)) == date(2027, 8, 15)
    assert leggi_data("natale", date(2027, 1, 1)) == date(2027, 12, 25)
    assert leggi_data("29 febbraio", date(2028, 3, 1)) == date(2032, 2, 29)


def test_pasqua_il_giorno_di_pasqua(monkeypatch):
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2027, 3, 28))
    assert leggi_data("pasqua") == date(2027, 3, 28)


def test_natale_oltre_il_2100(monkeypatch):
    monkeypatch.setattr(date_lavoro, "_oggi", lambda: date(2100, 12, 26))
    assert "2100" in rifiuto("natale")


def test_carattere_non_stampabile_nel_messaggio(oggi_fisso):
    assert "U+0001" in rifiuto("25\x01dicembre")


# --- Task 3: le tre operazioni (oggi = martedi' 2026-11-03) ---

from servizio.date_lavoro import AVVISO, calcola_scadenza, conta_giorni, info_giorno  # noqa: E402


def rifiuto_op(funzione, *args, **kwargs):
    with pytest.raises(ErroreData) as errore:
        funzione(*args, **kwargs)
    return str(errore.value)


def test_dicembre_estremi_compresi(oggi_fisso):
    r = conta_giorni("31/12/2026", "1/12/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"], r["conteggio"]) == (
        31, 21, "estremi compresi")
    assert r["festivita"] == [{"data": "2026-12-08", "nome": "Immacolata Concezione"},
                              {"data": "2026-12-25", "nome": "Natale"}]
    assert (r["da"], r["da_giorno"], r["a"], r["a_giorno"]) == (
        "2026-12-01", "martedì", "2026-12-31", "giovedì")
    assert r["operazione"] == "giorni" and r["avviso"] == AVVISO


def test_mancano_oggi_escluso(oggi_fisso):
    r = conta_giorni("6/11/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"], r["conteggio"]) == (
        3, 3, "oggi escluso")
    assert conta_giorni("6/11/2026", "oggi")["conteggio"] == "oggi escluso"
    assert conta_giorni("6/11/2026", " Oggi ")["giorni_lavorativi"] == 3


def test_domani_conta_estremi_compresi(oggi_fisso):
    r = conta_giorni("6/11/2026", "domani")
    assert (r["conteggio"], r["giorni_lavorativi"]) == ("estremi compresi", 3)


def test_stesso_giorno(oggi_fisso):
    r = conta_giorni("oggi")
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (0, 0)
    r = conta_giorni("3/11/2026", "3/11/2026")
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (1, 1)
    r = conta_giorni("7/11/2026", "7/11/2026")      # sabato
    assert (r["giorni_calendario"], r["giorni_lavorativi"]) == (1, 0)


def test_festivita_solo_feriali(oggi_fisso):
    r = conta_giorni("31/10/2026", "1/10/2026")     # 4 ottobre 2026 e' domenica
    assert r["festivita"] == []


def test_data_passata(oggi_fisso):
    assert "già passata" in rifiuto_op(conta_giorni, "1/11/2026")


def test_data_senza_anno_da_partenza(oggi_fisso):
    assert conta_giorni("ferragosto", "1/3/2027")["a"] == "2027-08-15"


def test_attraversa_29_febbraio(oggi_fisso):
    assert conta_giorni("1/3/2024", "28/2/2024")["giorni_calendario"] == 3


def test_manca_la_data(oggi_fisso):
    assert "manca la data" in rifiuto_op(conta_giorni, None)


def test_scadenza_lavorativi(oggi_fisso):
    r = calcola_scadenza(3, "4/12/2026")            # ven 4: lun 7, (mar 8 festivo), mer 9, gio 10
    assert (r["scadenza"], r["scadenza_giorno"], r["slittata_da"]) == (
        "2026-12-10", "giovedì", None)
    assert (r["operazione"], r["giorni"], r["tipo"], r["avviso"]) == (
        "scadenza", 3, "lavorativi", AVVISO)


def test_scadenza_da_oggi(oggi_fisso):
    assert calcola_scadenza(1)["scadenza"] == "2026-11-04"


def test_scadenza_calendario_slitta_domenica(oggi_fisso):
    r = calcola_scadenza(5, tipo="calendario")       # 2026-11-08 domenica
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-11-09", "2026-11-08", "domenica")


def test_scadenza_calendario_slitta_festivita(oggi_fisso):
    r = calcola_scadenza(5, "20/12/2026", "calendario")   # 2026-12-25 venerdi'
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-12-28", "2026-12-25", "Natale")


def test_scadenza_zero(oggi_fisso):
    assert calcola_scadenza(0, "7/11/2026")["scadenza"] == "2026-11-07"
    r = calcola_scadenza(0, "7/11/2026", "calendario")
    assert (r["scadenza"], r["slittata_da"], r["motivo_slittamento"]) == (
        "2026-11-09", "2026-11-07", "sabato")


def test_scadenza_29_febbraio(oggi_fisso):
    r = calcola_scadenza(1, "28/2/2024", "calendario")
    assert (r["scadenza"], r["scadenza_giorno"]) == ("2024-02-29", "giovedì")


@pytest.mark.parametrize("giorni, motivo", [
    (None, "manca il numero di giorni"), (-1, "negativo"), (3661, "3660")])
def test_scadenza_rifiuti(oggi_fisso, giorni, motivo):
    assert motivo in rifiuto_op(calcola_scadenza, giorni)


def test_scadenza_oltre_2100(oggi_fisso):
    assert "2100" in rifiuto_op(calcola_scadenza, 1, "31/12/2100", "calendario")


def test_tipo_non_valido(oggi_fisso):
    assert "tipo" in rifiuto_op(calcola_scadenza, 1, tipo="mesi")


def test_info_feriale(oggi_fisso):
    r = info_giorno("3/11/2026")
    assert (r["data"], r["giorno_settimana"], r["lavorativo"], r["fine_settimana"],
            r["festivita"]) == ("2026-11-03", "martedì", True, False, [])
    assert r["operazione"] == "giorno" and r["avviso"] == AVVISO


def test_info_sabato(oggi_fisso):
    r = info_giorno("7/11/2026")
    assert (r["giorno_settimana"], r["lavorativo"], r["fine_settimana"]) == (
        "sabato", False, True)


def test_info_festivo(oggi_fisso):
    r = info_giorno("2/6/2026")
    assert (r["giorno_settimana"], r["lavorativo"], r["festivita"]) == (
        "martedì", False, ["Festa della Repubblica"])


def test_info_doppia(oggi_fisso):
    assert len(info_giorno("25/4/2011")["festivita"]) == 2


def test_info_manca_la_data(oggi_fisso):
    assert "manca la data" in rifiuto_op(info_giorno, "")
