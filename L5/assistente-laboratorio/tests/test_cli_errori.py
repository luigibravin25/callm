"""Errori generici di LM Studio (openai.APIError) durante una domanda: messaggio e sessione viva."""
import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from openai import APIError

from app.cli import ETICHETTA_ASSISTENTE, main


class AttesaMuta:
    def avvia(self):
        pass

    def ferma(self):
        pass


def _errore_contesto():
    return APIError("Context size has been exceeded.", httpx.Request("POST", "http://x"),
                    body=None)


class LlmContestoPieno:
    """Prima domanda: errore di contesto (dopo un token, come nello streaming); poi risponde."""

    def __init__(self):
        self.ricevuti = []

    def stream(self, messaggi):
        self.ricevuti.append(list(messaggi))
        if len(self.ricevuti) == 1:
            yield AIMessageChunk(content="Sto")
            raise _errore_contesto()
        yield AIMessageChunk(content="Ciao")

    def invoke(self, messaggi):
        self.ricevuti.append(list(messaggi))
        if len(self.ricevuti) == 1:
            raise _errore_contesto()
        return AIMessage("Ciao")


def _sessione(stream):
    llm = LlmContestoPieno()
    righe = iter(["prima domanda", "seconda domanda", "exit"])
    uscite, token = [], []
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append, token_fn=token.append,
         llm=llm, stream=stream, attesa=AttesaMuta())
    return llm, uscite, token


def test_errore_generico_non_chiude_la_sessione_in_blocco():
    llm, uscite, _ = _sessione(stream=False)
    errore = next(u for u in uscite if "Context size has been exceeded" in u)
    assert "LM Studio" in errore and "Context Length" in errore
    assert uscite[-1] == ETICHETTA_ASSISTENTE + "Ciao"  # la seconda domanda ha risposta


def test_errore_generico_non_chiude_la_sessione_in_streaming():
    llm, uscite, token = _sessione(stream=True)
    assert any("Context size has been exceeded" in u for u in uscite)
    assert "Ciao" in token
    # il testo parziale ("Sto") viene chiuso con un a capo prima del messaggio d'errore
    assert token[:3] == [ETICHETTA_ASSISTENTE, "Sto", "\n"]


def test_domanda_fallita_fuori_dalla_cronologia():
    llm, _, _ = _sessione(stream=False)
    umani = [m.content for m in llm.ricevuti[-1] if isinstance(m, HumanMessage)]
    assert umani == ["seconda domanda"]
