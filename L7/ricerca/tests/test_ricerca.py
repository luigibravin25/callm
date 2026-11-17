# test della ricerca top-k in Qdrant in memoria: fonte dei risultati, filtro per capitolo, massimo, errori
import logging

import pytest
from qdrant_client import QdrantClient

from app.chunking import chunk_delle_ricette
from app.corpus import Ricetta
from app.errori import ErroreRicerca
from app.indice import Indice
from tests.finti import EmbedderFinto

# in memoria gli indici sul payload non hanno effetto (Qdrant lo avvisa): l'indice si verifica sul server
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")


# testo di prova diverso per ogni ricetta, lungo circa `caratteri`
def parole_di(numero: int, caratteri: int) -> str:
    return " ".join(f"parola{numero}x{i}" for i in range(caratteri // 12))


# dieci ricette di tre capitoli, ognuna in più chunk (30 chunk in tutto)
CAPITOLI_PROVA = ("BRODI, GELATINA E SUGHI", "MINESTRE IN BRODO", "PIATTI DI PESCE")
RICETTE = [Ricetta(n, f"Ricetta {n}", CAPITOLI_PROVA[n % 3], parole_di(n, 2500)) for n in range(1, 11)]


@pytest.fixture
def embedder():
    return EmbedderFinto()


@pytest.fixture
def indice(embedder):
    ix = Indice(QdrantClient(":memory:"), "ricettario", "bge", embedder)
    ix.indicizza(chunk_delle_ricette(RICETTE, "paragrafi", 1000, 150), chunking="paragrafi 1000/150")
    return ix


def test_risultati_con_fonte(indice):
    risultati = indice.cerca("brodo di carne", k=5)
    assert [r.posizione for r in risultati] == [1, 2, 3, 4, 5]
    for r in risultati:
        assert isinstance(r.score, float)
        assert r.titolo == f"Ricetta {r.numero}" and r.capitolo in CAPITOLI_PROVA
        assert 0 <= r.indice_chunk < r.totale_chunk and r.testo


def test_filtro_per_capitolo(indice):
    risultati = indice.cerca("brodo di carne", capitolo="MINESTRE IN BRODO", k=5)
    assert 0 < len(risultati) <= 5
    assert {r.capitolo for r in risultati} == {"MINESTRE IN BRODO"}


def test_capitolo_scritto_in_altro_modo(indice):
    attesi = indice.cerca("brodo di carne", capitolo="MINESTRE IN BRODO", k=5)
    assert indice.cerca("brodo di carne", capitolo="  minestre in brodo ", k=5) == attesi


def test_capitolo_sconosciuto(indice):
    with pytest.raises(ErroreRicerca, match="PASTICCERIA"):
        indice.cerca("torta", capitolo="DOLCI")


def test_k_oltre_il_massimo(indice, caplog):
    with caplog.at_level(logging.WARNING, logger="ricerca"):
        risultati = indice.cerca("brodo", k=50)
    assert len(risultati) == 20
    assert "20" in caplog.text


def test_k_minore_di_uno(indice):
    with pytest.raises(ErroreRicerca):
        indice.cerca("brodo", k=0)


def test_domanda_vuota(indice, embedder):
    chiamate_prima = len(embedder.chiamate)
    with pytest.raises(ErroreRicerca):
        indice.cerca("   ")
    assert len(embedder.chiamate) == chiamate_prima


def test_testo_della_domanda_all_embedder(indice, embedder):
    indice.cerca("quanta farina?")
    assert embedder.chiamate[-1] == ["quanta farina?"]


def test_collezione_assente():
    ix = Indice(QdrantClient(":memory:"), "ricettario", "bge", EmbedderFinto())
    with pytest.raises(ErroreRicerca, match="ingestion"):
        ix.cerca("brodo")


def test_modello_diverso_bloccato_in_ricerca(indice):
    altro = EmbedderFinto()
    ix = Indice(indice.client, "ricettario", "altro", altro)
    with pytest.raises(ErroreRicerca, match="altro"):
        ix.cerca("brodo")
    assert altro.chiamate == []


# --- esercizio 2, A: filtro solo_dosi ---
from qdrant_client.models import PointStruct

from app.indice import id_punto

ELENCO = ("Farina, grammi 200.", "Burro, grammi 50.")


# ricette dispari con elenco di ingredienti in testa (solo il primo chunk ha le dosi), pari senza
def ricette_con_dosi():
    ricette = []
    for n in range(1, 11):
        ingredienti = ELENCO if n % 2 else ()
        testo = ("\n".join(ELENCO) + "\n\n" if ingredienti else "") + parole_di(n, 2500)
        ricette.append(Ricetta(n, f"Ricetta {n}", CAPITOLI_PROVA[n % 3], testo, ingredienti))
    return ricette


@pytest.fixture
def indice_dosi():
    ix = Indice(QdrantClient(":memory:"), "ricettario", "bge", EmbedderFinto())
    ix.indicizza(chunk_delle_ricette(ricette_con_dosi(), "paragrafi", 1000, 150), chunking="paragrafi 1000/150")
    return ix


def test_payload_con_contiene_dosi(indice_dosi):
    punto = indice_dosi.client.retrieve("ricettario", [id_punto(1, 0)], with_payload=True)[0]
    assert punto.payload["contiene_dosi"] is True


def test_solo_dosi(indice_dosi):
    risultati = indice_dosi.cerca("farina e burro", k=5, solo_dosi=True)
    assert 0 < len(risultati) <= 5
    assert all(r.contiene_dosi for r in risultati)


def test_solo_dosi_e_capitolo(indice_dosi):
    risultati = indice_dosi.cerca("farina e burro", capitolo="MINESTRE IN BRODO", k=5, solo_dosi=True)
    assert risultati
    assert all(r.contiene_dosi and r.capitolo == "MINESTRE IN BRODO" for r in risultati)


def test_solo_dosi_capitolo_senza_dosi(indice_dosi):
    # nessun chunk con dosi in questo capitolo: lista vuota, nessun errore
    assert indice_dosi.cerca("farina", capitolo="SALSE", solo_dosi=True) == []


def test_solo_dosi_senza_campo(indice_dosi):
    # un punto scritto senza il campo (collezione non ancora aggiornata): errore che indica lo script
    vettore = indice_dosi.embedder.incorpora(["x"])[0]
    indice_dosi.client.upsert("ricettario", points=[PointStruct(id=id_punto(99, 0), vector=vettore, payload={
        "testo": "x", "numero": 99, "titolo": "X", "capitolo": "SALSE", "indice_chunk": 0, "totale_chunk": 1})])
    chiamate = len(indice_dosi.embedder.chiamate)
    with pytest.raises(ErroreRicerca, match="aggiorna_dosi.py"):
        indice_dosi.cerca("farina", solo_dosi=True)
    assert len(indice_dosi.embedder.chiamate) == chiamate
