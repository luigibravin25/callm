"""Server MCP delle note (FastMCP, trasporto stdio), archivio SQLite (archivio.py).

Avvio: python -m mcp_note.server  (di solito lo avvia l'adattatore, all'avvio di app.cli).
Archivio: variabile NOTE_DB, altrimenti assistente-laboratorio/dati/note.sqlite.
Su stdout passa solo il protocollo MCP; il log di ogni modifica va su stderr.
"""
import json
import sys
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BeforeValidator

from mcp_note.archivio import (LIMIT_PREDEFINITO, MAX_LIMIT, ErroreNote, aggiungi, elenca,
                               elimina)

mcp = FastMCP("note")


def _niente_booleani(nome: str):
    def controlla(valore):
        # la validazione di FastMCP convertirebbe True in 1
        if isinstance(valore, bool):
            raise ValueError(f"{nome} deve essere un numero intero, ricevuto {valore!r}.")
        return valore
    return BeforeValidator(controlla)


# nello schema restano {"type": "integer"} (niente anyOf, per il template di gemma)
Limite = Annotated[int, _niente_booleani("limit")]
IdNota = Annotated[int, _niente_booleani("note_id")]


def _log(testo: str) -> None:
    # log di ogni modifica, sempre visibile (non dipende da FASTMCP_LOG_LEVEL)
    print(f"[note] {testo}", file=sys.stderr, flush=True)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                      idempotentHint=False))
def add_note(text: str) -> str:
    """Crea una nota PERMANENTE (resta salvata anche dopo il riavvio) con il testo da ricordare.

    Cosa cambia: aggiunge una nota all'archivio e restituisce il suo ID e la data di creazione.
    Chiamalo UNA SOLA VOLTA per richiesta (es. "ricordami di consegnare il report venerdi'":
    text = "consegnare il report venerdi'"). Testo da 1 a 500 caratteri.
    Come verificarlo: list_notes mostra la nota con lo stesso ID.
    """
    try:
        nota = aggiungi(text)
    except ErroreNote as e:
        raise ToolError(str(e)) from None
    _log(f"creata nota {nota['id']}: {nota['testo']}")
    return f"Nota {nota['id']} creata il {nota['creata']}: {nota['testo']}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_notes(limit: Limite = LIMIT_PREDEFINITO) -> str:
    """Elenca le note salvate, dalla piu' recente alla piu' vecchia. Non modifica nulla.

    Restituisce "Note:" seguito da una lista JSON con id, testo e data di creazione, oppure
    "Nessuna nota salvata.". limit: da 1 a 50 (predefinito 10). Se dopo la lista c'e' la riga
    "Mostrate N di M note", le note sono di piu': richiama con il limit indicato.
    Rispondi all'utente con una frase, non ripetere il JSON.
    """
    try:
        note, totale = elenca(limit)
    except ErroreNote as e:
        raise ToolError(str(e)) from None
    if not note:
        return "Nessuna nota salvata."
    # testo davanti alla lista: con una lista JSON pura gemma ripeteva il risultato grezzo
    testo = "Note: " + json.dumps(note, ensure_ascii=False)
    if totale > len(note):
        if totale <= MAX_LIMIT:
            testo += (f"\nMostrate {len(note)} di {totale} note: richiama list_notes con "
                      f"limit={totale} per vederle tutte.")
        else:
            testo += f"\nMostrate {len(note)} di {totale} note: le più vecchie non sono mostrate."
    return testo


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                      idempotentHint=True))
def delete_note(note_id: IdNota) -> str:
    """Elimina DEFINITIVAMENTE una nota, indicata dal suo ID (numero intero).

    Cosa cambia: la nota viene cancellata dall'archivio e non si puo' recuperare. Prima di
    eseguirlo il programma chiede conferma all'utente: se l'utente rifiuta, nulla viene
    eliminato. Non indovinare l'ID: se l'utente non lo dice in modo chiaro, usa prima list_notes.
    Un ID inesistente da' errore e non elimina nulla.
    Come verificarlo: dopo l'eliminazione list_notes non mostra piu' la nota.
    """
    try:
        nota = elimina(note_id)
    except ErroreNote as e:
        raise ToolError(str(e)) from None
    _log(f"eliminata nota {nota['id']}: {nota['testo']}")
    return f"Nota {nota['id']} eliminata: {nota['testo']} (creata il {nota['creata']})."


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
