"""CLI: domanda di conferma da terminale prima di un tool distruttivo, prompt delle note."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from app.cli import domanda_conferma, main, risposta_affermativa
from app.llm import SYSTEM_PROMPT


class AttesaMuta:
    """Animazione d'attesa finta: registra quando viene fermata."""

    def __init__(self):
        self.fermate = 0

    def avvia(self):
        pass

    def ferma(self):
        self.fermate += 1


class ModelloCopione:
    """Modello finto: restituisce i messaggi in ordine (poi ripete l'ultimo)."""

    def __init__(self, messaggi):
        self.messaggi = list(messaggi)

    def invoke(self, _messaggi):
        if len(self.messaggi) > 1:
            return self.messaggi.pop(0)
        return self.messaggi[0].model_copy(update={"id": None})


def _elenco(testo_lista):
    """Tool list_notes finto che restituisce sempre `testo_lista`."""
    def list_notes(limit: int = 10) -> str:
        """finto"""
        return testo_lista
    return StructuredTool.from_function(list_notes, metadata={"readOnlyHint": True})


def _cancella(registro):
    """Tool delete_note finto, distruttivo, che registra gli ID eliminati."""
    def delete_note(note_id: int) -> str:
        """finto"""
        registro.append(note_id)
        return f"Nota {note_id} eliminata"
    return StructuredTool.from_function(delete_note, metadata={"destructiveHint": True})


ELENCO = 'Note: [{"id": 3, "testo": "report", "creata": "2026-11-05 10:00:00"}]'


@pytest.mark.parametrize("testo, atteso", [
    ("s", True), (" S ", True), ("si", True), ("Sì", True),
    ("n", False), ("", False), ("si grazie", False), ("no", False),
])
def test_risposta_affermativa(testo, atteso):
    assert risposta_affermativa(testo) is atteso


def test_domanda_con_testo_della_nota():
    strumenti = [_elenco(ELENCO)]
    assert domanda_conferma("delete_note", {"note_id": 3}, strumenti) == \
        'Eliminare la nota 3 "report"? (s/n) '
    assert domanda_conferma("delete_note", {"note_id": "3"}, strumenti) == \
        'Eliminare la nota 3 "report"? (s/n) '


def test_domanda_nota_assente_solo_id():
    assert domanda_conferma("delete_note", {"note_id": 99}, [_elenco(ELENCO)]) == \
        "Eliminare la nota 99? (s/n) "


def test_domanda_elenco_in_errore_solo_id():
    def list_notes(limit: int = 10) -> str:
        """finto"""
        raise RuntimeError("archivio rotto")
    rotto = StructuredTool.from_function(list_notes)
    assert domanda_conferma("delete_note", {"note_id": 3}, [rotto]) == \
        "Eliminare la nota 3? (s/n) "


def test_domanda_altro_tool_distruttivo():
    assert domanda_conferma("svuota", {"tutto": True}, []) == \
        "Eseguire svuota con {'tutto': True}? (s/n) "


def _sessione(risposte, registro):
    """Una sessione della CLI: il modello chiede delete_note(3), poi risponde "fatto"."""
    llm = ModelloCopione([
        AIMessage("", tool_calls=[{"name": "delete_note", "args": {"note_id": 3}, "id": "c1"}]),
        AIMessage("fatto"),
    ])
    righe = iter(risposte)
    domande = []

    def input_fn(prompt=""):
        domande.append(prompt)
        valore = next(righe)
        if isinstance(valore, BaseException):
            raise valore
        return valore

    attesa = AttesaMuta()
    main(input_fn=input_fn, output_fn=lambda _t: None, llm=llm, stream=False,
         attesa=attesa, strumenti=[_elenco(ELENCO), _cancella(registro)])
    return domande, attesa


def test_main_chiede_conferma_e_annulla_con_n():
    registro = []
    domande, attesa = _sessione(["elimina la nota 3", "n", "exit"], registro)
    assert 'Eliminare la nota 3 "report"? (s/n) ' in domande
    assert registro == []
    assert attesa.fermate >= 1  # l'animazione si ferma prima della domanda


def test_main_elimina_con_s():
    registro = []
    _sessione(["elimina la nota 3", "s", "exit"], registro)
    assert registro == [3]


def test_eof_durante_la_conferma_annulla():
    registro = []
    _sessione(["elimina la nota 3", EOFError(), "exit"], registro)
    assert registro == []


def test_system_prompt_regole_note():
    assert "chiama tooltime senza l'argomento fuso" in SYSTEM_PROMPT
    for parte in ("add_note una sola volta", "delete_note", "chiede conferma", "list_notes"):
        assert parte in SYSTEM_PROMPT, parte


def test_system_prompt_niente_nomi_degli_strumenti():
    # l'utente non deve leggere "list_notes": l'assistente parla in modo naturale e, se non sa
    # l'ID, legge lui l'elenco e chiede quale nota eliminare
    assert "Non nominare mai all'utente i nomi degli strumenti" in SYSTEM_PROMPT
    assert "leggi tu l'elenco" in SYSTEM_PROMPT


def test_animazione_riparte_dopo_un_annullamento():
    # dopo un'eliminazione annullata il modello ragiona di nuovo: l'attesa deve ripartire
    class AttesaContata(AttesaMuta):
        def __init__(self):
            super().__init__()
            self.avvii = 0

        def avvia(self):
            self.avvii += 1

    llm = ModelloCopione([
        AIMessage("", tool_calls=[{"name": "delete_note", "args": {"note_id": 3}, "id": "c1"}]),
        AIMessage("annullato"),
    ])
    righe = iter(["elimina la nota 3", "n", "exit"])
    attesa = AttesaContata()
    main(input_fn=lambda _p="": next(righe), output_fn=lambda _t: None, llm=llm, stream=False,
         attesa=attesa, strumenti=[_elenco(ELENCO), _cancella([])])
    assert attesa.avvii == 2  # all'inizio della domanda e dopo il risultato annullato
