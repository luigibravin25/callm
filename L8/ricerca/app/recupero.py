"""Modulo di recupero della lezione 8 (esercizio 3): riscrittura e scomposizione della domanda, fusione RRF,
reranking listwise e ripieghi. Usato dal server MCP di ricerca e dallo script di confronto."""
# librerie standard: JSON, classi di dati e copie modificate dei risultati
import json
from dataclasses import dataclass, replace

from app.chat import Chat
from app.indice import Risultato
# id citabile e troncamento del testo: gli stessi del risultato del tool (risultato.py non importa questo modulo)
from mcp_ricerca.risultato import id_citabile, tronca

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

# prompt di reranking approvato dall'utente (specifica §7.2), testo esatto
PROMPT_RERANKING = (
    "Ricevi una domanda e alcuni passaggi di un ricettario, ognuno con un id tra parentesi quadre. Restituisci gli "
    "id dei passaggi utili a rispondere alla domanda, anche solo a una sua parte, dal più utile al meno utile. "
    "Ometti i passaggi che non c'entrano. Se nessun passaggio è utile, restituisci una lista vuota. Usa solo gli "
    "id ricevuti. Rispondi solo con il JSON richiesto."
)
# schema JSON della risposta di reranking
SCHEMA_RERANKING = {"type": "object", "properties": {"id": {"type": "array", "items": {"type": "string"}}},
                    "required": ["id"]}
# caratteri massimi del testo di un candidato mandato al reranking (deciso dal codice)
TESTO_RERANK = 400


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


# messaggio utente del reranking: la domanda, una riga vuota, un candidato per riga con id, titolo e capitolo
def _messaggio_reranking(domanda: str, candidati: list[Risultato]) -> str:
    righe = [f"[{id_citabile(r.numero, r.indice_chunk)}] {r.titolo} ({r.capitolo}): "
             f"{tronca(r.testo, TESTO_RERANK)[0]}" for r in candidati]
    return f"Domanda: {domanda}\n\n" + "\n".join(righe)


def riordina(domanda: str, candidati: list[Risultato], chat: Chat,
             partenza: str) -> tuple[list[Risultato], str | None, int]:
    """Reranking listwise: (candidati riordinati, eventuale ripiego, id scartati). Lista vuota = esclusi tutti;
    in ripiego si tiene l'ordine ricevuto (`partenza`: "vettoriale" o "RRF")."""
    try:
        risposta = chat.completa_json(PROMPT_RERANKING, _messaggio_reranking(domanda, candidati), "reranking",
                                      SCHEMA_RERANKING)
    except Exception:
        # qualsiasi errore della chiamata: mai un errore verso l'agente
        return candidati, f"reranking: errore della chiamata → ordine {partenza}", 0
    ricevuti = _elenco_json(risposta, "id")
    if ricevuti is None:
        return candidati, f"reranking: JSON non valido → ordine {partenza}", 0
    # lista vuota: nessun candidato utile, esclusi tutti (astensione, non ripiego)
    if not ricevuti:
        return [], None, 0
    per_id = {id_citabile(r.numero, r.indice_chunk): r for r in candidati}
    tenuti: list[Risultato] = []
    visti: set[str] = set()
    scartati = 0
    for grezzo in ricevuti:
        # id senza spazi e parentesi quadre ai bordi (il modello può scriverli come nel messaggio)
        pulito = grezzo.strip().strip("[]").strip()
        # id inventato o già visto: scartato e contato
        if pulito not in per_id or pulito in visti:
            scartati += 1
            continue
        visti.add(pulito)
        tenuti.append(per_id[pulito])
    # nessun id valido in una lista non vuota: risposta inaffidabile, si torna all'ordine di partenza
    if not tenuti:
        return candidati, f"reranking: id inventati → ordine {partenza}", scartati
    return _rinumera(tenuti), None, scartati


# esito di una ricerca: passaggi nell'ordine finale e ciò che serve al risultato, al log e al confronto
@dataclass(frozen=True)
class EsitoRecupero:
    risultati: list[Risultato]  # al massimo top_k, posizione 1..n
    modalita: str  # modalità usata
    query_usate: list[str]  # query cercate, la domanda per prima
    ripieghi: list[str]  # ripieghi della chiamata, vuoto se nessuno
    chiamate_llm: int  # chiamate al modello di chat tentate
    id_scartati: int  # id inventati o doppioni scartati dal reranking


def recupera(domanda: str, top_k: int, capitolo: str | None, *, indice, chat: Chat | None, modalita: str,
             candidati: int, tetto: int) -> EsitoRecupero:
    """Ricerca nella modalità indicata (specifica §6.1); gli errori dell'indice passano, quelli dell'LLM no."""
    ripieghi: list[str] = []
    chiamate = 0
    query = [domanda]
    # riscrittura: 1-3 query (la domanda per prima), oppure la sola domanda in ripiego
    if modalita in ("riscrittura", "entrambe"):
        query, ripiego = query_di_ricerca(domanda, chat)
        chiamate += 1
        if ripiego:
            ripieghi.append(ripiego)
    # stessi candidati per query in tutte le modalità (un solo fattore cambiato nel confronto)
    liste = [indice.cerca(q, capitolo=capitolo, k=candidati) for q in query]
    # con una sola query la fusione lascia l'ordine vettoriale
    ordinati = fondi_rrf(liste)
    scartati = 0
    # reranking dei primi `tetto` candidati, giudicati sulla domanda originale; senza candidati non serve
    if modalita in ("reranking", "entrambe") and ordinati:
        partenza = "RRF" if modalita == "entrambe" else "vettoriale"
        ordinati, ripiego, scartati = riordina(domanda, ordinati[:tetto], chat, partenza)
        chiamate += 1
        if ripiego:
            ripieghi.append(ripiego)
    return EsitoRecupero(risultati=_rinumera(ordinati[:top_k]), modalita=modalita, query_usate=query,
                         ripieghi=ripieghi, chiamate_llm=chiamate, id_scartati=scartati)
