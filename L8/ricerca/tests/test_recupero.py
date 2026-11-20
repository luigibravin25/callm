# test del modulo di recupero (lezione 8, esercizio 3): riscrittura, fusione RRF, reranking, modalità.
# LLM finto e indice finto: nessun servizio.
from dataclasses import replace

import pytest

from app.errori import ErroreRicerca
from app.indice import Risultato
from app.recupero import PROMPT_RERANKING, PROMPT_RISCRITTURA, fondi_rrf, query_di_ricerca, riordina
from tests.finti import ChatFinta


# risultato di prova: ricetta `numero`, chunk `chunk` (da 0), score coseno
def ris(numero: int, chunk: int, score: float, testo: str = "testo di prova") -> Risultato:
    return Risultato(posizione=1, score=score, numero=numero, titolo=f"Ricetta {numero}", capitolo="DOLCI",
                     indice_chunk=chunk, totale_chunk=chunk + 1, testo=testo)


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


# --- fusione RRF ---

# Verifica l'unione senza doppioni, l'ordine per punteggio RRF e lo score coseno più alto.
def test_rrf_unione_senza_doppioni():
    a = [ris(1, 0, 0.9), ris(2, 0, 0.8)]
    b = [ris(2, 0, 0.85), ris(3, 0, 0.7)]
    fusi = fondi_rrf([a, b])
    assert [(r.numero, r.posizione) for r in fusi] == [(2, 1), (1, 2), (3, 3)]
    assert fusi[0].score == 0.85


# Verifica che a pari punteggio RRF venga prima lo score coseno più alto.
def test_rrf_pari_punteggio_vince_lo_score():
    fusi = fondi_rrf([[ris(1, 0, 0.5)], [ris(2, 0, 0.6)]])
    assert [r.numero for r in fusi] == [2, 1]


# Verifica che con una sola query l'ordine vettoriale resti com'è.
def test_rrf_una_sola_lista_ordine_invariato():
    lista = [ris(5, 0, 0.9), ris(4, 1, 0.8), ris(3, 0, 0.7)]
    assert [(r.numero, r.indice_chunk) for r in fondi_rrf([lista])] == [(5, 0), (4, 1), (3, 0)]


# --- reranking listwise ---

CANDIDATI = [ris(89, 0, 0.9), ris(208, 0, 0.8), ris(7, 0, 0.7)]


# Verifica l'ordine restituito, gli id omessi esclusi e il messaggio mandato al modello.
def test_reranking_ordine_ed_esclusi():
    chat = ChatFinta(['{"id": ["R208-1", "R89-1"]}'])
    ordinati, ripiego, scartati = riordina("Che vino?", CANDIDATI, chat, "vettoriale")
    assert [(r.numero, r.posizione) for r in ordinati] == [(208, 1), (89, 2)]
    assert (ripiego, scartati) == (None, 0)
    sistema, utente, _ = chat.chiamate[0]
    assert sistema == PROMPT_RERANKING and utente.startswith("Domanda: Che vino?\n\n[R89-1] Ricetta 89 (DOLCI): ")


# Verifica che la lista vuota escluda tutti i candidati senza ripiego.
def test_reranking_lista_vuota_esclude_tutti():
    assert riordina("D?", CANDIDATI, ChatFinta(['{"id": []}']), "vettoriale") == ([], None, 0)


# Verifica che id inventati e doppioni siano scartati e contati, tenendo quelli validi.
def test_reranking_scarta_inventati_e_doppioni():
    ordinati, ripiego, scartati = riordina("D?", CANDIDATI, ChatFinta(['{"id": ["R7-1", "R999-1", "R7-1"]}']),
                                           "RRF")
    assert [r.numero for r in ordinati] == [7] and ripiego is None and scartati == 2


# Verifica il ripiego sull'ordine di partenza quando tutti gli id sono inventati.
def test_reranking_solo_inventati():
    ordinati, ripiego, _ = riordina("D?", CANDIDATI, ChatFinta(['{"id": ["R1-1"]}']), "RRF")
    assert ordinati == CANDIDATI and ripiego == "reranking: id inventati → ordine RRF"


# Verifica il ripiego con JSON non valido o di forma sbagliata.
@pytest.mark.parametrize("risposta", ["{", '{"id": "R89-1"}', '{"altro": []}'])
def test_reranking_json_non_valido(risposta):
    ordinati, ripiego, _ = riordina("D?", CANDIDATI, ChatFinta([risposta]), "vettoriale")
    assert ordinati == CANDIDATI and ripiego == "reranking: JSON non valido → ordine vettoriale"


# Verifica il ripiego con un JSON troncato (token finiti).
def test_reranking_json_troncato():
    _, ripiego, _ = riordina("D?", CANDIDATI, ChatFinta(['{"id": ["R89-1", "R2']), "vettoriale")
    assert ripiego == "reranking: JSON non valido → ordine vettoriale"


# Verifica il ripiego quando LM Studio non risponde.
def test_reranking_errore_della_chiamata():
    _, ripiego, _ = riordina("D?", CANDIDATI, ChatFinta([ErroreRicerca("spenta")]), "vettoriale")
    assert ripiego == "reranking: errore della chiamata → ordine vettoriale"


# Verifica che un id con spazi o parentesi quadre sia riconosciuto.
def test_reranking_id_con_parentesi_e_spazi():
    ordinati, _, _ = riordina("D?", CANDIDATI, ChatFinta(['{"id": [" [R7-1] "]}']), "vettoriale")
    assert [r.numero for r in ordinati] == [7]


# Verifica che il testo di un candidato mandato al modello sia al massimo di 400 caratteri.
def test_reranking_testo_troncato():
    lungo = replace(ris(1, 0, 0.9), testo="parola " * 200)
    chat = ChatFinta(['{"id": []}'])
    riordina("D?", [lungo], chat, "vettoriale")
    riga = chat.chiamate[0][1].splitlines()[2]
    assert len(riga.split(": ", 1)[1]) <= 400
