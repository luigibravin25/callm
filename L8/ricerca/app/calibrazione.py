"""Calibrazione delle soglie sullo score (lezione 8, esercizio 4): score delle fonti e soglie proposte."""
# librerie standard: arrotondamenti, classi di dati
import math
from dataclasses import dataclass

from app.errori import ErroreRicerca
from app.indice import Risultato
from app.valutazione import Domanda


# score registrati per una domanda: chunk migliore di ogni fonte attesa e score dei k passaggi
@dataclass(frozen=True)
class RigaCalibrazione:
    domanda: Domanda
    score_fonti: dict[int, float | None]  # fonte → score del suo chunk migliore tra i primi k (None se assente)
    score: list[float]  # score dei k passaggi, in ordine


def riga(domanda: Domanda, risultati: list[Risultato]) -> RigaCalibrazione:
    """Score delle fonti attese (chunk migliore, cioè quello che porta la fonte in classifica) e dei passaggi."""
    score_fonti: dict[int, float | None] = {}
    for fonte in domanda.fonti:
        della_fonte = [r.score for r in risultati if r.numero == fonte]
        score_fonti[fonte] = max(della_fonte) if della_fonte else None
    return RigaCalibrazione(domanda, score_fonti, [r.score for r in risultati])


# arrotondamento a 2 decimali per difetto o per eccesso; round(…, 6) toglie l'errore dei decimali (0.8 * 100)
def _per_difetto(x: float) -> float:
    return math.floor(round(x * 100, 6)) / 100


def _per_eccesso(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def soglie_proposte(righe: list[RigaCalibrazione]) -> tuple[float, float, float, float]:
    """(min_fonti, max_senza, alta, bassa) con il criterio approvato: nessuna fonte vera esclusa (bassa per difetto
    sotto la fonte più debole), passaggi delle domande senza risposta al massimo di affidabilità media (alta per
    eccesso sopra il più alto); se le fasce non si sovrappongono, alta = bassa."""
    fonti = [s for r in righe for s in r.score_fonti.values() if s is not None]
    senza = [s for r in righe if not r.domanda.fonti for s in r.score]
    # senza dati la regola non si applica: messaggio chiaro invece di un errore di min() o max()
    if not fonti:
        raise ErroreRicerca("calibrazione: nessuna fonte attesa trovata tra i primi k (aumentare -k o controllare "
                            "le domande con fonte)")
    if not senza:
        raise ErroreRicerca("calibrazione: nessuna domanda senza risposta tra le domande (servono per la soglia "
                            "alta)")
    min_fonti, max_senza = min(fonti), max(senza)
    bassa, alta = _per_difetto(min_fonti), _per_eccesso(max_senza)
    # la configurazione deve restare valida (bassa <= alta): senza sovrapposizione nessuna fascia media
    if bassa > alta:
        alta = bassa
    return min_fonti, max_senza, alta, bassa


# tipo di domanda per la tabella
def _tipo(domanda: Domanda) -> str:
    if not domanda.fonti:
        return "senza risposta"
    return "composta" if domanda.composta else "con risposta"


def tabella_calibrazione(righe: list[RigaCalibrazione], intestazione: dict[str, str]) -> str:
    """Parametri, una riga per domanda con gli score e il riepilogo con le soglie proposte (Markdown)."""
    testa = [f"- {chiave}: {valore}" for chiave, valore in intestazione.items()]
    tabella = ["| domanda | tipo | score delle fonti attese | score dei passaggi |", "|---|---|---|---|"]
    for r in righe:
        fonti = ", ".join(f"{f}: {s:.4f}" if s is not None else f"{f}: assente" for f, s in r.score_fonti.items())
        tabella.append(f"| {r.domanda.testo} | {_tipo(r.domanda)} | {fonti or '—'} | "
                       + ", ".join(f"{s:.4f}" for s in r.score) + " |")
    min_fonti, max_senza, alta, bassa = soglie_proposte(righe)
    riepilogo = [
        f"- score minimo di una fonte attesa (min_fonti): {min_fonti:.4f}",
        f"- score massimo di un passaggio delle domande senza risposta (max_senza): {max_senza:.4f}",
        f"- fasce sovrapposte: {'sì' if max_senza >= min_fonti else 'no'}",
        f"- soglia bassa proposta (min_fonti per difetto): {bassa:.2f}",
        f"- soglia alta proposta (max_senza per eccesso{', uguale alla bassa' if alta == bassa else ''}): {alta:.2f}",
    ]
    return "\n".join(testa) + "\n\n" + "\n".join(tabella) + "\n\n" + "\n".join(riepilogo)
