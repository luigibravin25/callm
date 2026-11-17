# test del chunking: testo breve e lungo per le due strategie, overlap, parametri, chunk delle ricette
import pytest

from app.chunking import chunk_delle_ricette, dividi
from app.config import CARTELLA_L7
from app.corpus import Ricetta, carica_corpus
from app.errori import ErroreRicerca

STRATEGIE = ("paragrafi", "caratteri")
FILE_VERO = CARTELLA_L7 / "Ricettario" / "Ricettario.txt"
serve_il_file = pytest.mark.skipif(not FILE_VERO.is_file(), reason="Ricettario/Ricettario.txt assente")

# testo breve (76 caratteri, come la ricetta 288)
BREVE = "Coniglio in umido con lardone, aglio, prezzemolo e sugo di pomodoro. Buono."
# frase di prova di ~100 caratteri, numerata: il testo non si ripete, così le sovrapposizioni
# trovate dai test sono solo quelle vere
def frasi(da: int, quante: int) -> str:
    return " ".join(f"Frase {n}: mettete la carne nella cazzaruola con burro, sale e pepe; poi il brodo."
                    for n in range(da, da + quante))


# testo lungo (~6000 caratteri): paragrafi normali, un elenco di ingredienti e un paragrafo da ~1500
def lungo() -> str:
    paragrafi = [frasi(10 * p, 6) for p in range(7)]
    paragrafi.insert(2, "Farina, grammi 200.\nBurro, grammi 50.\nUova, N. 2.")
    paragrafi.insert(4, frasi(100, 15))
    return "\n\n".join(paragrafi)


# sovrapposizione tra due chunk consecutivi: il più lungo prefisso del secondo che è suffisso del primo
def sovrapposizione(primo: str, secondo: str) -> str:
    for lunghezza in range(min(len(primo), len(secondo)), 0, -1):
        if primo.endswith(secondo[:lunghezza]):
            return secondo[:lunghezza]
    return ""


# testo ricomposto dai chunk senza le sovrapposizioni, con gli spazi normalizzati
def ricomponi(chunk: list[str]) -> str:
    parti = [chunk[0]] + [b[len(sovrapposizione(a, b)):] for a, b in zip(chunk, chunk[1:])]
    return " ".join(" ".join(parti).split())


def normalizza(testo: str) -> str:
    return " ".join(testo.split())


@pytest.mark.parametrize("strategia", STRATEGIE)
def test_testo_breve_un_solo_chunk(strategia):
    assert dividi(BREVE, strategia, 1000, 150) == [BREVE]


@pytest.mark.parametrize("strategia", STRATEGIE)
def test_testo_lungo(strategia):
    testo = lungo()
    chunk = dividi(testo, strategia, 1000, 150)
    assert len(chunk) > 1
    assert all(0 < len(c) <= 1000 for c in chunk)
    for a, b in zip(chunk, chunk[1:]):
        s = sovrapposizione(a, b)
        # overlap presente, entro il massimo, tagliato a inizio parola
        assert 0 < len(s) <= 150
        assert a[len(a) - len(s) - 1].isspace()
    # nessun pezzo perso né ripetuto
    assert ricomponi(chunk) == normalizza(testo)


@pytest.mark.parametrize("strategia", STRATEGIE)
def test_overlap_zero(strategia):
    testo = lungo()
    chunk = dividi(testo, strategia, 1000, 0)
    assert " ".join(normalizza(c) for c in chunk) == normalizza(testo)


def test_paragrafi_tiene_intero_l_elenco_di_ingredienti():
    chunk = dividi(lungo(), "paragrafi", 1000, 150)
    assert any("Farina, grammi 200.\nBurro, grammi 50.\nUova, N. 2." in c for c in chunk)


@pytest.mark.parametrize("strategia, dimensione, overlap", [
    ("frasi", 1000, 150), ("paragrafi", 0, 0), ("paragrafi", 1000, -1), ("caratteri", 100, 100),
])
def test_parametri_non_validi(strategia, dimensione, overlap):
    with pytest.raises(ErroreRicerca):
        dividi(BREVE, strategia, dimensione, overlap)


def test_chunk_delle_ricette():
    ricette = [Ricetta(1, "Breve", "SALSE", BREVE), Ricetta(2, "Lunga", "UMIDI", lungo())]
    chunk = chunk_delle_ricette(ricette, "paragrafi", 1000, 150)
    breve = [c for c in chunk if c.numero == 1]
    lunga = [c for c in chunk if c.numero == 2]
    assert [(c.indice_chunk, c.totale_chunk, c.titolo, c.capitolo, c.testo) for c in breve] == [
        (0, 1, "Breve", "SALSE", BREVE)]
    assert [c.indice_chunk for c in lunga] == list(range(len(lunga)))
    assert {c.totale_chunk for c in lunga} == {len(lunga)}
    assert {(c.titolo, c.capitolo) for c in lunga} == {("Lunga", "UMIDI")}
    # ordine: prima la ricetta 1, poi la 2
    assert chunk == breve + lunga


@serve_il_file
@pytest.mark.parametrize("strategia", STRATEGIE)
def test_288_e_776(strategia):
    ricette = {r.numero: r for r in carica_corpus(FILE_VERO)}
    assert dividi(ricette[288].testo, strategia, 1000, 150) == [ricette[288].testo]
    chunk = dividi(ricette[776].testo, strategia, 1000, 150)
    assert len(chunk) > 1
    assert all(len(c) <= 1000 for c in chunk)
    assert ricomponi(chunk) == normalizza(ricette[776].testo)


# --- esercizio 2, A: contiene_dosi ---
from app.chunking import ha_dosi

INGREDIENTI = ("Farina, grammi 200.", "Burro, grammi 50.")


def test_ha_dosi():
    assert ha_dosi("Impastate.\n\nFarina, grammi 200.\nBurro, grammi 50.", INGREDIENTI)
    # riga spezzata o unita a prosa con uno spazio: non conta
    assert not ha_dosi("Impastate. Farina, grammi 200.\nBurro, grammi", INGREDIENTI)
    assert not ha_dosi("Farina, grammi 200.", ())


def test_versi_non_sono_dosi():
    # chunk della ricetta con elenco che contiene solo versi ed etichette su righe proprie: niente dosi
    versi = "Si chiamano così.\n\nPrimo verso,\nSecondo verso.\n\nPrima:"
    assert not ha_dosi(versi, INGREDIENTI)
    # stesso chunk con una riga di ingrediente intera: dosi
    assert ha_dosi(versi + "\nFarina, grammi 200.", INGREDIENTI)


def test_chunk_delle_ricette_con_dosi():
    testo = "Farina, grammi 200.\nBurro, grammi 50.\n\n" + frasi(1, 30)
    chunk = chunk_delle_ricette([Ricetta(1, "Pasta", "PASTICCERIA", testo, INGREDIENTI)], "paragrafi", 1000, 150)
    assert len(chunk) > 1
    assert chunk[0].contiene_dosi is True
    assert chunk[-1].contiene_dosi is False


@serve_il_file
def test_417_chunk_con_dosi():
    ricette = carica_corpus(FILE_VERO)
    chunk = chunk_delle_ricette(ricette, "paragrafi", 1000, 150)
    assert sum(c.contiene_dosi for c in chunk) == 417
    # ogni ricetta con elenco ha almeno un chunk con il campo vero
    con_dosi = {c.numero for c in chunk if c.contiene_dosi}
    assert {r.numero for r in ricette if r.ingredienti} <= con_dosi


# --- esercizio 2, B: titolo e capitolo davanti al chunk nel testo indicizzato ---
# alias: un nome che inizia con "test" verrebbe raccolto da pytest come test
from app.chunking import Chunk, testo_indicizzato as forma_indicizzata


def test_testo_indicizzato():
    c = Chunk(208, "Pollo alla cacciatora", "UMIDI", 0, 2, "Prendete un pollo giovine.")
    assert forma_indicizzata(c) == "Ricetta: Pollo alla cacciatora\nCapitolo: Umidi\n\nPrendete un pollo giovine."
    c = Chunk(1, "Brodo", "BRODI, GELATINA E SUGHI", 0, 1, "Il brodo.")
    assert forma_indicizzata(c).splitlines()[1] == "Capitolo: Brodi, gelatina e sughi"
