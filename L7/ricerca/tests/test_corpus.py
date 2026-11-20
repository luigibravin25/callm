# test della lettura del corpus: testo di prova con tutti i casi della specifica (§7) e file vero
import pytest

from app.config import CARTELLA_L7
from app.corpus import CAPITOLI, analizza, carica_corpus
from app.errori import ErroreRicerca

# testo di prova: intestazione Gutenberg, capitolo con introduzione, ingredienti con continuazione,
# illustrazione su due righe, richiamo di nota, corsivo, riga che inizia con un numero, titolo interno,
# intestazione di sola introduzione (MINESTRE), sottocapitolo, versi, appendice
TESTO_PROVA = """The Project Gutenberg eBook of Prova

1. Riga numerata prima dell'inizio

*** START OF THE PROJECT GUTENBERG EBOOK PROVA ***

RICETTE


BRODI, GELATINA E SUGHI

Introduzione del capitolo che si scarta
sempre.

1. Brodo

Il brodo si fa con la carne
di manzo e con poco sale.

  Farina, grammi 200
    e un po' di più.
  Burro, grammi 50.

   [Illustrazione: Disco — NdT: Ø 64 mm
   nell'illustrazione originale]

Certi cuochi strapazzano il frasario dei nostri poco benevoli
vicini[2] con nomi _strani_.

2. Sugo

Mettete la carne al fuoco.
137. Mettete il composto al fuoco e
rimestate sempre.

RICETTA A

Burro e farina in parti uguali.


MINESTRE

Introduzione di minestre da scartare.

MINESTRE IN BRODO

3. _Cappelletti_

Si chiamano così per la forma.

      Primo verso della poesia,
      Secondo verso della poesia.

Ultima riga dei cappelletti.

APPENDICE

4. Testo dell'appendice.

*** END OF THE PROJECT GUTENBERG EBOOK PROVA ***
""".replace("\n", "\r\n")  # a capo CRLF come nel file vero

# file vero: i test che lo usano si saltano se manca
FILE_VERO = CARTELLA_L7 / "Ricettario" / "Ricettario.txt"
serve_il_file = pytest.mark.skipif(not FILE_VERO.is_file(), reason="Ricettario/Ricettario.txt assente")


@pytest.fixture(scope="module")
def prova():
    # ricette del testo di prova per numero
    return {r.numero: r for r in analizza(TESTO_PROVA)}


def test_tre_ricette_con_numero_titolo_capitolo(prova):
    assert [(r.numero, r.titolo, r.capitolo) for r in prova.values()] == [
        (1, "Brodo", "BRODI, GELATINA E SUGHI"),
        (2, "Sugo", "BRODI, GELATINA E SUGHI"),
        (3, "Cappelletti", "MINESTRE IN BRODO"),
    ]


def test_introduzioni_scartate(prova):
    tutto = " ".join(r.testo for r in prova.values())
    assert "Introduzione" not in tutto
    assert "MINESTRE" not in tutto
    # la ricetta 2 si chiude prima dell'intestazione MINESTRE
    assert prova[2].testo.endswith("Burro e farina in parti uguali.")


def test_prosa_unita_e_ingredienti_su_righe_proprie(prova):
    assert prova[1].testo == (
        "Il brodo si fa con la carne di manzo e con poco sale.\n\n"
        "Farina, grammi 200 e un po' di più.\n"
        "Burro, grammi 50.\n\n"
        "Certi cuochi strapazzano il frasario dei nostri poco benevoli vicini con nomi strani."
    )


def test_illustrazioni_richiami_e_corsivo_tolti(prova):
    testo = prova[1].testo
    assert "[" not in testo and "]" not in testo
    assert "Illustrazione" not in testo and "NdT" not in testo
    assert "_" not in testo
    assert "vicini con" in testo


def test_riga_che_inizia_con_un_numero_resta_testo(prova):
    assert "fuoco. 137. Mettete il composto al fuoco e rimestate sempre." in prova[2].testo


def test_titolo_interno_resta_nel_testo(prova):
    assert "\n\nRICETTA A\n\n" in prova[2].testo


def test_versi_su_righe_proprie(prova):
    assert prova[3].testo == ("Si chiamano così per la forma.\n\n"
                              "Primo verso della poesia,\nSecondo verso della poesia.\n\n"
                              "Ultima riga dei cappelletti.")


def test_appendice_esclusa(prova):
    assert 4 not in prova
    assert "appendice" not in " ".join(r.testo for r in prova.values())


def test_ricetta_vuota_errore():
    testo = "*** START OF X\nBRODI, GELATINA E SUGHI\n1. Vuota\n\n2. Piena\ntesto\n*** END OF X\n"
    with pytest.raises(ErroreRicerca, match="1"):
        analizza(testo)


def test_file_mancante(tmp_path):
    percorso = tmp_path / "manca.txt"
    with pytest.raises(ErroreRicerca) as errore:
        carica_corpus(percorso)
    assert str(percorso) in str(errore.value) and "59047" in str(errore.value)


def test_file_incompleto(tmp_path):
    # un file leggibile ma con 3 ricette non passa il controllo delle 790
    percorso = tmp_path / "corto.txt"
    percorso.write_text(TESTO_PROVA, encoding="utf-8")
    with pytest.raises(ErroreRicerca, match="790"):
        carica_corpus(percorso)


# --- file vero ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ricette():
    return {r.numero: r for r in carica_corpus(FILE_VERO)}


@serve_il_file
def test_790_ricette_senza_buchi(ricette):
    assert list(ricette) == list(range(1, 791))


@serve_il_file
def test_23_capitoli_in_ordine(ricette):
    assert len(CAPITOLI) == 23
    assert tuple(dict.fromkeys(r.capitolo for r in ricette.values())) == CAPITOLI


@serve_il_file
def test_capitoli_di_7_e_455(ricette):
    assert ricette[7].capitolo == "MINESTRE IN BRODO"
    assert ricette[455].capitolo == "PIATTI DI PESCE"


@serve_il_file
def test_ricetta_6_senza_introduzione_di_minestre(ricette):
    assert ricette[6].testo.endswith("confacenti al bisogno.")


@serve_il_file
def test_nessuna_illustrazione(ricette):
    assert not any("[Illustrazione" in r.testo or "NdT" in r.testo for r in ricette.values())


@serve_il_file
def test_indizi_nelle_ricette_attese(ricette):
    for numero, indizio in ((89, "grammi 400"), (89, "si liquefecero"), (7, "mangiatore discreto"),
                            (208, "vino rosso"), (455, "brodetto")):
        assert indizio in ricette[numero].testo, (numero, indizio)


@serve_il_file
def test_288_breve_776_lunga(ricette):
    assert len(ricette[288].testo) < 1000
    assert max(ricette.values(), key=lambda r: len(r.testo)).numero == 776
    assert len(ricette[776].testo) > 5000


# --- esercizio 2, A: righe di ingrediente (rientrate di 2 spazi) di ogni ricetta ---

def test_ingredienti_della_ricetta_con_elenco(prova):
    # la continuazione a 4 spazi è unita alla sua riga, come nel testo
    assert prova[1].ingredienti == ("Farina, grammi 200 e un po' di più.", "Burro, grammi 50.")


def test_nessun_ingrediente_senza_elenco(prova):
    # la ricetta 3 ha versi a 6 spazi: non sono ingredienti
    assert prova[2].ingredienti == ()
    assert prova[3].ingredienti == ()


@serve_il_file
def test_347_ricette_con_elenco(ricette):
    assert sum(1 for r in ricette.values() if r.ingredienti) == 347
    assert ricette[89].ingredienti and ricette[7].ingredienti
    assert not ricette[208].ingredienti and not ricette[455].ingredienti


@serve_il_file
def test_ingredienti_sono_righe_del_testo(ricette):
    for r in ricette.values():
        righe = r.testo.split("\n")
        assert all(i in righe for i in r.ingredienti), r.numero
