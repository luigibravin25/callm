"""Modulo di recupero della lezione 8 (esercizio 3): riscrittura e scomposizione della domanda, fusione RRF,
reranking listwise e ripieghi. Usato dal server MCP di ricerca e dallo script di confronto."""
# librerie standard: JSON, copie modificate dei risultati
import json
from dataclasses import replace

from app.chat import Chat
from app.indice import Risultato

# prompt di riscrittura approvato dall'utente (specifica §7.1), testo esatto
PROMPT_RISCRITTURA = (
    "Trasforma la domanda dell'utente in query di ricerca per il ricettario di Pellegrino Artusi. Se la domanda "
    "chiede più cose (per esempio due ricette diverse), scomponila: una query per ogni parte. Se chiede una cosa "
    "sola, scrivi una query riformulata. Al massimo 2 query, brevi, con i nomi dei piatti e degli ingredienti. "
    "Non rispondere alla domanda e non aggiungere informazioni. Rispondi solo con il JSON richiesto."
)
# schema JSON della risposta di riscrittura (structured output di LM Studio)
SCHEMA_RISCRITTURA = {"type": "object", "properties": {"query": {"type": "array", "items": {"type": "string"}}},
                      "required": ["query"]}
# query in tutto, originale compresa (decisione dell'utente, domanda 4)
QUERY_MASSIME = 3
# costante della fusione per rango (Reciprocal Rank Fusion)
RRF_K = 60


# elenco di testi sotto `chiave` in una risposta JSON; None se il JSON non è valido o ha un'altra forma
def _elenco_json(testo: str, chiave: str) -> list[str] | None:
    try:
        dati = json.loads(testo)
    except (json.JSONDecodeError, TypeError):
        return None
    # serve un oggetto con la chiave e una lista di soli testi
    if not isinstance(dati, dict) or not isinstance(dati.get(chiave), list):
        return None
    if not all(isinstance(elemento, str) for elemento in dati[chiave]):
        return None
    return dati[chiave]


def query_di_ricerca(domanda: str, chat: Chat) -> tuple[list[str], str | None]:
    """Query da cercare (la domanda per prima, 1-3 in tutto) e l'eventuale ripiego sulla sola domanda."""
    try:
        risposta = chat.completa_json(PROMPT_RISCRITTURA, domanda, "riscrittura", SCHEMA_RISCRITTURA)
    except Exception:
        # qualsiasi errore della chiamata (LM Studio spento, timeout): mai un errore verso l'agente
        return [domanda], "riscrittura: errore della chiamata → sola domanda"
    riscritte = _elenco_json(risposta, "query")
    if riscritte is None:
        return [domanda], "riscrittura: JSON non valido → sola domanda"
    if not riscritte:
        return [domanda], "riscrittura: lista vuota → sola domanda"
    # l'originale resta sempre per prima; doppioni confrontati senza maiuscole e spazi ai bordi
    query = [domanda]
    viste = {domanda.strip().lower()}
    valide = 0
    for testo in riscritte:
        pulita = testo.strip()
        if not pulita:
            continue
        valide += 1
        if pulita.lower() in viste:
            continue
        viste.add(pulita.lower())
        # al massimo QUERY_MASSIME query in tutto: le altre si scartano
        if len(query) < QUERY_MASSIME:
            query.append(pulita)
    # solo stringhe vuote o di spazi: nessuna query da usare
    if valide == 0:
        return [domanda], "riscrittura: nessuna query valida → sola domanda"
    return query, None


# risultati con la posizione rinumerata 1..n nell'ordine dato
def _rinumera(risultati: list[Risultato]) -> list[Risultato]:
    return [replace(r, posizione=i) for i, r in enumerate(risultati, start=1)]


def fondi_rrf(liste: list[list[Risultato]]) -> list[Risultato]:
    """Unione senza doppioni delle liste delle query, ordinata per punteggio RRF (somma di 1/(60 + rango))."""
    punteggi: dict[tuple[int, int], float] = {}
    migliori: dict[tuple[int, int], Risultato] = {}
    for lista in liste:
        for rango, r in enumerate(lista, start=1):
            # un chunk è identificato da ricetta e numero del chunk
            chiave = (r.numero, r.indice_chunk)
            punteggi[chiave] = punteggi.get(chiave, 0.0) + 1 / (RRF_K + rango)
            # si tiene lo score coseno più alto tra le query
            if chiave not in migliori or r.score > migliori[chiave].score:
                migliori[chiave] = r
    # punteggio RRF decrescente, poi score coseno decrescente, poi id: ordine stabile e riproducibile
    ordine = sorted(punteggi, key=lambda c: (-punteggi[c], -migliori[c].score, c))
    return _rinumera([migliori[c] for c in ordine])
