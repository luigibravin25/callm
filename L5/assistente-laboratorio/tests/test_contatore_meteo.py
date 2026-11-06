"""Test delle categorie di errore del meteo e del contatore del limite giornaliero.

Nessuna rete: il contatore e' un file SQLite in una cartella temporanea e l'istante corrente e'
fisso, cosi' i giorni sono controllati.
"""
# date con fuso (per un istante fisso) e percorsi
from datetime import datetime, timezone
from pathlib import Path

import pytest

# il codice da verificare: errori del meteo e contatore delle richieste
from mcp_meteo import errori
from mcp_meteo.contatore import (LIMITE_PREDEFINITO, Contatore, limite_giornaliero,
                                 percorso_contatore)

# istante fisso usato come "adesso": i test non dipendono dal giorno in cui girano
ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # giovedi' 5 novembre, 13:00 a Roma


# crea un contatore isolato: file nella cartella temporanea del test, orologio fermo
def _contatore(tmp_path: Path, limite: int, istante: datetime = ISTANTE) -> Contatore:
    """Contatore su un file temporaneo con un orologio fisso."""
    return Contatore(tmp_path / "contatore.sqlite", limite, lambda: istante)


# tutte le classi d'errore hanno la stessa base e il messaggio "Categoria: dettaglio"
def test_categorie_nel_messaggio():
    """Ogni errore e' un ErroreMeteo e il messaggio inizia con la sua categoria."""
    # il messaggio inizia con la categoria: il modello capisce che tipo di errore e'
    assert str(errori.CittaNonTrovata("Xyz")) == "Città non trovata: Xyz"
    for classe in (errori.ArgomentoNonValido, errori.CittaNonTrovata, errori.TimeoutMeteo,
                   errori.ReteNonRaggiungibile, errori.ServizioNonDisponibile,
                   errori.RispostaNonValida, errori.LimiteRaggiunto,
                   errori.ContatoreNonAccessibile):
        assert issubclass(classe, errori.ErroreMeteo)
        assert str(classe("x")) == f"{classe.CATEGORIA}: x"


# ogni richiesta registrata aumenta di uno il conteggio del giorno
def test_registra_conta(tmp_path):
    """registra() restituisce il conteggio di oggi, che cresce di uno a ogni richiesta."""
    contatore = _contatore(tmp_path, 3)
    assert [contatore.registra() for _ in range(3)] == [1, 2, 3]
    assert contatore.conteggio_di_oggi() == 3


# arrivati al limite la richiesta e' rifiutata, con un messaggio chiaro per l'utente
def test_limite_raggiunto_senza_incremento(tmp_path):
    """Al limite: LimiteRaggiunto con "riprova domani" e il conteggio non cresce."""
    # preparazione: limite 2, gia' raggiunto con due richieste
    contatore = _contatore(tmp_path, 2)
    contatore.registra()
    contatore.registra()
    # azione: la terza richiesta deve sollevare LimiteRaggiunto
    with pytest.raises(errori.LimiteRaggiunto) as info:
        contatore.registra()
    assert "2 richieste" in str(info.value) and "riprova domani" in str(info.value)
    assert contatore.conteggio_di_oggi() == 2  # la richiesta bloccata non conta


# il conteggio sta nel file, non in memoria: un riavvio non lo azzera
def test_sopravvive_a_un_nuovo_contatore(tmp_path):
    """Un nuovo Contatore sullo stesso file prosegue il conteggio (server riavviato)."""
    # il server meteo riparte a ogni chiamata: il conteggio deve restare nel file
    _contatore(tmp_path, 10).registra()
    nuovo = _contatore(tmp_path, 10)
    assert nuovo.registra() == 2


# il giorno si decide con l'ora di Roma, non con quella UTC
def test_riparte_il_giorno_dopo(tmp_path):
    """Dopo la mezzanotte di Roma il conteggio di oggi riparte da zero."""
    _contatore(tmp_path, 10).registra()
    # 23:30 UTC del 5 novembre e' gia' il 6 novembre a Roma
    domani = _contatore(tmp_path, 10, datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc))
    assert domani.conteggio_di_oggi() == 0


# lettura del limite da METEO_LIMITE_GIORNALIERO: valore usato, avviso se non valido
@pytest.mark.parametrize("valore, atteso, avviso", [
    # (testo della variabile, limite atteso, avviso su stderr); None = variabile assente
    ("50", 50, False), (None, LIMITE_PREDEFINITO, False), ("", LIMITE_PREDEFINITO, False),
    ("0", LIMITE_PREDEFINITO, True), ("-3", LIMITE_PREDEFINITO, True),
    ("abc", LIMITE_PREDEFINITO, True)])
def test_limite_da_variabile(monkeypatch, capsys, valore, atteso, avviso):
    """METEO_LIMITE_GIORNALIERO valido si usa; assente o vuoto -> 1000; non valido -> 1000 con avviso."""
    # preparazione: variabile tolta oppure impostata al valore del caso
    if valore is None:
        monkeypatch.delenv("METEO_LIMITE_GIORNALIERO", raising=False)
    else:
        monkeypatch.setenv("METEO_LIMITE_GIORNALIERO", valore)
    assert limite_giornaliero() == atteso
    # l'avviso nomina la variabile solo quando il valore non e' valido
    assert ("METEO_LIMITE_GIORNALIERO" in capsys.readouterr().err) is avviso


# il file del contatore: da METEO_CONTATORE oppure quello predefinito in dati/
def test_percorso_da_variabile_e_predefinito(monkeypatch, tmp_path):
    """METEO_CONTATORE sceglie il file; senza variabile si usa dati/meteo_richieste.sqlite."""
    monkeypatch.setenv("METEO_CONTATORE", str(tmp_path / "c.sqlite"))
    assert percorso_contatore() == tmp_path / "c.sqlite"
    monkeypatch.delenv("METEO_CONTATORE")
    assert percorso_contatore().as_posix().endswith("dati/meteo_richieste.sqlite")


# se il contatore non si puo' usare, la richiesta si blocca: il limite non si aggira
def test_contatore_non_accessibile(tmp_path):
    """Un file al posto della cartella rende il contatore non accessibile: errore, non un via libera."""
    # preparazione: un file normale usato come se fosse la cartella del contatore
    file = tmp_path / "un_file"
    file.write_text("non sono una cartella")
    contatore = Contatore(file / "contatore.sqlite", 10, lambda: ISTANTE)
    with pytest.raises(errori.ContatoreNonAccessibile):
        contatore.registra()


# al primo uso il contatore crea le cartelle che mancano (es. dati/)
def test_crea_la_cartella(tmp_path):
    """Le cartelle mancanti del percorso si creano al primo registra()."""
    percorso = tmp_path / "nuova" / "sotto" / "contatore.sqlite"
    Contatore(percorso, 10, lambda: ISTANTE).registra()
    assert percorso.exists()
