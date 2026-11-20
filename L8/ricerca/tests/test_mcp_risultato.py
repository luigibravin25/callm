# test delle funzioni pure del server MCP: id citabile, troncamento, limite di top_k, formato del passaggio
import pytest

from app.errori import ErroreRicerca
from app.indice import Risultato
from mcp_ricerca.risultato import TESTO_MASSIMO, id_citabile, limita_top_k, passaggio, tronca


def test_id_citabile():
    # numero della ricetta e posizione del chunk contata da 1
    assert id_citabile(89, 0) == "R89-1"
    assert id_citabile(208, 0) == "R208-1"
    assert id_citabile(776, 5) == "R776-6"


def test_tronca_breve():
    assert tronca("abc") == ("abc", False)


def test_tronca_a_fine_parola():
    testo = " ".join(f"parola{i}" for i in range(200))  # ~1500 caratteri
    troncato, tagliato = tronca(testo)
    assert tagliato is True
    assert len(troncato) <= TESTO_MASSIMO == 800
    # l'ultima parola tenuta è intera
    assert troncato.split()[-1] in testo.split()


def test_tronca_senza_spazi():
    # una parola più lunga del limite: taglio secco, nessun ciclo infinito
    assert tronca("a" * 1000) == ("a" * 800, True)


def test_limita_top_k():
    assert limita_top_k(5) == (5, None)
    assert limita_top_k(10) == (10, None)
    assert limita_top_k(25) == (10, "top_k 25 ridotto a 10")
    with pytest.raises(ErroreRicerca, match="1-10"):
        limita_top_k(0)


def test_passaggio_da_risultato():
    r = Risultato(posizione=1, score=0.61357, numero=208, titolo="Pollo alla cacciatora", capitolo="FRITTI",
                  indice_chunk=0, totale_chunk=1, testo="Prendete un pollo.")
    assert passaggio(r, "affidabile") == {"id": "R208-1", "ricetta": 208, "titolo": "Pollo alla cacciatora",
                                          "capitolo": "FRITTI", "posizione": "chunk 1 di 1", "score": 0.6136,
                                          "testo": "Prendete un pollo.", "troncato": False,
                                          "affidabilita": "affidabile"}



# Verifica il testo della lista vuota dichiarata, con e senza motivo (esercizio 4).
def test_nota_lista_vuota():
    from mcp_ricerca.risultato import nota_lista_vuota
    assert nota_lista_vuota(None) == "nessun passaggio rimasto: lista vuota"
    assert nota_lista_vuota("esclusi tutti dal reranking") == \
        "nessun passaggio rimasto: lista vuota (esclusi tutti dal reranking)"
