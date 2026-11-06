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


@pytest.mark.parametrize("testo", [
    # le risposte brevi di prima
    "s", " S ", "si", "Sì",
    # risposte naturali concordate con l'utente il 2026-11-06 (maiuscole, spazi e
    # punteggiatura finale non contano)
    "ok", "Okay!", "certo", "Va bene.", "d'accordo", "vai", "procedi", "conferma", "confermo",
    "elimina", "elimina pure", "cancella", "Cancella pure", "esatto",
    # le stesse precedute da "sì"
    "sì vai", "Sì, certo", "si elimina", "si grazie", "sì, va bene", "Sì, elimina pure!"])
def test_risposta_affermativa_si(testo):
    """Frasi intere che valgono sì: solo queste cancellano la nota."""
    assert risposta_affermativa(testo) is True


@pytest.mark.parametrize("testo", [
    "n", "", "no", "No grazie", "non ora", "annulla", "lascia stare", "forse",
    # un sì insieme a un dubbio o a un rifiuto vale no
    "sì ma aspetta", "si, anzi no", "ok ma non quella", "certo che no",
    # frasi lunghe o altro testo: in caso di dubbio non si cancella
    "sì quella di ieri", "elimina la 5", "grazie", "sisi"])
def test_risposta_affermativa_no(testo):
    """Tutto il resto vale no."""
    assert risposta_affermativa(testo) is False


def test_domanda_con_testo_della_nota():
    """La domanda e' colloquiale: la dice l'assistente, con numero e testo veri della nota."""
    strumenti = [_elenco(ELENCO)]
    attesa = 'Vuoi che elimini la nota 3 "report"? Rispondimi sì o no.'
    assert domanda_conferma("delete_note", {"note_id": 3}, strumenti) == attesa
    assert domanda_conferma("delete_note", {"note_id": "3"}, strumenti) == attesa


def test_domanda_nota_assente_solo_id():
    assert domanda_conferma("delete_note", {"note_id": 99}, [_elenco(ELENCO)]) == \
        "Vuoi che elimini la nota 99? Rispondimi sì o no."


def test_domanda_elenco_in_errore_solo_id():
    def list_notes(limit: int = 10) -> str:
        """finto"""
        raise RuntimeError("archivio rotto")
    rotto = StructuredTool.from_function(list_notes)
    assert domanda_conferma("delete_note", {"note_id": 3}, [rotto]) == \
        "Vuoi che elimini la nota 3? Rispondimi sì o no."


def test_domanda_altro_tool_distruttivo():
    assert domanda_conferma("svuota", {"tutto": True}, []) == \
        "Vuoi che esegua svuota con {'tutto': True}? Rispondimi sì o no."


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
    uscite = []  # righe scritte con output_fn (la domanda dell'assistente)
    main(input_fn=input_fn, output_fn=uscite.append, llm=llm, stream=False,
         attesa=attesa, strumenti=[_elenco(ELENCO), _cancella(registro)])
    return domande, attesa, uscite


def test_main_chiede_conferma_e_annulla_con_n():
    registro = []
    domande, attesa, uscite = _sessione(["elimina la nota 3", "n", "exit"], registro)
    # la domanda la dice l'assistente; la risposta si scrive alla solita riga "Tu: "
    assert 'Assistente: Vuoi che elimini la nota 3 "report"? Rispondimi sì o no.' in uscite
    assert domande.count("Tu: ") == 3  # domanda, risposta alla conferma, exit
    assert registro == []
    assert attesa.fermate >= 1  # l'animazione si ferma prima della domanda


def test_main_elimina_con_risposta_naturale():
    registro = []
    _sessione(["elimina la nota 3", "Sì, elimina pure!", "exit"], registro)
    assert registro == [3]


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


def _turno_in_streaming(testo_prima: str, risposta: str) -> str:
    """Una domanda in streaming: il modello scrive `testo_prima` (anche vuoto), chiama
    delete_note(3), l'utente risponde `risposta`; restituisce tutto il testo del terminale."""
    from langchain_core.messages import AIMessageChunk

    from tests.test_streaming import ModelloStream, _pezzi

    # primo turno del modello: testo facoltativo e poi la chiamata a delete_note
    chiamata = ([AIMessageChunk(content=testo_prima)] if testo_prima else []) + [
        AIMessageChunk(content="", tool_call_chunks=[
            {"name": "delete_note", "args": '{"note_id": 3}', "id": "c1", "index": 0}])]
    llm = ModelloStream([chiamata, _pezzi("Fatto: nota 3 ", "eliminata.")])
    scritti = []  # tutto quello che finisce nel terminale, in ordine
    righe = iter(["elimina la nota 3", risposta, "exit"])

    def input_fn(prompt=""):
        scritti.append(prompt + "<invio>\n")  # la domanda e l'invio dell'utente
        return next(righe)

    # output_fn come print: ogni riga finisce con un a capo
    main(input_fn=input_fn, output_fn=lambda t: scritti.append(t + "\n"),
         token_fn=scritti.append, llm=llm, stream=True, attesa=AttesaMuta(),
         strumenti=[_elenco(ELENCO), _cancella([])])
    return "".join(scritti)


DOMANDA = 'Assistente: Vuoi che elimini la nota 3 "report"? Rispondimi sì o no.\n'


def test_dopo_la_conferma_nuova_riga_assistente():
    """Come in una chat: il testo scritto prima della domanda resta, la domanda la dice
    l'assistente, l'utente risponde a "Tu: " e il modello riparte con "Assistente: "."""
    testo = _turno_in_streaming("Certo, elimino la nota.", "sì vai")
    assert ('Assistente: Certo, elimino la nota.\n' + DOMANDA + 'Tu: <invio>\n'
            'Assistente: Fatto: nota 3 eliminata.\n') in testo


def test_conferma_senza_testo_prima():
    """Senza testo prima della chiamata: domanda dell'assistente, risposta, poi la risposta
    del modello con la sua etichetta."""
    testo = _turno_in_streaming("", "s")
    assert (DOMANDA + 'Tu: <invio>\nAssistente: Fatto: nota 3 eliminata.\n') in testo
    assert testo.count("Assistente: ") == 2  # la domanda e la risposta del modello
