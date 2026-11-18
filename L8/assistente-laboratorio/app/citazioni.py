"""Controllo delle citazioni (lezione 8, esercizio 2): funzioni pure, senza grafo né log.

Id citati = gli id `R<numero>-<chunk>` scritti tra parentesi quadre nella risposta del modello.
Id ricevuti = gli id dei passaggi restituiti da search_documents nel turno (risultato JSON dell'esercizio 1).
"""
# librerie standard: JSON, espressioni regolari, classi di dati
import json
import re
from dataclasses import dataclass

# messaggi della conversazione (i risultati degli strumenti sono ToolMessage)
from langchain_core.messages import BaseMessage, ToolMessage

# nome del tool del server di ricerca
NOME_RICERCA = "search_documents"
# un gruppo tra parentesi quadre (senza parentesi annidate) e, dentro, un id citabile
GRUPPO = re.compile(r"\[([^\[\]]*)\]")
ID_CITABILE = re.compile(r"R\d+-\d+")


# esito del controllo di un turno: cosa è stato citato, cosa no, quante ricerche e quanti passaggi
@dataclass(frozen=True)
class EsitoCitazioni:
    verificate: tuple[str, ...]  # citati e ricevuti nel turno
    sconosciute: tuple[str, ...]  # citati ma non ricevuti nel turno
    ricerche: int  # chiamate eseguite a search_documents nel turno
    passaggi: int  # id ricevuti distinti


# elenco senza doppi che mantiene l'ordine di comparsa
def _senza_doppi(valori: list[str]) -> list[str]:
    return list(dict.fromkeys(valori))


def id_citati(testo: str) -> list[str]:
    """Id tra parentesi quadre nel testo (anche più id nello stesso gruppo), in ordine e senza doppi."""
    return _senza_doppi([i for gruppo in GRUPPO.findall(testo) for i in ID_CITABILE.findall(gruppo)])


def id_ricevuti(contenuto: str) -> list[str]:
    """Id dei passaggi nel risultato JSON di search_documents; testo non JSON o senza passaggi → nessuno."""
    try:
        dati = json.loads(contenuto)
    except (json.JSONDecodeError, TypeError):
        return []
    # un JSON diverso dal risultato atteso non porta id
    passaggi = dati.get("passaggi") if isinstance(dati, dict) else None
    if not isinstance(passaggi, list):
        return []
    return [p["id"] for p in passaggi if isinstance(p, dict) and isinstance(p.get("id"), str)]


def controlla(turno: list[BaseMessage], risposta: str) -> EsitoCitazioni:
    """`turno`: messaggi dopo l'ultima domanda, già senza le chiamate non eseguite; `risposta`: testo finale."""
    # risultati della ricerca nel turno (anche quelli in errore: contano come ricerche)
    ricerche = [m for m in turno if isinstance(m, ToolMessage) and m.name == NOME_RICERCA]
    # id ricevuti solo dai risultati riusciti
    ricevuti = _senza_doppi([i for m in ricerche if m.status != "error" for i in id_ricevuti(str(m.content))])
    citati = id_citati(risposta)
    return EsitoCitazioni(verificate=tuple(i for i in citati if i in ricevuti),
                          sconosciute=tuple(i for i in citati if i not in ricevuti),
                          ricerche=len(ricerche), passaggi=len(ricevuti))


def riga_log(esito: EsitoCitazioni) -> str:
    """Testo della riga [citazioni]: elenchi separati da virgole, «-» se vuoti."""
    return (f"verificate={','.join(esito.verificate) or '-'} sconosciute={','.join(esito.sconosciute) or '-'} "
            f"ricerche={esito.ricerche} passaggi={esito.passaggi}")
