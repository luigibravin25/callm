"""Test delle categorie di errore del meteo e del contatore del limite giornaliero.

Nessuna rete: il contatore e' un file SQLite in una cartella temporanea e l'istante corrente e'
fisso, cosi' i giorni sono controllati.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_meteo import errori
from mcp_meteo.contatore import (LIMITE_PREDEFINITO, Contatore, limite_giornaliero,
                                 percorso_contatore)

ISTANTE = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)  # giovedi' 5 novembre, 13:00 a Roma


def _contatore(tmp_path: Path, limite: int, istante: datetime = ISTANTE) -> Contatore:
    """Contatore su un file temporaneo con un orologio fisso."""
    return Contatore(tmp_path / "contatore.sqlite", limite, lambda: istante)


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


def test_registra_conta(tmp_path):
    """registra() restituisce il conteggio di oggi, che cresce di uno a ogni richiesta."""
    contatore = _contatore(tmp_path, 3)
    assert [contatore.registra() for _ in range(3)] == [1, 2, 3]
    assert contatore.conteggio_di_oggi() == 3


def test_limite_raggiunto_senza_incremento(tmp_path):
    """Al limite: LimiteRaggiunto con "riprova domani" e il conteggio non cresce."""
    contatore = _contatore(tmp_path, 2)
    contatore.registra()
    contatore.registra()
    with pytest.raises(errori.LimiteRaggiunto) as info:
        contatore.registra()
    assert "2 richieste" in str(info.value) and "riprova domani" in str(info.value)
    assert contatore.conteggio_di_oggi() == 2  # la richiesta bloccata non conta


def test_sopravvive_a_un_nuovo_contatore(tmp_path):
    """Un nuovo Contatore sullo stesso file prosegue il conteggio (server riavviato)."""
    # il server meteo riparte a ogni chiamata: il conteggio deve restare nel file
    _contatore(tmp_path, 10).registra()
    nuovo = _contatore(tmp_path, 10)
    assert nuovo.registra() == 2


def test_riparte_il_giorno_dopo(tmp_path):
    """Dopo la mezzanotte di Roma il conteggio di oggi riparte da zero."""
    _contatore(tmp_path, 10).registra()
    # 23:30 UTC del 5 novembre e' gia' il 6 novembre a Roma
    domani = _contatore(tmp_path, 10, datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc))
    assert domani.conteggio_di_oggi() == 0


@pytest.mark.parametrize("valore, atteso, avviso", [
    ("50", 50, False), (None, LIMITE_PREDEFINITO, False), ("", LIMITE_PREDEFINITO, False),
    ("0", LIMITE_PREDEFINITO, True), ("-3", LIMITE_PREDEFINITO, True),
    ("abc", LIMITE_PREDEFINITO, True)])
def test_limite_da_variabile(monkeypatch, capsys, valore, atteso, avviso):
    """METEO_LIMITE_GIORNALIERO valido si usa; assente o vuoto -> 1000; non valido -> 1000 con avviso."""
    if valore is None:
        monkeypatch.delenv("METEO_LIMITE_GIORNALIERO", raising=False)
    else:
        monkeypatch.setenv("METEO_LIMITE_GIORNALIERO", valore)
    assert limite_giornaliero() == atteso
    assert ("METEO_LIMITE_GIORNALIERO" in capsys.readouterr().err) is avviso


def test_percorso_da_variabile_e_predefinito(monkeypatch, tmp_path):
    """METEO_CONTATORE sceglie il file; senza variabile si usa dati/meteo_richieste.sqlite."""
    monkeypatch.setenv("METEO_CONTATORE", str(tmp_path / "c.sqlite"))
    assert percorso_contatore() == tmp_path / "c.sqlite"
    monkeypatch.delenv("METEO_CONTATORE")
    assert percorso_contatore().as_posix().endswith("dati/meteo_richieste.sqlite")


def test_contatore_non_accessibile(tmp_path):
    """Un file al posto della cartella rende il contatore non accessibile: errore, non un via libera."""
    file = tmp_path / "un_file"
    file.write_text("non sono una cartella")
    contatore = Contatore(file / "contatore.sqlite", 10, lambda: ISTANTE)
    with pytest.raises(errori.ContatoreNonAccessibile):
        contatore.registra()


def test_crea_la_cartella(tmp_path):
    """Le cartelle mancanti del percorso si creano al primo registra()."""
    percorso = tmp_path / "nuova" / "sotto" / "contatore.sqlite"
    Contatore(percorso, 10, lambda: ISTANTE).registra()
    assert percorso.exists()
