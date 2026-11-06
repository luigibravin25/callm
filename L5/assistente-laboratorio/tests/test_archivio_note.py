# Test dell'archivio delle note (mcp_note/archivio.py): funzioni Python su SQLite,
# provate direttamente senza il server MCP.

# espressioni regolari (formato della data) e SQLite (lettura diretta dell'archivio)
import re
import sqlite3

import pytest

# il codice da verificare
from mcp_note.archivio import (ErroreNote, aggiungi, elenca, elimina, leggi,
                               percorso_archivio)


# archivio temporaneo nuovo per ogni test: si parte sempre da zero note
@pytest.fixture
def db(tmp_path):
    return tmp_path / "note.sqlite"


# una nota nuova ha ID 1, testo senza spazi ai bordi e data "AAAA-MM-GG hh:mm:ss"
def test_aggiungi_restituisce_id_e_data(db):
    nota = aggiungi("  consegnare il report venerdì  ", db)
    assert nota["id"] == 1
    assert nota["testo"] == "consegnare il report venerdì"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", nota["creata"])


# l'elenco parte dalla nota piu' recente e rispetta il limite; il totale conta tutte le note
def test_elenca_dalla_piu_recente(db):
    for t in ("uno", "due", "tre"):
        aggiungi(t, db)
    lista, totale = elenca(10, db)
    assert [n["id"] for n in lista] == [3, 2, 1] and totale == 3
    lista, totale = elenca(2, db)  # solo 2, ma il totale resta 3
    assert [n["id"] for n in lista] == [3, 2] and totale == 3


# archivio vuoto: lista vuota e totale 0, nessun errore
def test_elenca_vuoto(db):
    assert elenca(10, db) == ([], 0)


# un testo vuoto o di soli spazi e' rifiutato con un messaggio che dice cosa fare
@pytest.mark.parametrize("testo", ["", "   "])
def test_testo_vuoto(db, testo):
    with pytest.raises(ErroreNote) as e:
        aggiungi(testo, db)
    assert str(e.value) == "Il testo della nota è vuoto: scrivi che cosa ricordare."


# oltre 500 caratteri la nota e' rifiutata e l'archivio resta vuoto
def test_testo_troppo_lungo(db):
    with pytest.raises(ErroreNote) as e:
        aggiungi("x" * 501, db)
    assert str(e.value) == "Il testo della nota è troppo lungo: 501 caratteri, massimo 500."
    assert elenca(10, db) == ([], 0)  # nessuna nota salvata


# caso limite: 500 caratteri esatti sono ammessi
def test_testo_500_accettato(db):
    assert len(aggiungi("x" * 500, db)["testo"]) == 500


# limit ammette 1-50: fuori intervallo un errore con il valore ricevuto
@pytest.mark.parametrize("n", [0, 51, -1])
def test_limit_fuori_intervallo(db, n):
    with pytest.raises(ErroreNote) as e:
        elenca(n, db)
    assert str(e.value) == f"limit deve essere tra 1 e 50, ricevuto {n}."


# True in Python vale 1, ma non e' un numero valido per limit
def test_limit_booleano_rifiutato(db):
    with pytest.raises(ErroreNote):
        elenca(True, db)


# elimina restituisce la nota cancellata (per il messaggio) e la nota non si legge piu'
def test_elimina_restituisce_la_nota(db):
    aggiungi("uno", db)
    eliminata = elimina(1, db)
    assert eliminata["id"] == 1 and eliminata["testo"] == "uno"
    with pytest.raises(ErroreNote) as e:
        leggi(1, db)
    assert str(e.value) == "La nota 1 non esiste."


# eliminare un ID che non c'e' da' errore e lascia intatte le altre note
def test_elimina_inesistente_non_cambia_nulla(db):
    aggiungi("uno", db)
    aggiungi("due", db)
    with pytest.raises(ErroreNote) as e:
        elimina(99, db)
    assert str(e.value) == "La nota 99 non esiste: nessuna nota eliminata."
    assert elenca(10, db)[1] == 2  # il totale e' ancora 2


# un ID eliminato non torna: la nota successiva prende il 3, non il 2
def test_id_non_riusati(db):
    aggiungi("uno", db)
    aggiungi("due", db)
    elimina(2, db)
    assert aggiungi("tre", db)["id"] == 3


# la nota e' davvero scritta su disco: una connessione nuova la ritrova
def test_persistenza_tra_connessioni(db):
    aggiungi("resta", db)
    con = sqlite3.connect(db)  # connessione indipendente dall'archivio
    try:
        assert con.execute("SELECT testo FROM note").fetchall() == [("resta",)]
    finally:
        con.close()


# ID non validi (booleano, zero, negativo) rifiutati senza cancellare nulla
@pytest.mark.parametrize("note_id", [True, 0, -3])
def test_note_id_non_valido_rifiutato(db, note_id):
    aggiungi("uno", db)
    with pytest.raises(ErroreNote):
        elimina(note_id, db)
    assert elenca(10, db)[1] == 1  # la nota c'e' ancora


# apostrofi, accenti, virgolette ed emoji si salvano e si rileggono uguali
def test_testo_con_caratteri_speciali(db):
    testo = "l'esame è \"lunedì\" 🎓"
    aggiungi(testo, db)
    assert leggi(1, db)["testo"] == testo


# un archivio che non si apre da' un errore leggibile, non un'eccezione di SQLite
def test_archivio_non_accessibile(tmp_path):
    # una cartella al posto del file: SQLite non la puo' aprire
    with pytest.raises(ErroreNote) as e:
        aggiungi("x", tmp_path)
    assert str(e.value).startswith("Archivio delle note non accessibile:")


# la cartella dell'archivio si crea da sola se non esiste (es. dati/ al primo avvio)
def test_cartella_creata_se_manca(tmp_path):
    db = tmp_path / "nuova" / "note.sqlite"
    aggiungi("x", db)
    assert db.exists()


# la variabile NOTE_DB sceglie il file dell'archivio
def test_percorso_da_note_db(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTE_DB", str(tmp_path / "altro.sqlite"))
    assert percorso_archivio() == tmp_path / "altro.sqlite"


# senza NOTE_DB si usa dati/note.sqlite dentro il progetto
def test_percorso_predefinito(monkeypatch):
    monkeypatch.delenv("NOTE_DB", raising=False)  # tolta per questo test
    assert percorso_archivio().as_posix().endswith("assistente-laboratorio/dati/note.sqlite")


# senza percorso esplicito aggiungi ed elenca leggono NOTE_DB
def test_senza_percorso_usa_note_db(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTE_DB", str(tmp_path / "env.sqlite"))
    aggiungi("da env")
    assert elenca()[0][0]["testo"] == "da env"


# l'ordine dell'elenco segue l'ID, non la data (che puo' tornare indietro con l'ora legale)
def test_ordine_per_id_anche_con_date_fuori_ordine(db):
    # cambio dell'ora legale: l'ora 02:00-03:00 si ripete e una nota piu' recente puo' avere
    # una data "minore"; l'ordine deve seguire l'ID (sempre crescente)
    aggiungi("prima", db)
    aggiungi("seconda", db)
    # si scrivono a mano date invertite: la nota 2 risulta "piu' vecchia" della 1
    con = sqlite3.connect(db)
    with con:
        con.execute("UPDATE note SET creata = '2026-10-25 02:30:00' WHERE id = 1")
        con.execute("UPDATE note SET creata = '2026-10-25 02:10:00' WHERE id = 2")
    con.close()
    assert [n["id"] for n in elenca(10, db)[0]] == [2, 1]  # prima la 2: ID piu' alto
