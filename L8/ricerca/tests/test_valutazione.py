# test della valutazione: posizione e score della fonte, indizio nel chunk, tabella Markdown riproducibile
from pathlib import Path

from app.indice import Risultato
from app.valutazione import Domanda, leggi_domande, tabella_markdown, valuta

DOMANDE_VERE = Path(__file__).resolve().parents[1] / "valutazione" / "domande.toml"
INTESTAZIONE = {"modello": "bge", "collezione": "ricettario", "punti": "1234", "chunking": "paragrafi 1000/150",
                "k": "5"}


# risultato finto: posizione, ricetta, score e testo
def ris(posizione: int, numero: int, score: float, testo: str = "testo") -> Risultato:
    return Risultato(posizione=posizione, score=score, numero=numero, titolo=f"Ricetta {numero}",
                     capitolo="TRAMESSI", indice_chunk=0, totale_chunk=1, testo=testo)


# funzione di ricerca finta: stessi risultati per ogni domanda
def cerca_con(risultati):
    return lambda domanda: risultati


def test_leggi_domande():
    # le 6 domande della lezione 7, invariate, in testa al file
    domande = leggi_domande(DOMANDE_VERE)[:6]
    assert [d.fonti for d in domande] == [(89,), (7,), (208,), (89,), (455,), ()]
    assert [d.indizi for d in domande] == [("grammi 400",), ("mangiatore discreto",), ("vino rosso",),
                                           ("si liquefecero",), ("brodetto",), ()]


def test_fonte_al_secondo_posto():
    domanda = Domanda("gnocchi?", (89,), ("grammi 400",))
    riga = valuta([domanda], cerca_con([ris(1, 7, 0.9), ris(2, 89, 0.8, "patate, grammi 400.")]))[0]
    assert (riga.posizione, riga.score, riga.contiene) == (2, 0.8, True)
    assert riga.primo.numero == 7


def test_piu_chunk_della_fonte_conta_il_primo():
    domanda = Domanda("gnocchi?", (89,), ("grammi 400",))
    risultati = [ris(1, 7, 0.9), ris(2, 89, 0.8, "senza indizio"), ris(3, 5, 0.7), ris(4, 89, 0.6, "grammi 400")]
    riga = valuta([domanda], cerca_con(risultati))[0]
    assert (riga.posizione, riga.score, riga.contiene) == (2, 0.8, False)


def test_indizio_con_le_stesse_maiuscole():
    riga = valuta([Domanda("vino?", (208,), ("vino rosso",))], cerca_con([ris(1, 208, 0.9, "Vino Rosso")]))[0]
    assert riga.contiene is False


def test_fonte_assente():
    righe = valuta([Domanda("cacciucco?", (455,), ("brodetto",))], cerca_con([ris(1, 7, 0.9)]))
    assert (righe[0].posizione, righe[0].score, righe[0].contiene) == (None, None, None)
    riga_tabella = tabella_markdown(righe, INTESTAZIONE).splitlines()[-1]
    assert "| assente |" in riga_tabella and "| — |" in riga_tabella


def test_domanda_senza_fonte():
    righe = valuta([Domanda("tiramisù?", (), ())], cerca_con([ris(1, 7, 0.61234), ris(2, 8, 0.5)]))
    assert righe[0].score_risultati == [0.61234, 0.5]
    assert "0.6123, 0.5000" in tabella_markdown(righe, INTESTAZIONE)


def test_tabella():
    righe = valuta([Domanda("gnocchi?", (89,), ("grammi 400",))], cerca_con([ris(1, 89, 0.81234, "grammi 400")]))
    tabella = tabella_markdown(righe, INTESTAZIONE)
    assert tabella.startswith("- modello: bge\n- collezione: ricettario\n- punti: 1234\n"
                              "- chunking: paragrafi 1000/150\n- k: 5\n\n")
    assert tabella.splitlines()[-1] == "| gnocchi? | 89 | 1 | 0.8123 | sì | n. 89 «Ricetta 89» 0.8123 |"


def test_tabella_riproducibile():
    risultati = [ris(1, 89, 0.81234, "grammi 400"), ris(2, 7, 0.5)]
    domande = [Domanda("gnocchi?", (89,), ("grammi 400",)), Domanda("tiramisù?", (), ())]
    prima = tabella_markdown(valuta(domande, cerca_con(risultati)), INTESTAZIONE)
    assert tabella_markdown(valuta(domande, cerca_con(risultati)), INTESTAZIONE) == prima


# --- esercizio 2, minori 1 e 2: intestazione dalla collezione, domande controllate ---
import pytest

from app.errori import ErroreRicerca
from app.valutazione import intestazione_valutazione


def test_intestazione_dalla_collezione():
    completo = {"modello_embedding": "bge", "dimensione": 1024, "chunking": "paragrafi 1000/150",
                "testo_indicizzato": "testo"}
    assert intestazione_valutazione(completo, "ricettario", 1326, 5, solo_dosi=False) == {
        "modello": "bge", "collezione": "ricettario", "punti": "1326", "chunking": "paragrafi 1000/150",
        "testo indicizzato": "testo", "k": "5", "filtro": "nessuno"}
    # collezione dell'esercizio 1: solo modello e dimensione
    vecchia = intestazione_valutazione({"modello_embedding": "bge", "dimensione": 1024}, "ricettario", 1326, 5,
                                       solo_dosi=True)
    assert (vecchia["chunking"], vecchia["testo indicizzato"]) == ("non registrato", "non registrato")
    assert vecchia["filtro"] == "solo chunk con dosi"


VALIDA = '[[domanda]]\ntesto = "uno?"\nfonte = 1\nindizio = "a"\n\n'


@pytest.mark.parametrize("seconda", [
    '[[domanda]]\nfonte = 2\nindizio = "b"\n',            # testo mancante
    '[[domanda]]\ntesto = "  "\n',                         # testo vuoto
    '[[domanda]]\ntesto = "due?"\nfonte = 2\n',            # fonte senza indizio
    '[[domanda]]\ntesto = "due?"\nindizio = "b"\n',        # indizio senza fonte
    '[[domanda]]\ntesto = "due?"\nfonte = "89"\nindizio = "b"\n',  # fonte non intera
])
def test_domande_non_valide(tmp_path, seconda):
    percorso = tmp_path / "domande.toml"
    percorso.write_text(VALIDA + seconda, encoding="utf-8")
    with pytest.raises(ErroreRicerca, match="domanda 2"):
        leggi_domande(percorso)


def test_file_senza_domande(tmp_path):
    percorso = tmp_path / "domande.toml"
    percorso.write_text("# vuoto\n", encoding="utf-8")
    with pytest.raises(ErroreRicerca):
        leggi_domande(percorso)



# --- lezione 8, esercizio 3: domande composte e senza risposta ---

# Verifica la lettura di una domanda composta con più fonti e indizi.
def test_domanda_composta(tmp_path):
    file = tmp_path / "d.toml"
    file.write_text('[[domanda]]\ntesto = "a e b?"\nfonti = [126, 231]\nindizi = ["due torli", "Uova, N. 2."]\n',
                    encoding="utf-8")
    domanda = leggi_domande(file)[0]
    assert domanda.fonti == (126, 231) and domanda.indizi == ("due torli", "Uova, N. 2.") and domanda.composta


# Verifica che per una composta conti la prima fonte trovata, con il suo indizio.
def test_composta_conta_la_prima_fonte_trovata():
    riga = valuta([Domanda("a e b?", (126, 231), ("due torli", "Uova, N. 2."))],
                  cerca_con([ris(1, 7, 0.9), ris(2, 231, 0.8, "Uova, N. 2.")]))[0]
    assert (riga.posizione, riga.contiene) == (2, True)


# Verifica la colonna della fonte attesa con più fonti.
def test_tabella_composta():
    righe = valuta([Domanda("a e b?", (126, 231), ("x", "y"))], cerca_con([ris(1, 126, 0.9, "x")]))
    assert "| a e b? | 126, 231 | 1 |" in tabella_markdown(righe, INTESTAZIONE)


# Verifica gli errori di formato di fonti e indizi.
@pytest.mark.parametrize("seconda", [
    '[[domanda]]\ntesto = "x"\nfonti = [1, 2]\nindizi = ["a"]\n',                         # lunghezze diverse
    '[[domanda]]\ntesto = "x"\nfonti = []\nindizi = []\n',                                # liste vuote
    '[[domanda]]\ntesto = "x"\nfonte = 1\nindizio = "a"\nfonti = [1]\nindizi = ["a"]\n',  # forme mescolate
    '[[domanda]]\ntesto = "x"\nfonti = ["1"]\nindizi = ["a"]\n',                          # fonte non intera
    '[[domanda]]\ntesto = "x"\nfonti = [1]\nindizi = [""]\n',                             # indizio vuoto
])
def test_fonti_non_valide(tmp_path, seconda):
    percorso = tmp_path / "domande.toml"
    percorso.write_text(VALIDA + seconda, encoding="utf-8")
    with pytest.raises(ErroreRicerca, match="domanda 2"):
        leggi_domande(percorso)


# Verifica il file vero: 10 domande, 2 composte, 3 senza risposta.
def test_file_delle_domande_della_lezione_8():
    domande = leggi_domande(DOMANDE_VERE)
    assert len(domande) == 10
    assert sum(d.composta for d in domande) == 2 and sum(not d.fonti for d in domande) == 3
