# test delle soglie sullo score (lezione 8, esercizio 4): fasce, confini e filtro, con score preparati a mano
import pytest

from app.indice import Risultato
from app.soglie import fascia, filtra


# risultato di prova con la ricetta e lo score dati
def ris(numero: int, score: float) -> Risultato:
    return Risultato(posizione=1, score=score, numero=numero, titolo=f"Ricetta {numero}", capitolo="DOLCI",
                     indice_chunk=0, totale_chunk=1, testo="testo")


# Verifica le tre fasce e i valori uguali alle soglie (alta 0.60, bassa 0.51).
@pytest.mark.parametrize("score, attesa", [(0.61, "affidabile"), (0.60, "affidabile"), (0.5999, "media"),
                                           (0.51, "media"), (0.5099, None), (-0.2, None)])
def test_fasce_ai_confini(score, attesa):
    assert fascia(score, 0.60, 0.51) == attesa


# Verifica che con soglie uguali non ci sia la fascia media.
def test_soglie_uguali_nessuna_media():
    assert (fascia(0.55, 0.55, 0.55), fascia(0.5499, 0.55, 0.55)) == ("affidabile", None)


# Verifica che con soglie a -1 nessuno score sia escluso.
def test_soglie_minime_nessun_escluso():
    assert fascia(-1.0, -1.0, -1.0) == "affidabile"


# Verifica il filtro: ordine conservato, fascia di ogni risultato, numero degli esclusi.
def test_filtra_ordine_e_esclusi():
    rimasti, esclusi = filtra([ris(1, 0.5), ris(2, 0.7), ris(3, 0.55)], 0.60, 0.51)
    assert [(r.numero, f) for r, f in rimasti] == [(2, "affidabile"), (3, "media")] and esclusi == 1
