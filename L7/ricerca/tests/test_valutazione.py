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
    domande = leggi_domande(DOMANDE_VERE)
    assert len(domande) == 6
    assert [d.fonte for d in domande] == [89, 7, 208, 89, 455, None]
    assert [d.indizio for d in domande] == ["grammi 400", "mangiatore discreto", "vino rosso", "si liquefecero",
                                            "brodetto", None]


def test_fonte_al_secondo_posto():
    domanda = Domanda("gnocchi?", 89, "grammi 400")
    riga = valuta([domanda], cerca_con([ris(1, 7, 0.9), ris(2, 89, 0.8, "patate, grammi 400.")]))[0]
    assert (riga.posizione, riga.score, riga.contiene) == (2, 0.8, True)
    assert riga.primo.numero == 7


def test_piu_chunk_della_fonte_conta_il_primo():
    domanda = Domanda("gnocchi?", 89, "grammi 400")
    risultati = [ris(1, 7, 0.9), ris(2, 89, 0.8, "senza indizio"), ris(3, 5, 0.7), ris(4, 89, 0.6, "grammi 400")]
    riga = valuta([domanda], cerca_con(risultati))[0]
    assert (riga.posizione, riga.score, riga.contiene) == (2, 0.8, False)


def test_indizio_con_le_stesse_maiuscole():
    riga = valuta([Domanda("vino?", 208, "vino rosso")], cerca_con([ris(1, 208, 0.9, "Vino Rosso")]))[0]
    assert riga.contiene is False


def test_fonte_assente():
    righe = valuta([Domanda("cacciucco?", 455, "brodetto")], cerca_con([ris(1, 7, 0.9)]))
    assert (righe[0].posizione, righe[0].score, righe[0].contiene) == (None, None, None)
    riga_tabella = tabella_markdown(righe, INTESTAZIONE).splitlines()[-1]
    assert "| assente |" in riga_tabella and "| — |" in riga_tabella


def test_domanda_senza_fonte():
    righe = valuta([Domanda("tiramisù?", None, None)], cerca_con([ris(1, 7, 0.61234), ris(2, 8, 0.5)]))
    assert righe[0].score_risultati == [0.61234, 0.5]
    assert "0.6123, 0.5000" in tabella_markdown(righe, INTESTAZIONE)


def test_tabella():
    righe = valuta([Domanda("gnocchi?", 89, "grammi 400")], cerca_con([ris(1, 89, 0.81234, "grammi 400")]))
    tabella = tabella_markdown(righe, INTESTAZIONE)
    assert tabella.startswith("- modello: bge\n- collezione: ricettario\n- punti: 1234\n"
                              "- chunking: paragrafi 1000/150\n- k: 5\n\n")
    assert tabella.splitlines()[-1] == "| gnocchi? | 89 | 1 | 0.8123 | sì | n. 89 «Ricetta 89» 0.8123 |"


def test_tabella_riproducibile():
    risultati = [ris(1, 89, 0.81234, "grammi 400"), ris(2, 7, 0.5)]
    domande = [Domanda("gnocchi?", 89, "grammi 400"), Domanda("tiramisù?", None, None)]
    prima = tabella_markdown(valuta(domande, cerca_con(risultati)), INTESTAZIONE)
    assert tabella_markdown(valuta(domande, cerca_con(risultati)), INTESTAZIONE) == prima
