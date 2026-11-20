# test degli script ingestion.py e cerca.py senza servizi: Qdrant in memoria, embedder finto
import logging

import pytest
from qdrant_client import QdrantClient

import calibra
import cerca
import confronta
import ingestion
import valuta
from app.config import carica_configurazione
from app.corpus import analizza
from app.errori import ErroreRicerca
from app.indice import Risultato
from tests.finti import EmbedderFinto
from tests.test_corpus import TESTO_PROVA

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")


@pytest.fixture
def conf(monkeypatch):
    for nome in ("CHUNK_STRATEGIA", "CHUNK_DIMENSIONE", "CHUNK_OVERLAP", "QDRANT_COLLEZIONE", "TOP_K"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    return carica_configurazione()


def test_esegui_su_corpus_finto(conf, monkeypatch, caplog):
    # il corpus vero vuole 790 ricette: qui le tre del testo di prova
    monkeypatch.setattr(ingestion, "carica_corpus", lambda percorso: analizza(TESTO_PROVA))
    with caplog.at_level(logging.INFO, logger="ricerca"):
        esito = ingestion.esegui(conf, QdrantClient(":memory:"), EmbedderFinto())
    assert esito.punti == esito.chunk == 3
    assert "ricette 3 · chunk 3 · punti scritti 3 · orfani cancellati 0 · punti nella collezione 3" in caplog.text
    assert "modello bge · chunking paragrafi 1000/150" in caplog.text


RISULTATO = Risultato(posizione=1, score=0.81234, numero=89, titolo="Gnocchi di patate",
                      capitolo="MINESTRE ASCIUTTE E DI MAGRO", indice_chunk=0, totale_chunk=3,
                      testo="Patate grosse e gialle, grammi 400.")


def test_formatta():
    assert cerca.formatta([RISULTATO]) == (
        "#1 · score 0.8123 · n. 89 «Gnocchi di patate» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 3\n"
        "Patate grosse e gialle, grammi 400.")


def test_formatta_vuoto():
    assert cerca.formatta([]) == "Nessun risultato."


def test_argomenti():
    argomenti = cerca.leggi_argomenti(["gnocchi", "--capitolo", "minestre asciutte e di magro", "-k", "3"])
    assert (argomenti.domanda, argomenti.capitolo, argomenti.k) == ("gnocchi", "minestre asciutte e di magro", 3)
    # senza -k il valore si decide dopo, con TOP_K della configurazione
    assert cerca.leggi_argomenti(["gnocchi"]).k is None
    assert valuta.leggi_argomenti([]).k is None


@pytest.mark.parametrize("principale", [lambda: cerca.main(["--help"]), lambda: valuta.main(["--help"]),
                                        lambda: confronta.main(["--help"]), lambda: calibra.main(["--help"])])
def test_help_senza_configurazione(monkeypatch, capsys, principale):
    # l'aiuto non richiede variabili d'ambiente
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    with pytest.raises(SystemExit) as uscita:
        principale()
    assert uscita.value.code == 0
    assert "usage" in capsys.readouterr().out


@pytest.mark.parametrize("principale", [ingestion.main, lambda: cerca.main(["brodo"]), lambda: valuta.main([])])
def test_main_errore_esce_con_1(monkeypatch, caplog, principale):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    with pytest.raises(SystemExit) as uscita:
        principale()
    assert uscita.value.code == 1
    assert "EMBEDDING_MODEL" in caplog.text


def test_qdrant_spento_messaggio_chiaro(monkeypatch, caplog):
    # il client di Qdrant non raggiunge il server: messaggio con l'indirizzo e il comando di avvio
    from qdrant_client.http.exceptions import ResponseHandlingException

    from app.avvio import esegui

    def principale():
        raise ResponseHandlingException(ConnectionError("rifiutata"))

    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6333")
    with pytest.raises(SystemExit) as uscita:
        esegui(principale)
    assert uscita.value.code == 1
    assert "QDRANT_URL=http://127.0.0.1:6333" in caplog.text and "docker compose up -d qdrant" in caplog.text


def test_log_senza_richieste_http():
    # le richieste HTTP verso LM Studio e Qdrant non riempiono il log degli script
    from app.avvio import configura_log

    configura_log()
    for nome in ("httpx", "httpx2"):
        # livello proprio del logger (quello ereditato dal root di pytest non conta)
        assert logging.getLogger(nome).level == logging.WARNING, nome


def test_modello_controllato_prima_del_corpus(conf, monkeypatch, caplog):
    # collezione costruita con "bge"; la configurazione indica un altro modello
    client = QdrantClient(":memory:")
    monkeypatch.setattr(ingestion, "carica_corpus", lambda percorso: analizza(TESTO_PROVA))
    ingestion.esegui(conf, client, EmbedderFinto())

    def corpus_vietato(percorso):
        raise AssertionError("il corpus non va letto se il modello è diverso")

    monkeypatch.setattr(ingestion, "carica_corpus", corpus_vietato)
    monkeypatch.setenv("EMBEDDING_MODEL", "altro")
    caplog.clear()
    with pytest.raises(ErroreRicerca):
        ingestion.esegui(carica_configurazione(), client, EmbedderFinto())
    assert "corpus letto" not in caplog.text


def test_formatta_con_dosi():
    from dataclasses import replace
    riga = cerca.formatta([replace(RISULTATO, contiene_dosi=True)]).splitlines()[0]
    assert riga.endswith("· chunk 1 di 3 · con dosi")


def test_argomenti_solo_dosi():
    assert cerca.leggi_argomenti(["gnocchi", "--solo-dosi"]).solo_dosi is True
    assert cerca.leggi_argomenti(["gnocchi"]).solo_dosi is False
    assert valuta.leggi_argomenti(["--solo-dosi"]).solo_dosi is True



# Verifica che il confronto senza LM_MODEL esca con 1 e un messaggio chiaro (prima di qualsiasi servizio).
def test_confronta_senza_lm_model(monkeypatch, caplog):
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    for nome in ("LM_MODEL", "RICERCA_MODALITA"):
        monkeypatch.delenv(nome, raising=False)
    with pytest.raises(SystemExit) as uscita:
        confronta.main([])
    assert uscita.value.code == 1
    assert "LM_MODEL" in caplog.text



# Verifica che il sorgente di confronta.py compili senza avvisi (sequenze di escape nel docstring).
def test_confronta_senza_avvisi_di_sintassi():
    import warnings
    from pathlib import Path
    sorgente = (Path(__file__).resolve().parents[1] / "confronta.py").read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(sorgente, "confronta.py", "exec")
