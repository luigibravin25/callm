"""Confronto delle quattro configurazioni del recupero (lezione 8, esercizio 3): metriche e tabelle Markdown."""
# librerie standard: classi di dati
from dataclasses import dataclass

from app.valutazione import Domanda

# configurazioni a confronto, nell'ordine delle colonne: un solo fattore cambiato tra una e l'altra
CONFIGURAZIONI = ("base", "riscrittura", "reranking", "entrambe")


# esito di una domanda in una configurazione
@dataclass(frozen=True)
class EsitoDomanda:
    domanda: Domanda
    numeri: list[int]  # numeri di ricetta dei passaggi restituiti, in ordine
    chiamate_llm: int  # chiamate al modello di chat
    latenza: float  # secondi della ricerca
    ripieghi: int  # ripieghi della ricerca


def posizione_fonte(e: EsitoDomanda) -> int | None:
    """Prima posizione (da 1) di una fonte attesa tra i passaggi; None se assente."""
    return next((i for i, n in enumerate(e.numeri, start=1) if n in e.domanda.fonti), None)


def copertura(e: EsitoDomanda) -> tuple[int, int]:
    """(fonti distinte trovate tra i passaggi, fonti attese)."""
    return len(set(e.domanda.fonti) & set(e.numeri)), len(e.domanda.fonti)


def astenuta(e: EsitoDomanda) -> bool:
    """Nessun passaggio restituito: il recupero si è astenuto."""
    return not e.numeri


# posizione per i confronti: assente = peggiore di ogni posizione
def _pos(e: EsitoDomanda) -> float:
    posizione = posizione_fonte(e)
    return posizione if posizione is not None else float("inf")


def confronto_con_base(base: EsitoDomanda, altro: EsitoDomanda) -> str:
    """"migliorata", "peggiorata" o "" rispetto a base (specifica §10)."""
    if not base.domanda.fonti:
        # senza risposta: astenersi è meglio che restituire passaggi
        if astenuta(altro) == astenuta(base):
            return ""
        return "migliorata" if astenuta(altro) else "peggiorata"
    # chiave da massimizzare: per le composte prima la copertura, poi la posizione; per le altre la posizione
    def chiave(e: EsitoDomanda) -> tuple:
        return (copertura(e)[0] if e.domanda.composta else 0, -_pos(e))
    if chiave(altro) > chiave(base):
        return "migliorata"
    if chiave(altro) < chiave(base):
        return "peggiorata"
    return ""


# media con una cifra decimale e massimo
def _media_max(valori: list[float], cifre: int) -> str:
    if not valori:
        return "—"
    massimo = max(valori)
    testo_max = f"{massimo:.{cifre}f}" if cifre > 1 else f"{massimo:g}"
    return f"{sum(valori) / len(valori):.{cifre}f}/{testo_max}"


def riepilogo(esiti: list[EsitoDomanda]) -> dict[str, str]:
    """Metriche di una configurazione sulle domande (chiavi nell'ordine della tabella riassuntiva)."""
    con_fonte = [e for e in esiti if e.domanda.fonti]
    senza_fonte = [e for e in esiti if not e.domanda.fonti]
    composte = [e for e in esiti if e.domanda.composta]
    trovate = [e for e in con_fonte if posizione_fonte(e) is not None]
    # MRR: media di 1/posizione della prima fonte attesa (0 se assente) sulle domande con fonte
    mrr = sum(1 / posizione_fonte(e) for e in trovate) / len(con_fonte) if con_fonte else 0.0
    return {
        "fonte nei primi k": f"{len(trovate)}/{len(con_fonte)}",
        "MRR": f"{mrr:.3f}",
        "copertura delle composte": f"{sum(copertura(e)[0] for e in composte)}/"
                                    f"{sum(copertura(e)[1] for e in composte)}",
        "astensioni corrette": f"{sum(astenuta(e) for e in senza_fonte)}/{len(senza_fonte)}",
        "astensioni errate": f"{sum(astenuta(e) for e in con_fonte)}/{len(con_fonte)}",
        "chiamate LLM (media/max)": _media_max([e.chiamate_llm for e in esiti], 1),
        "latenza s (media/max)": _media_max([e.latenza for e in esiti], 2),
        "ripieghi": str(sum(e.ripieghi for e in esiti)),
    }


# cella della tabella domanda per domanda (senza l'indicazione rispetto a base)
def _cella(e: EsitoDomanda) -> str:
    if astenuta(e):
        return "astensione"
    if not e.domanda.fonti:
        return f"{len(e.numeri)} passaggi"
    posizione = posizione_fonte(e)
    if e.domanda.composta:
        trovate, attese = copertura(e)
        return f"{trovate}/{attese} (pos. {posizione})" if posizione is not None else f"0/{attese}"
    return str(posizione) if posizione is not None else "assente"


def tabelle_markdown(esiti: dict[str, list[EsitoDomanda]], intestazione: dict[str, str]) -> str:
    """Parametri della prova, tabella riassuntiva e tabella domanda per domanda (da copiare in rag-agente.md)."""
    configurazioni = [c for c in CONFIGURAZIONI if c in esiti]
    testa = [f"- {chiave}: {valore}" for chiave, valore in intestazione.items()]
    # tabella riassuntiva: una riga per metrica, una colonna per configurazione
    riepiloghi = {c: riepilogo(esiti[c]) for c in configurazioni}
    metriche = list(next(iter(riepiloghi.values())).keys()) if riepiloghi else []
    riassunto = ["| metrica | " + " | ".join(configurazioni) + " |", "|---" * (len(configurazioni) + 1) + "|"]
    riassunto += [f"| {m} | " + " | ".join(riepiloghi[c][m] for c in configurazioni) + " |" for m in metriche]
    # tabella domanda per domanda: esito in ogni configurazione, con migliorata/peggiorata rispetto a base
    dettaglio = ["| domanda | " + " | ".join(configurazioni) + " |", "|---" * (len(configurazioni) + 1) + "|"]
    base = esiti.get("base", [])
    for i, e_base in enumerate(base):
        celle = [_cella(e_base)]
        for c in configurazioni[1:]:
            altro = esiti[c][i]
            esito = confronto_con_base(e_base, altro)
            celle.append(f"{_cella(altro)} {esito}".strip())
        dettaglio.append(f"| {e_base.domanda.testo} | " + " | ".join(celle) + " |")
    return "\n".join(testa) + "\n\n" + "\n".join(riassunto) + "\n\n" + "\n".join(dettaglio)
