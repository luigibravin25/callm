# test degli script ingestion.py e cerca.py senza servizi: Qdrant in memoria, embedder finto
import logging

import pytest
from qdrant_client import QdrantClient

import cerca
import ingestion
from app.config import carica_configurazione
from app.corpus import analizza
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
    argomenti = cerca.leggi_argomenti(["gnocchi", "--capitolo", "minestre asciutte e di magro", "-k", "3"], 5)
    assert (argomenti.domanda, argomenti.capitolo, argomenti.k) == ("gnocchi", "minestre asciutte e di magro", 3)
    assert cerca.leggi_argomenti(["gnocchi"], 5).k == 5


@pytest.mark.parametrize("principale", [ingestion.main, lambda: cerca.main(["brodo"])])
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
