# Test della logica della calcolatrice sicura (servizio/calcolatrice.py), senza HTTP.
# Path serve a leggere il sorgente del modulo; pytest per i test parametrizzati
from pathlib import Path

import pytest

# il modulo da provare, la sua eccezione e la funzione che calcola
from servizio import calcolatrice
from servizio.calcolatrice import ErroreCalcolo, calcola


# Supporto: si aspetta un ErroreCalcolo e ne restituisce il messaggio da controllare.
def rifiuto(espressione: str) -> str:
    """Messaggio dell'errore sollevato dalla calcolatrice per un input rifiutato."""
    with pytest.raises(ErroreCalcolo) as errore:
        calcola(espressione)
    return str(errore.value)


# Verifica i risultati corretti: precedenza (* prima di +), parentesi, potenza associativa a
# destra (2^3^2 = 512), segni unari, spazi, decimali. Ogni coppia e' (espressione, risultato).
@pytest.mark.parametrize("espr, atteso", [
    ("1+2", 3), ("2*3+4", 10), ("2+3*4", 14), ("(2+3)*4", 20), ("8/4/2", 1),
    ("5-3-1", 1), ("2^3^2", 512), ("2**3**2", 512), ("2^3", 8), ("-2^2", -4),
    ("(-2)^2", 4), ("2^-1", 0.5), ("-3+2", -1), ("2*-4", -8), ("-(2+1)", -3),
    ("--3", 3), ("+3", 3), (" 1 + 2 ", 3), ("3.5*2", 7), ("((1+2)*(3+4))", 21),
    ("0^0", 1), ("10^-50", 1e-50), ("7/2", 3.5),
])
def test_espressioni_valide(espr, atteso):
    # pytest.approx tollera i piccoli errori di arrotondamento dei numeri decimali
    assert calcola(espr) == pytest.approx(atteso)


# Verifica il rifiuto esplicito degli input non validi (requisito: nessun risultato inventato).
# Ogni coppia e' (espressione, parte del messaggio d'errore atteso): vuota, troppo lunga,
# caratteri e operatori non ammessi, sintassi, numeri malformati, annidamento, divisione per
# zero, potenze non reali, risultati troppo grandi.
@pytest.mark.parametrize("espr, motivo", [
    ("", "espressione vuota"), ("   ", "espressione vuota"),
    ("1+" * 100 + "1", "troppo lunga"),
    ("2+x", "carattere non ammesso 'x' in posizione 3"),
    ("sqrt(4)", "carattere non ammesso 's'"), ("10%3", "carattere non ammesso '%'"),
    ("3 × 4", "carattere non ammesso '×'"), ("3 x 4", "carattere non ammesso 'x'"),
    ("5 − 2", "carattere non ammesso '−'"), ("2+2=", "carattere non ammesso '='"),
    ("1e3", "carattere non ammesso 'e'"), ("[1+2]", "carattere non ammesso '['"),
    ("7//2", "operatore non ammesso '//'"),
    ("2+", "sintassi non valida"), ("*3", "sintassi non valida"),
    ("(1+2", "sintassi non valida"), ("1+2)", "sintassi non valida"),
    ("()", "sintassi non valida"), ("2(3)", "sintassi non valida"),
    ("(1)(2)", "sintassi non valida"), ("1 2", "sintassi non valida"),
    ("2 * * 3", "sintassi non valida"),
    ("1.2.3", "numero non valido"), (".5", "numero non valido"), ("5.", "numero non valido"),
    ("(" * 51 + "1" + ")" * 51, "annidamento eccessivo"),
    ("-" * 51 + "1", "annidamento eccessivo"),
    ("1/0", "divisione per zero"), ("0^-1", "divisione per zero"),
    ("1/(2-2)", "divisione per zero"),
    ("(-8)^(1/3)", "potenza non definita nei reali"),
    ("9^9^9", "risultato troppo grande"), ("10^200", "risultato troppo grande"),
    ("10^60*10^60", "risultato troppo grande"), ("9" * 150, "risultato troppo grande"),
])
def test_rifiuti(espr, motivo):
    # controllo: il messaggio d'errore contiene il motivo atteso
    assert motivo in rifiuto(espr)


# Verifica che la virgola decimale all'italiana sia rifiutata con un suggerimento utile.
def test_virgola_suggerisce_il_punto():
    messaggio = rifiuto("2,5*2")
    # controllo: indica il carattere sbagliato e suggerisce il punto decimale
    assert "carattere non ammesso ','" in messaggio and "punto decimale" in messaggio


# Verifica il limite: 50 parentesi annidate sono ancora ammesse (51 sono rifiutate, vedi sopra).
def test_annidamento_al_limite_ammesso():
    assert calcola("(" * 50 + "1" + ")" * 50) == 1


# Verifica il limite: un'espressione di 200 caratteri esatti e' ancora calcolata.
def test_lunghezza_al_limite_ammessa():
    # "1" + 99 volte "+1" + uno spazio finale = 200 caratteri, somma 100
    espressione = "1" + "+1" * 99 + " "
    assert len(espressione) == 200
    assert calcola(espressione) == 100


# Verifica di sicurezza: il modulo non usa eval, exec, compile ne' il modulo ast di Python.
def test_nessun_eval_nel_modulo():
    # legge il codice sorgente della calcolatrice come testo
    sorgente = Path(calcolatrice.__file__).read_text(encoding="utf-8")
    # controllo: nessuna parola vietata compare nel sorgente
    for vietato in ("eval(", "exec(", "compile(", "import ast", "from ast"):
        assert vietato not in sorgente


# Verifica che un carattere invisibile (a capo) sia mostrato come codice U+000A, leggibile.
def test_carattere_di_controllo_mostrato_come_codice():
    assert "carattere non ammesso U+000A in posizione 2" in rifiuto("2\n+2")
