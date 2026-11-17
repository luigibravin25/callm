"""Divisione delle ricette in chunk: strategia "paragrafi" (predefinita) o "caratteri" (specifica, §8).

Dimensione e overlap sono in caratteri: nessuna dipendenza dal tokenizer del modello.
"""
# librerie standard: espressioni regolari, classi di dati
import re
from dataclasses import dataclass

from app.config import STRATEGIE
from app.corpus import Ricetta
from app.errori import ErroreRicerca

# fine di una frase: dopo . ; : ! ? seguiti da spazio o a capo
_FINE_FRASE = re.compile(r"(?<=[.;:!?])\s+")


# un chunk con la sua fonte: ricetta, capitolo e posizione nella ricetta
@dataclass(frozen=True)
class Chunk:
    numero: int
    titolo: str
    capitolo: str
    indice_chunk: int  # posizione nella ricetta, da 0
    totale_chunk: int  # chunk della stessa ricetta
    testo: str


# errore se strategia, dimensione o overlap non sono ammessi
def _controlla(strategia: str, dimensione: int, overlap: int) -> None:
    if strategia not in STRATEGIE:
        raise ErroreRicerca(f"strategia di chunking {strategia!r} non valida (ammesse: {', '.join(STRATEGIE)})")
    if dimensione < 1:
        raise ErroreRicerca(f"dimensione dei chunk {dimensione} non valida (ammesso: intero >= 1)")
    if not 0 <= overlap < dimensione:
        raise ErroreRicerca(f"overlap {overlap} non valido (ammesso: 0 <= overlap < {dimensione})")


# prima posizione >= da (e > 0) dove inizia una parola: carattere non spazio dopo uno spazio
def _inizio_parola(testo: str, da: int) -> int:
    k = max(da, 1)
    while k < len(testo) and not (testo[k - 1].isspace() and not testo[k].isspace()):
        k += 1
    return k


# coda di un chunk lunga al massimo `overlap` caratteri, tagliata all'inizio di una parola
def _coda(testo: str, overlap: int) -> str:
    if overlap == 0:
        return ""
    return testo[_inizio_parola(testo, len(testo) - overlap):]


# toglie la prima parola della coda (per farla stare nel chunk insieme al pezzo seguente)
def _accorcia(coda: str) -> str:
    return coda[_inizio_parola(coda, 1):]


# pezzi della strategia "paragrafi": (testo, inizia un paragrafo nuovo?)
def _pezzi(testo: str, dimensione: int) -> list[tuple[str, bool]]:
    pezzi: list[tuple[str, bool]] = []
    for paragrafo in testo.split("\n\n"):
        paragrafo = paragrafo.strip()
        if not paragrafo:
            continue
        if len(paragrafo) <= dimensione:
            pezzi.append((paragrafo, True))
            continue
        # paragrafo troppo lungo → frasi; frase troppo lunga → parole
        parti: list[str] = []
        for frase in _FINE_FRASE.split(paragrafo):
            parti.extend([frase] if len(frase) <= dimensione else frase.split())
        pezzi.extend((parte, i == 0) for i, parte in enumerate(parti))
    return pezzi


def _per_paragrafi(testo: str, dimensione: int, overlap: int) -> list[str]:
    chunk: list[str] = []
    corrente = ""
    for pezzo, nuovo_paragrafo in _pezzi(testo, dimensione):
        # tra paragrafi una riga vuota, dentro un paragrafo uno spazio
        separatore = "\n\n" if nuovo_paragrafo else " "
        candidato = pezzo if not corrente else corrente + separatore + pezzo
        if len(candidato) <= dimensione:
            corrente = candidato
            continue
        # il pezzo non ci sta: si chiude il chunk e il seguente riparte dalla sua coda
        chunk.append(corrente)
        coda = _coda(corrente, overlap)
        while coda and len(coda) + 1 + len(pezzo) > dimensione:
            coda = _accorcia(coda)
        corrente = f"{coda} {pezzo}" if coda else pezzo
    if corrente:
        chunk.append(corrente)
    return chunk


def _per_caratteri(testo: str, dimensione: int, overlap: int) -> list[str]:
    chunk: list[str] = []
    inizio = 0
    while inizio < len(testo):
        fine = inizio + dimensione
        if fine >= len(testo):
            chunk.append(testo[inizio:].strip())
            break
        # bordo spostato indietro all'ultimo spazio, per non tagliare una parola
        taglio = next((j for j in range(fine, inizio, -1) if testo[j].isspace()), fine)
        chunk.append(testo[inizio:taglio].strip())
        # la finestra seguente riparte `overlap` caratteri prima, all'inizio di una parola
        inizio = _inizio_parola(testo, max(taglio - overlap, inizio + 1))
    return [c for c in chunk if c]


def dividi(testo: str, strategia: str, dimensione: int, overlap: int) -> list[str]:
    """Divide un testo in chunk di al massimo `dimensione` caratteri con `overlap` caratteri di raccordo."""
    _controlla(strategia, dimensione, overlap)
    testo = testo.strip()
    # un testo che ci sta tutto è un solo chunk, uguale al testo
    if len(testo) <= dimensione:
        return [testo] if testo else []
    if strategia == "paragrafi":
        return _per_paragrafi(testo, dimensione, overlap)
    return _per_caratteri(testo, dimensione, overlap)


def chunk_delle_ricette(ricette: list[Ricetta], strategia: str, dimensione: int, overlap: int) -> list[Chunk]:
    """Chunk di tutte le ricette, nell'ordine: ricetta, poi posizione nella ricetta."""
    chunk: list[Chunk] = []
    for ricetta in ricette:
        testi = dividi(ricetta.testo, strategia, dimensione, overlap)
        chunk.extend(Chunk(ricetta.numero, ricetta.titolo, ricetta.capitolo, i, len(testi), t)
                     for i, t in enumerate(testi))
    return chunk
