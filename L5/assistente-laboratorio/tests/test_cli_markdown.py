"""CLI: niente Markdown nel terminale (grassetto ** ed elenchi con *), anche in streaming."""
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.cli import ETICHETTA_ASSISTENTE, FiltroMarkdown, main
from app.llm import SYSTEM_PROMPT


def _filtra(*pezzi):
    """Passa i pezzi al filtro come farebbe lo streaming e restituisce il testo finale."""
    f = FiltroMarkdown()
    return "".join(f.aggiungi(p) for p in pezzi) + f.fine()


@pytest.mark.parametrize("pezzi, atteso", [
    (["**ID 2:** consegnare il report"], "ID 2: consegnare il report"),
    (["Ecco le note:\n*   **ID 2:** report\n*   **ID 1:** latte"],
     "Ecco le note:\n- ID 2: report\n- ID 1: latte"),
    (["* prima\n* seconda"], "- prima\n- seconda"),
    # gli asterischi spezzati tra due pezzi dello streaming
    (["Nota *", "*ID 2*", "*: report"], "Nota ID 2: report"),
    (["Ecco:\n", "*", "   **ID 1:** latte"], "Ecco:\n- ID 1: latte"),
    # un asterisco singolo nel testo resta (es. una moltiplicazione)
    (["2*3 fa 6"], "2*3 fa 6"),
    (["finisce con *"], "finisce con *"),
])
def test_filtro_markdown(pezzi, atteso):
    assert _filtra(*pezzi) == atteso


class ModelloStream:
    """Modello finto in streaming: restituisce i pezzi di testo indicati."""

    def __init__(self, pezzi):
        self.pezzi = pezzi

    def stream(self, _messaggi):
        for p in self.pezzi:
            yield AIMessageChunk(content=p)

    def invoke(self, _messaggi):
        return AIMessage("".join(self.pezzi))


class AttesaMuta:
    def avvia(self):
        pass

    def ferma(self):
        pass


@pytest.mark.parametrize("stream", [True, False])
def test_main_senza_asterischi(stream):
    llm = ModelloStream(["Ecco:\n*", "   **ID 2", ":** report"])
    righe = iter(["quali note ho?", "exit"])
    token, uscite = [], []
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append, token_fn=token.append,
         llm=llm, stream=stream, attesa=AttesaMuta(), strumenti=[])
    testo = "".join(token) if stream else uscite[-1]
    assert "*" not in testo
    assert testo.replace(ETICHETTA_ASSISTENTE, "").strip() == "Ecco:\n- ID 2: report"


def test_system_prompt_testo_semplice():
    assert "senza asterischi" in SYSTEM_PROMPT and "trattino" in SYSTEM_PROMPT


# --- revisione finale: le potenze della calcolatrice (2**10) non sono grassetto ---

@pytest.mark.parametrize("pezzi, atteso", [
    (["2**10 = 1024"], "2**10 = 1024"),
    (["(1+2)**2 fa 9"], "(1+2)**2 fa 9"),
    (["2*", "*10 = 1024"], "2**10 = 1024"),  # spezzato nello streaming
    (["**Risultato:** 2**3 = 8"], "Risultato: 2**3 = 8"),
])
def test_potenze_non_toccate(pezzi, atteso):
    assert _filtra(*pezzi) == atteso


def test_elenchi_annidati():
    assert _filtra("Note:\n* prima\n  * dettaglio\n    *   altro") == \
        "Note:\n- prima\n  - dettaglio\n    - altro"
    assert _filtra("  * ", "voce") == "  - voce"
