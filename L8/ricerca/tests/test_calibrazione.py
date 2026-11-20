# test della calibrazione delle soglie (lezione 8, esercizio 4): score delle fonti e soglie proposte
from app.calibrazione import riga, soglie_proposte, tabella_calibrazione
from app.indice import Risultato
from app.valutazione import Domanda

SEMPLICE_208 = Domanda("vino?", (208,), ("vino rosso",))
COMPOSTA_126_231 = Domanda("a e b?", (126, 231), ("due torli", "Uova, N. 2."))
VUOTA = Domanda("sushi?", (), ())


# risultato di prova: ricetta, score, chunk
def ris(numero: int, score: float, chunk: int = 0) -> Risultato:
    return Risultato(posizione=1, score=score, numero=numero, titolo=f"Ricetta {numero}", capitolo="DOLCI",
                     indice_chunk=chunk, totale_chunk=chunk + 1, testo="testo")


# Verifica che lo score di una fonte sia quello del suo chunk migliore (None se assente).
def test_calibrazione_chunk_migliore():
    r = riga(COMPOSTA_126_231, [ris(126, 0.55, chunk=1), ris(126, 0.64, chunk=0), ris(5, 0.6)])
    assert r.score_fonti == {126: 0.64, 231: None}
    assert r.score == [0.55, 0.64, 0.6]


# Verifica la regola approvata: bassa per difetto sotto la fonte più debole, alta per eccesso sopra le senza risposta.
def test_soglie_proposte():
    righe = [riga(SEMPLICE_208, [ris(208, 0.5191)]), riga(VUOTA, [ris(5, 0.5912), ris(6, 0.52)])]
    assert soglie_proposte(righe) == (0.5191, 0.5912, 0.60, 0.51)


# Verifica che senza sovrapposizione le soglie coincidano (nessuna fascia media), sempre valide.
def test_soglie_senza_sovrapposizione():
    righe = [riga(SEMPLICE_208, [ris(208, 0.80)]), riga(VUOTA, [ris(5, 0.40)])]
    assert soglie_proposte(righe)[2:] == (0.80, 0.80)


# Verifica la tabella Markdown con score e soglie proposte.
def test_tabella_calibrazione():
    testo = tabella_calibrazione([riga(SEMPLICE_208, [ris(208, 0.6141)]), riga(VUOTA, [ris(5, 0.53)])], {"k": "5"})
    assert "0.6141" in testo and "soglia bassa proposta" in testo and "- k: 5" in testo


# Verifica un errore chiaro (non un ValueError) se mancano domande con fonte trovata o domande senza risposta.
def test_soglie_proposte_senza_dati():
    import pytest
    from app.errori import ErroreRicerca
    with pytest.raises(ErroreRicerca, match="nessuna fonte attesa"):
        soglie_proposte([riga(SEMPLICE_208, [ris(5, 0.6)]), riga(VUOTA, [ris(5, 0.5)])])
    with pytest.raises(ErroreRicerca, match="nessuna domanda senza risposta"):
        soglie_proposte([riga(SEMPLICE_208, [ris(208, 0.6)])])
