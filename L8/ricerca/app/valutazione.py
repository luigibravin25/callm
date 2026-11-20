"""Valutazione della ricerca sulle domande con fonte attesa: posizione e score della fonte (specifica, §11-12)."""
# librerie standard: lettura TOML, classi di dati, percorsi, tipi
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.errori import ErroreRicerca
from app.indice import Risultato

# nome del file nei messaggi di errore
DOMANDE_FILE = "domande.toml"


# una domanda di valutazione: fonti attese decise prima (vuote = non è nel libro) e, per ogni fonte, la frase
# che il suo chunk deve contenere; più fonti = domanda composta (lezione 8, esercizio 3)
@dataclass(frozen=True)
class Domanda:
    testo: str
    fonti: tuple[int, ...]
    indizi: tuple[str, ...]

    @property
    def composta(self) -> bool:
        """Domanda che chiede più cose, con una fonte per parte."""
        return len(self.fonti) > 1


# esito di una domanda: posizione, score e indizio del primo chunk della fonte tra i primi k
@dataclass(frozen=True)
class RigaValutazione:
    domanda: Domanda
    posizione: int | None  # None = fonte assente tra i primi k
    score: float | None
    contiene: bool | None  # None = fonte assente o domanda senza fonte
    primo: Risultato | None  # primo risultato della ricerca
    score_risultati: list[float]  # score di tutti i risultati (per la domanda senza fonte)


# una tabella [[domanda]] controllata: errore con il numero della domanda (1..n) invece di una traceback
def _domanda(numero: int, dati: dict) -> Domanda:
    testo = dati.get("testo")
    if not isinstance(testo, str) or not testo.strip():
        raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero} senza testo")
    singola = "fonte" in dati or "indizio" in dati
    multipla = "fonti" in dati or "indizi" in dati
    # le due forme non si mescolano
    if singola and multipla:
        raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero}: usare fonte/indizio oppure fonti/indizi, non "
                            "entrambe le forme")
    if multipla:
        fonti, indizi = dati.get("fonti"), dati.get("indizi")
        # liste non vuote e della stessa lunghezza: un indizio per ogni fonte
        if (not isinstance(fonti, list) or not isinstance(indizi, list) or not fonti
                or len(fonti) != len(indizi)):
            raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero}: fonti e indizi vanno indicati come liste non "
                                "vuote della stessa lunghezza")
    else:
        fonte, indizio = dati.get("fonte"), dati.get("indizio")
        # fonte e indizio vanno insieme (domanda con fonte attesa) oppure mancano entrambi (es. tiramisù)
        if (fonte is None) != (indizio is None):
            raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero}: fonte e indizio vanno indicati insieme")
        fonti, indizi = ([fonte], [indizio]) if fonte is not None else ([], [])
    # ogni fonte è il numero di una ricetta, ogni indizio un testo non vuoto
    for fonte in fonti:
        if not isinstance(fonte, int) or isinstance(fonte, bool):
            raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero}: fonte deve essere il numero della ricetta")
    for indizio in indizi:
        if not isinstance(indizio, str) or not indizio:
            raise ErroreRicerca(f"{DOMANDE_FILE}: domanda {numero}: indizio deve essere un testo non vuoto")
    return Domanda(testo, tuple(fonti), tuple(indizi))


def leggi_domande(percorso: Path) -> list[Domanda]:
    """Domande dal file TOML: tabelle [[domanda]] con testo e, facoltativi, fonte e indizio (una fonte) oppure
    fonti e indizi (domanda composta)."""
    try:
        with percorso.open("rb") as file:
            dati = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as errore:
        raise ErroreRicerca(f"{DOMANDE_FILE}: file non leggibile ({errore})") from errore
    domande = dati.get("domanda")
    if not isinstance(domande, list) or not domande:
        raise ErroreRicerca(f"{DOMANDE_FILE}: nessuna tabella [[domanda]]")
    return [_domanda(i, d) for i, d in enumerate(domande, start=1)]


def intestazione_valutazione(registrazione: dict, collezione: str, punti: int, k: int,
                             solo_dosi: bool) -> dict[str, str]:
    """Parametri della prova: chunking e testo indicizzato dalla collezione, non dalla configurazione."""
    return {
        "modello": str(registrazione.get("modello_embedding", "non registrato")),
        "collezione": collezione,
        "punti": str(punti),
        "chunking": str(registrazione.get("chunking") or "non registrato"),
        "testo indicizzato": str(registrazione.get("testo_indicizzato") or "non registrato"),
        "k": str(k),
        "filtro": "solo chunk con dosi" if solo_dosi else "nessuno",
    }


def valuta(domande: list[Domanda], cerca: Callable[[str], list[Risultato]]) -> list[RigaValutazione]:
    """Una riga per domanda; con più chunk delle fonti tra i primi k conta il primo."""
    righe: list[RigaValutazione] = []
    for domanda in domande:
        risultati = cerca(domanda.testo)
        # primo chunk di una qualsiasi delle fonti attese (per una composta: la prima fonte trovata)
        fonte = next((r for r in risultati if r.numero in domanda.fonti), None)
        righe.append(RigaValutazione(
            domanda=domanda,
            posizione=fonte.posizione if fonte else None,
            score=fonte.score if fonte else None,
            # ricerca esatta dell'indizio, con le stesse maiuscole, nel chunk della fonte
            contiene=(domanda.indizi[domanda.fonti.index(fonte.numero)] in fonte.testo) if fonte else None,
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
        # fonti attese separate da virgola (più di una per le composte)
        attese = ", ".join(str(f) for f in r.domanda.fonti)
        if not r.domanda.fonti:
            # domanda senza fonte: gli score dei k risultati
            celle = ["nessuna", "—", ", ".join(_s(s) for s in r.score_risultati) or "—", "—"]
        elif r.posizione is None:
            celle = [attese, "assente", "—", "—"]
        else:
            celle = [attese, str(r.posizione), _s(r.score), "sì" if r.contiene else "no"]
        tabella.append(f"| {r.domanda.testo} | " + " | ".join(celle) + f" | {primo} |")
    return "\n".join(testa) + "\n\n" + "\n".join(tabella)
