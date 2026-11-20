# test di aggiorna_dosi: il campo contiene_dosi arriva ai punti esistenti senza ricalcolare gli embedding
import logging

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

import aggiorna_dosi
from app.chunking import chunk_delle_ricette
from app.config import carica_configurazione
from app.corpus import Ricetta
from app.errori import ErroreRicerca
from app.indice import Indice, id_punto
from tests.finti import EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")

ELENCO = ("Farina, grammi 200.", "Burro, grammi 50.")


# ricette dispari con elenco in testa, pari senza; testi lunghi (più chunk)
def ricette():
    lista = []
    for n in range(1, 7):
        ingredienti = ELENCO if n % 2 else ()
        corpo = " ".join(f"parola{n}x{i}" for i in range(200))
        testo = ("\n".join(ELENCO) + "\n\n" if ingredienti else "") + corpo
        lista.append(Ricetta(n, f"Ricetta {n}", "SALSE", testo, ingredienti))
    return lista


@pytest.fixture
def scritta():
    # collezione scritta come nell'esercizio 1: poi il campo si toglie da tutti i punti
    embedder = EmbedderFinto()
    client = QdrantClient(":memory:")
    chunk = chunk_delle_ricette(ricette(), "paragrafi", 1000, 150)
    Indice(client, "ricettario", "bge", embedder).indicizza(chunk, chunking="paragrafi 1000/150")
    client.delete_payload("ricettario", keys=["contiene_dosi"],
                          points=[id_punto(c.numero, c.indice_chunk) for c in chunk])
    return client, embedder, chunk


def ingredienti():
    return {r.numero: r.ingredienti for r in ricette()}


def campo(client, c):
    return client.retrieve("ricettario", [id_punto(c.numero, c.indice_chunk)], with_payload=True)[0].payload.get(
        "contiene_dosi")


def test_tutti_i_punti_ricevono_il_campo(scritta):
    client, _, chunk = scritta
    esito = Indice(client, "ricettario", "bge", None).aggiorna_dosi(ingredienti())
    assert esito.punti == len(chunk)
    assert esito.con_dosi == sum(c.contiene_dosi for c in chunk) > 0
    assert all(campo(client, c) == c.contiene_dosi for c in chunk)


def test_nessun_embedding(scritta):
    client, embedder, chunk = scritta
    chiamate = len(embedder.chiamate)
    punto = id_punto(chunk[0].numero, 0)
    prima = client.retrieve("ricettario", [punto], with_vectors=True)[0].vector
    Indice(client, "ricettario", "bge", None).aggiorna_dosi(ingredienti())
    assert len(embedder.chiamate) == chiamate
    assert client.retrieve("ricettario", [punto], with_vectors=True)[0].vector == prima


def test_ripetuto_stesso_risultato(scritta):
    client, _, chunk = scritta
    indice = Indice(client, "ricettario", "bge", None)
    primo = indice.aggiorna_dosi(ingredienti())
    assert indice.aggiorna_dosi(ingredienti()) == primo
    assert all(campo(client, c) == c.contiene_dosi for c in chunk)


def test_numero_sconosciuto(scritta):
    client, embedder, chunk = scritta
    vettore = embedder.incorpora(["x"])[0]
    client.upsert("ricettario", points=[PointStruct(id=id_punto(999, 0), vector=vettore, payload={
        "testo": "x", "numero": 999, "titolo": "X", "capitolo": "SALSE", "indice_chunk": 0, "totale_chunk": 1})])
    with pytest.raises(ErroreRicerca, match="999"):
        Indice(client, "ricettario", "bge", None).aggiorna_dosi(ingredienti())
    # nessuna scrittura
    assert all(campo(client, c) is None for c in chunk)


def test_collezione_assente():
    with pytest.raises(ErroreRicerca, match="ingestion"):
        Indice(QdrantClient(":memory:"), "ricettario", "bge", None).aggiorna_dosi(ingredienti())


def test_log_dello_script(scritta, monkeypatch, caplog):
    client, _, chunk = scritta
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    monkeypatch.setattr(aggiorna_dosi, "carica_corpus", lambda percorso: ricette())
    with caplog.at_level(logging.INFO, logger="ricerca"):
        aggiorna_dosi.esegui(carica_configurazione(), client)
    con = sum(c.contiene_dosi for c in chunk)
    assert (f"punti aggiornati {len(chunk)} · con dosi {con} · senza dosi {len(chunk) - con} · "
            "embedding ricalcolati 0") in caplog.text


def test_collezione_assente_prima_del_corpus(monkeypatch):
    # senza collezione l'errore dice di fare l'ingestion, senza leggere il corpus (spec §5.3, passo 1)
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")

    def corpus_vietato(percorso):
        raise AssertionError("il corpus non va letto se la collezione non esiste")

    monkeypatch.setattr(aggiorna_dosi, "carica_corpus", corpus_vietato)
    with pytest.raises(ErroreRicerca, match="ingestion"):
        aggiorna_dosi.esegui(carica_configurazione(), QdrantClient(":memory:"))
