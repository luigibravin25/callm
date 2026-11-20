# test del modulo di recupero (lezione 8, esercizio 3): riscrittura, fusione RRF, reranking, modalità.
# LLM finto e indice finto: nessun servizio.
import pytest

from app.errori import ErroreRicerca
from app.recupero import PROMPT_RISCRITTURA, query_di_ricerca
from tests.finti import ChatFinta


# --- riscrittura e scomposizione ---

# Verifica l'originale per prima, spazi e doppioni tolti, al massimo 3 query in tutto.
def test_riscrittura_originale_prima_senza_doppioni():
    chat = ChatFinta(['{"query": ["  salsa maionese tuorli ", "Gnocchi alla romana uova", '
                      '"salsa maionese tuorli", "terza"]}'])
    query, ripiego = query_di_ricerca("Domanda?", chat)
    assert query == ["Domanda?", "salsa maionese tuorli", "Gnocchi alla romana uova"]
    assert ripiego is None
    assert chat.chiamate[0][0] == PROMPT_RISCRITTURA and chat.chiamate[0][1] == "Domanda?"


# Verifica che una copia della domanda (maiuscole diverse) non diventi una seconda query.
def test_riscrittura_toglie_la_copia_della_domanda():
    query, _ = query_di_ricerca("Che vino?", ChatFinta(['{"query": ["che VINO?", "vino pollo"]}']))
    assert query == ["Che vino?", "vino pollo"]


# Verifica i ripieghi sulla sola domanda, con il motivo nel testo.
@pytest.mark.parametrize("risposta, motivo", [
    ("non è json", "JSON non valido"),
    ('{"altro": []}', "JSON non valido"),
    ('{"query": "una"}', "JSON non valido"),
    ('["q"]', "JSON non valido"),
    ('{"query": []}', "lista vuota"),
    ('{"query": ["  ", ""]}', "nessuna query valida"),
])
def test_riscrittura_ripiego(risposta, motivo):
    query, ripiego = query_di_ricerca("D?", ChatFinta([risposta]))
    assert query == ["D?"] and ripiego == f"riscrittura: {motivo} → sola domanda"


# Verifica il ripiego quando LM Studio non risponde.
def test_riscrittura_errore_della_chiamata():
    query, ripiego = query_di_ricerca("D?", ChatFinta([ErroreRicerca("spenta")]))
    assert query == ["D?"] and ripiego == "riscrittura: errore della chiamata → sola domanda"


# Verifica il ripiego con una risposta vuota (modello che ragiona e non scrive il JSON).
def test_riscrittura_risposta_vuota():
    _, ripiego = query_di_ricerca("D?", ChatFinta([""]))
    assert ripiego == "riscrittura: JSON non valido → sola domanda"


# Verifica il ripiego con elementi che non sono testi.
def test_riscrittura_elementi_non_testo():
    _, ripiego = query_di_ricerca("D?", ChatFinta(['{"query": [1, null]}']))
    assert ripiego == "riscrittura: JSON non valido → sola domanda"
