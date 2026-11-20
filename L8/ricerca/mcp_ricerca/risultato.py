"""Forma del risultato del tool search_documents: id citabile, testo troncato, limite di top_k (funzioni pure)."""
# librerie standard: dizionari tipizzati (danno al tool lo schema di uscita nella discovery)
from typing import TypedDict

from app.errori import ErroreRicerca
from app.indice import Risultato

# massimo di passaggi per chiamata, imposto dal codice del tool (contesto di un modello piccolo)
TOP_K_MASSIMO_TOOL = 10
# caratteri massimi del testo di un passaggio restituito al modello
TESTO_MASSIMO = 800


# un passaggio restituito al modello, con l'id da citare e la sua fonte
class Passaggio(TypedDict):
    id: str  # id citabile, es. R89-1
    ricetta: int  # numero della ricetta
    titolo: str
    capitolo: str
    posizione: str  # "chunk i di n"
    score: float  # similarità coseno, 4 decimali
    testo: str  # testo del chunk, al massimo TESTO_MASSIMO caratteri
    troncato: bool  # il testo è stato tagliato


# risultato completo del tool
class RisultatoRicerca(TypedDict):
    modalita: str  # modalità di recupero usata (dalla configurazione del server)
    query: str  # domanda cercata
    query_usate: list[str]  # query cercate davvero, la domanda per prima (esercizio 3)
    ripieghi: list[str]  # ripieghi di riscrittura o reranking, vuoto se nessuno (esercizio 3)
    top_k: int  # passaggi richiesti, dopo l'eventuale riduzione
    capitolo: str  # capitolo del filtro, "" se nessuno
    nota: str | None  # es. top_k ridotto
    passaggi: list[Passaggio]  # anche meno di top_k, o nessuno se il reranking li esclude tutti


def id_citabile(numero: int, indice_chunk: int) -> str:
    """Id leggibile e stabile dalla posizione: ricetta e chunk contato da 1 (es. R89-1)."""
    return f"R{numero}-{indice_chunk + 1}"


def tronca(testo: str, massimo: int = TESTO_MASSIMO) -> tuple[str, bool]:
    """Testo entro `massimo` caratteri, tagliato all'ultimo spazio; True se è stato tagliato."""
    if len(testo) <= massimo:
        return testo, False
    taglio = testo.rfind(" ", 0, massimo + 1)
    # nessuno spazio entro il limite (parola lunghissima): taglio secco
    if taglio <= 0:
        taglio = massimo
    return testo[:taglio].rstrip(), True


def limita_top_k(top_k: int) -> tuple[int, str | None]:
    """top_k entro 1..TOP_K_MASSIMO_TOOL; oltre il massimo si riduce e si restituisce la nota."""
    if top_k < 1:
        raise ErroreRicerca(f"top_k={top_k} non valido (ammesso: 1-{TOP_K_MASSIMO_TOOL})")
    if top_k > TOP_K_MASSIMO_TOOL:
        return TOP_K_MASSIMO_TOOL, f"top_k {top_k} ridotto a {TOP_K_MASSIMO_TOOL}"
    return top_k, None


def passaggio(r: Risultato) -> Passaggio:
    """Risultato della ricerca → passaggio per il modello (id citabile, fonte, testo troncato)."""
    testo, troncato = tronca(r.testo)
    return Passaggio(id=id_citabile(r.numero, r.indice_chunk), ricetta=r.numero, titolo=r.titolo,
                     capitolo=r.capitolo, posizione=f"chunk {r.indice_chunk + 1} di {r.totale_chunk}",
                     score=round(r.score, 4), testo=testo, troncato=troncato)
