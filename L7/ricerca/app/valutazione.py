"""Valutazione della ricerca sulle domande con fonte attesa: posizione e score della fonte (specifica, §11-12)."""
# librerie standard: lettura TOML, classi di dati, percorsi, tipi
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.indice import Risultato


# una domanda di valutazione: fonte attesa decisa prima (None = non è nel libro) e frase che il chunk
# della fonte deve contenere
@dataclass(frozen=True)
class Domanda:
    testo: str
    fonte: int | None
    indizio: str | None


# esito di una domanda: posizione, score e indizio del primo chunk della fonte tra i primi k
@dataclass(frozen=True)
class RigaValutazione:
    domanda: Domanda
    posizione: int | None  # None = fonte assente tra i primi k
    score: float | None
    contiene: bool | None  # None = fonte assente o domanda senza fonte
    primo: Risultato | None  # primo risultato della ricerca
    score_risultati: list[float]  # score di tutti i risultati (per la domanda senza fonte)


def leggi_domande(percorso: Path) -> list[Domanda]:
    """Domande dal file TOML: tabelle [[domanda]] con testo, fonte e indizio (ultimi due facoltativi)."""
    with percorso.open("rb") as file:
        dati = tomllib.load(file)
    return [Domanda(d["testo"], d.get("fonte"), d.get("indizio")) for d in dati["domanda"]]


def valuta(domande: list[Domanda], cerca: Callable[[str], list[Risultato]]) -> list[RigaValutazione]:
    """Una riga per domanda; con più chunk della fonte tra i primi k conta il primo."""
    righe: list[RigaValutazione] = []
    for domanda in domande:
        risultati = cerca(domanda.testo)
        fonte = next((r for r in risultati if r.numero == domanda.fonte), None) if domanda.fonte else None
        righe.append(RigaValutazione(
            domanda=domanda,
            posizione=fonte.posizione if fonte else None,
            score=fonte.score if fonte else None,
            # ricerca esatta dell'indizio, con le stesse maiuscole, nel chunk della fonte
            contiene=(domanda.indizio in fonte.testo) if fonte else None,
            primo=risultati[0] if risultati else None,
            score_risultati=[r.score for r in risultati],
        ))
    return righe


# score con 4 decimali
def _s(score: float) -> str:
    return f"{score:.4f}"


def tabella_markdown(righe: list[RigaValutazione], intestazione: dict[str, str]) -> str:
    """Parametri della prova e tabella Markdown (da copiare in docs/retrieval.md)."""
    testa = [f"- {chiave}: {valore}" for chiave, valore in intestazione.items()]
    tabella = ["| domanda | fonte attesa | posizione della fonte | score della fonte | il chunk contiene "
               "l'informazione | primo risultato |",
               "|---|---|---|---|---|---|"]
    for r in righe:
        primo = f"n. {r.primo.numero} «{r.primo.titolo}» {_s(r.primo.score)}" if r.primo else "—"
        if r.domanda.fonte is None:
            # domanda senza fonte: gli score dei k risultati
            celle = ["nessuna", "—", ", ".join(_s(s) for s in r.score_risultati) or "—", "—"]
        elif r.posizione is None:
            celle = [str(r.domanda.fonte), "assente", "—", "—"]
        else:
            celle = [str(r.domanda.fonte), str(r.posizione), _s(r.score), "sì" if r.contiene else "no"]
        tabella.append(f"| {r.domanda.testo} | " + " | ".join(celle) + f" | {primo} |")
    return "\n".join(testa) + "\n\n" + "\n".join(tabella)
