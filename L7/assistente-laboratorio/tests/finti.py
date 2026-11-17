# modelli finti per i test: nessuna richiesta a LM Studio
from langchain_core.messages import AIMessage


# finto modello dell'agente: restituisce le risposte preparate, una per chiamata
class ModelloFinto:
    def __init__(self, risposte: list):
        self.risposte = list(risposte)  # AIMessage da restituire in ordine
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    # il grafo associa gli strumenti al modello: qui non serve, si restituisce lo stesso oggetto
    def bind_tools(self, strumenti):
        return self

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finite le risposte preparate si ripete l'ultima (utile per i test del limite)
        risposta = self.risposte.pop(0) if len(self.risposte) > 1 else self.risposte[0]
        # copia nuova a ogni chiamata: add_messages assegna un id al messaggio e, se lo stesso
        # oggetto tornasse due volte, lo sostituirebbe invece di aggiungerlo (come un modello vero)
        return risposta.model_copy(deep=True)


# finto router: ogni elemento e' una DecisioneRouter, None oppure un'eccezione da sollevare
class RouterFinto:
    def __init__(self, decisioni: list):
        self.decisioni = list(decisioni)
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finite le decisioni preparate si ripete l'ultima
        decisione = self.decisioni.pop(0) if len(self.decisioni) > 1 else self.decisioni[0]
        if isinstance(decisione, Exception):
            raise decisione
        return decisione


# finto revisore: stesso comportamento del finto router (decisioni, None o eccezioni)
RevisoreFinto = RouterFinto


# finto modello del riassunto: restituisce i testi preparati come AIMessage (o solleva)
class RiassuntoFinto:
    # testi: risposte del modello in ordine (o eccezioni da sollevare)
    def __init__(self, testi: list):
        self.testi = list(testi)
        self.chiamate = []  # messaggi ricevuti a ogni chiamata

    # registra i messaggi e restituisce il prossimo testo come AIMessage
    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        # finiti i testi preparati si ripete l'ultimo
        testo = self.testi.pop(0) if len(self.testi) > 1 else self.testi[0]
        if isinstance(testo, Exception):
            raise testo
        return AIMessage(testo)


# finto tooltime: registra gli argomenti ricevuti e usa la logica vera dell'orologio (senza MCP)
def tooltime_finto(registro: list):
    # import qui: servono solo a chi usa questo finto strumento
    from langchain_core.tools import tool
    from mcp_assistente import orologio

    @tool("tooltime")
    def tooltime(fuso: str = "", parte: str = "entrambe") -> str:
        """Orologio finto per i test: restituisce data e ora nel fuso indicato."""
        registro.append({"fuso": fuso, "parte": parte})
        return orologio.ora_corrente(fuso, parte)
    return tooltime


# finto modello dell'agente A PEZZI (step 10): e' un vero BaseChatModel, cosi' il grafo in
# streaming (stream_mode "messages") riceve il testo parola per parola anche se il nodo chiama
# invoke; senza streaming restituisce il messaggio intero. Una risposta preparata per chiamata.
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr


class ModelloFlussoFinto(BaseChatModel):
    risposte: list  # AIMessage da restituire in ordine (finite, si ripete l'ultima)
    _usate: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "modello-flusso-finto"

    # il grafo associa gli strumenti al modello: qui non serve, si restituisce lo stesso oggetto
    def bind_tools(self, strumenti, **kwargs):
        return self

    # prossima risposta preparata (copia nuova: add_messages assegna gli id)
    def _prossima(self):
        i = min(self._usate, len(self.risposte) - 1)
        self._usate += 1
        return self.risposte[i].model_copy(deep=True)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._prossima())])

    # streaming: il testo parola per parola (spazi conservati), poi le chiamate a strumenti
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        risposta = self._prossima()
        for pezzo in re.findall(r"\S+\s*|\s+", str(risposta.content)):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=pezzo))
            if run_manager:
                run_manager.on_llm_new_token(pezzo, chunk=chunk)
            yield chunk
        if risposta.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(risposta.tool_calls)]))
        elif not str(risposta.content):
            # risposta vuota: un pezzo vuoto, cosi' lo streaming produce comunque un messaggio
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))
