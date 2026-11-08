"""Grafo: conferma per i tool distruttivi (destructiveHint) e blocco dei doppioni di add_note."""
# pytest, messaggi e strumenti di LangChain (ToolException = errore restituito al modello)
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException

# il grafo e i messaggi che manda al modello quando blocca una chiamata
from app.graph import MSG_ANNULLATA, MSG_DOPPIONE, MSG_RIPETUTA, build_graph


# modello finto: risposte gia' scritte, in ordine (poi ripete l'ultima)
class ModelloCopione:
    def __init__(self, messaggi):
        self.messaggi = list(messaggi)

    def invoke(self, _messaggi):
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)
        return self.messaggi[0].model_copy(update={"id": None})


# registra cosa hanno fatto davvero gli strumenti finti: note aggiunte, ID eliminati, letture
@pytest.fixture
def registro():
    return {"add": [], "delete": [], "list": 0}


# i tre tool delle note in versione finta, con le stesse annotazioni dei veri
@pytest.fixture
def strumenti(registro):
    # add_note: errore per un testo vuoto, come il server vero
    def add_note(text: str) -> str:
        """finto"""
        if not text.strip():
            raise ToolException("Il testo della nota è vuoto: scrivi che cosa ricordare.")
        registro["add"].append(text)
        return f"Nota {len(registro['add'])} creata"

    def delete_note(note_id: int) -> str:
        """finto"""
        registro["delete"].append(note_id)
        return f"Nota {note_id} eliminata"

    def list_notes(limit: int = 10) -> str:
        """finto"""
        registro["list"] += 1
        return "Nessuna nota salvata."

    # handle_tool_error=True: la ToolException diventa un ToolMessage d'errore
    return [
        StructuredTool.from_function(add_note, handle_tool_error=True,
                                     metadata={"destructiveHint": False}),
        StructuredTool.from_function(delete_note, handle_tool_error=True,
                                     metadata={"destructiveHint": True}),
        StructuredTool.from_function(list_notes, metadata={"readOnlyHint": True}),
    ]


# una risposta del modello con una o piu' tool call (id c0, c1, ...)
def _chiamate(*coppie):
    return AIMessage("", tool_calls=[{"name": n, "args": a, "id": f"c{i}"}
                                     for i, (n, a) in enumerate(coppie)])


# esegue il grafo su una domanda con il copione dato; conferma e' la funzione che decide
# (None = nessuna funzione di conferma); cronologia = messaggi delle domande precedenti
def _esegui(strumenti, copione, conferma=None, cronologia=None):
    grafo = build_graph(ModelloCopione(copione), strumenti=strumenti, conferma=conferma)
    messaggi = (cronologia or []) + [HumanMessage("domanda")]
    return grafo.invoke({"messages": messaggi, "steps": 0})


# i risultati degli strumenti nella conversazione finale
def _risultati(out):
    return [m for m in out["messages"] if isinstance(m, ToolMessage)]


# conferma data: delete_note viene eseguito
def test_conferma_vera_esegue(strumenti, registro):
    _esegui(strumenti, [_chiamate(("delete_note", {"note_id": 3})), AIMessage("ok")],
            conferma=lambda nome, argomenti: True)
    assert registro["delete"] == [3]


# conferma negata: niente cancellazione e il modello riceve MSG_ANNULLATA come errore
def test_conferma_falsa_annulla(strumenti, registro):
    out = _esegui(strumenti, [_chiamate(("delete_note", {"note_id": 3})), AIMessage("ok")],
                  conferma=lambda nome, argomenti: False)
    assert registro["delete"] == []
    risultato = _risultati(out)[0]
    assert risultato.content == MSG_ANNULLATA and risultato.status == "error"


# senza una funzione di conferma un tool distruttivo non si esegue mai (scelta prudente)
def test_senza_conferma_annulla(strumenti, registro):
    out = _esegui(strumenti, [_chiamate(("delete_note", {"note_id": 3})), AIMessage("ok")])
    assert registro["delete"] == [] and _risultati(out)[0].content == MSG_ANNULLATA


# add_note e list_notes non sono distruttivi: si eseguono senza chiedere nulla
def test_tool_non_distruttivi_senza_conferma(strumenti, registro):
    chiesto = []  # chiamate alla funzione di conferma: deve restare vuota
    _esegui(strumenti, [_chiamate(("add_note", {"text": "a"}), ("list_notes", {})),
                        AIMessage("ok")],
            conferma=lambda *a: chiesto.append(a) or True)
    assert chiesto == [] and registro["add"] == ["a"] and registro["list"] == 1


# la funzione di conferma riceve nome e argomenti: servono a scrivere la domanda
def test_conferma_riceve_nome_e_argomenti(strumenti):
    chiesto = []
    _esegui(strumenti, [_chiamate(("delete_note", {"note_id": 3})), AIMessage("ok")],
            conferma=lambda nome, argomenti: chiesto.append((nome, argomenti)) or False)
    assert chiesto == [("delete_note", {"note_id": 3})]


# nella stessa risposta: delete annullato, add eseguito; risultati nell'ordine delle chiamate
def test_add_e_delete_nella_stessa_risposta(strumenti, registro):
    out = _esegui(strumenti, [_chiamate(("delete_note", {"note_id": 1}),
                                        ("add_note", {"text": "nuova"})), AIMessage("ok")],
                  conferma=lambda *a: False)
    assert registro["add"] == ["nuova"] and registro["delete"] == []
    risultati = _risultati(out)
    assert [m.tool_call_id for m in risultati] == ["c0", "c1"]  # ogni risultato alla sua call
    assert risultati[0].content == MSG_ANNULLATA and risultati[1].content == "Nota 1 creata"


# il modello ripete add_note con lo stesso testo (maiuscole e spazi diversi): una sola nota
def test_doppione_in_due_risposte_della_stessa_domanda(strumenti, registro):
    out = _esegui(strumenti, [_chiamate(("add_note", {"text": "Consegnare il report"})),
                              _chiamate(("add_note", {"text": " consegnare il report "})),
                              AIMessage("ok")])
    assert registro["add"] == ["Consegnare il report"]
    # il secondo tentativo riceve MSG_DOPPIONE come errore
    secondo = _risultati(out)[1]
    assert secondo.content == MSG_DOPPIONE and secondo.status == "error"


# due add_note uguali nella stessa risposta: una sola nota
def test_doppione_nella_stessa_risposta(strumenti, registro):
    _esegui(strumenti, [_chiamate(("add_note", {"text": "x"}), ("add_note", {"text": "x"})),
                        AIMessage("ok")])
    assert registro["add"] == ["x"]


# testi diversi non sono doppioni: due note
def test_testi_diversi_due_note(strumenti, registro):
    _esegui(strumenti, [_chiamate(("add_note", {"text": "A"}), ("add_note", {"text": "B"})),
                        AIMessage("ok")])
    assert registro["add"] == ["A", "B"]


# il blocco vale solo dentro una domanda: chiedere due volte la stessa nota ne crea due
def test_stesso_testo_in_due_domande_due_note(strumenti, registro):
    prima = _esegui(strumenti, [_chiamate(("add_note", {"text": "x"})), AIMessage("ok")])
    # seconda domanda con la cronologia della prima
    _esegui(strumenti, [_chiamate(("add_note", {"text": "x"})), AIMessage("ok")],
            cronologia=prima["messages"])
    assert registro["add"] == ["x", "x"]


# una add_note fallita (testo vuoto) non conta come gia' salvata: si puo' riprovare
def test_add_fallita_non_conta(strumenti, registro):
    _esegui(strumenti, [_chiamate(("add_note", {"text": "  "})),
                        _chiamate(("add_note", {"text": "  "})),
                        _chiamate(("add_note", {"text": "x"})), AIMessage("ok")])
    assert registro["add"] == ["x"]  # solo la nota valida e' stata salvata


# delete_note e' riconosciuto per nome anche se manca l'annotazione destructiveHint
def test_delete_note_chiede_conferma_anche_senza_annotazione(registro):
    # difesa in profondita': se l'annotazione MCP destructiveHint andasse persa
    # (aggiornamento della libreria), delete_note deve chiedere conferma lo stesso
    def delete_note(note_id: int) -> str:
        """finto, senza metadata"""
        registro["delete"].append(note_id)
        return "eliminata"
    senza_metadata = StructuredTool.from_function(delete_note)
    # nessuna funzione di conferma: se il grafo chiede conferma, la cancellazione e' annullata
    out = _esegui([senza_metadata], [_chiamate(("delete_note", {"note_id": 3})),
                                      AIMessage("ok")])
    assert registro["delete"] == [] and _risultati(out)[0].content == MSG_ANNULLATA


# messaggio giusto per una chiamata ripetuta quando la prima e' fallita: MSG_RIPETUTA
def test_ripetuta_nella_stessa_risposta_con_prima_fallita(strumenti, registro):
    # due add_note uguali nella stessa risposta e la prima fallisce: la seconda non deve dire
    # "gia' salvata" (sarebbe falso), ma che la chiamata era ripetuta
    out = _esegui(strumenti, [_chiamate(("add_note", {"text": "  "}), ("add_note", {"text": "  "})),
                              AIMessage("ok")])
    secondo = _risultati(out)[1]
    assert secondo.content == MSG_RIPETUTA and "salvata" not in secondo.content
    assert registro["add"] == []
