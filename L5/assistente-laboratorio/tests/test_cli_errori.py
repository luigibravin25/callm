"""Errori generici di LM Studio (openai.APIError) durante una domanda: messaggio e sessione viva."""
# httpx (richiesta finta per l'errore), messaggi di LangChain, errore generico di openai
import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from openai import APIError

# il codice da verificare
from app.cli import ETICHETTA_ASSISTENTE, main


# attesa finta che non fa nulla: i puntini non servono in questi test
class AttesaMuta:
    def avvia(self):
        pass

    def ferma(self):
        pass


# l'errore che LM Studio da' quando la conversazione supera la "Context Length"
def _errore_contesto():
    return APIError("Context size has been exceeded.", httpx.Request("POST", "http://x"),
                    body=None)


class LlmContestoPieno:
    """Prima domanda: errore di contesto (dopo un token, come nello streaming); poi risponde."""

    def __init__(self):
        self.ricevuti = []  # i messaggi ricevuti a ogni chiamata

    # versione in streaming: un primo token, poi l'errore
    def stream(self, messaggi):
        self.ricevuti.append(list(messaggi))
        if len(self.ricevuti) == 1:
            yield AIMessageChunk(content="Sto")
            raise _errore_contesto()
        yield AIMessageChunk(content="Ciao")

    # versione in blocco: subito l'errore alla prima chiamata
    def invoke(self, messaggi):
        self.ricevuti.append(list(messaggi))
        if len(self.ricevuti) == 1:
            raise _errore_contesto()
        return AIMessage("Ciao")


# sessione con due domande: la prima fallisce, la seconda deve avere risposta
def _sessione(stream):
    llm = LlmContestoPieno()
    righe = iter(["prima domanda", "seconda domanda", "exit"])
    uscite, token = [], []  # righe intere e token dello streaming
    main(input_fn=lambda _p="": next(righe), output_fn=uscite.append, token_fn=token.append,
         llm=llm, stream=stream, attesa=AttesaMuta())
    return llm, uscite, token


# senza streaming: messaggio d'errore che spiega cosa fare e la chat continua
def test_errore_generico_non_chiude_la_sessione_in_blocco():
    llm, uscite, _ = _sessione(stream=False)
    errore = next(u for u in uscite if "Context size has been exceeded" in u)
    # il messaggio nomina LM Studio e l'impostazione da cambiare
    assert "LM Studio" in errore and "Context Length" in errore
    assert uscite[-1] == ETICHETTA_ASSISTENTE + "Ciao"  # la seconda domanda ha risposta


# in streaming: stesso errore dopo un token parziale, la chat continua
def test_errore_generico_non_chiude_la_sessione_in_streaming():
    llm, uscite, token = _sessione(stream=True)
    assert any("Context size has been exceeded" in u for u in uscite)
    assert "Ciao" in token  # risposta alla seconda domanda
    # il testo parziale ("Sto") viene chiuso con un a capo prima del messaggio d'errore
    assert token[:3] == [ETICHETTA_ASSISTENTE, "Sto", "\n"]


# la domanda fallita non resta nella cronologia: il modello non la rivede alla domanda dopo
def test_domanda_fallita_fuori_dalla_cronologia():
    llm, _, _ = _sessione(stream=False)
    # messaggi dell'utente ricevuti dal modello nell'ultima chiamata
    umani = [m.content for m in llm.ricevuti[-1] if isinstance(m, HumanMessage)]
    assert umani == ["seconda domanda"]
