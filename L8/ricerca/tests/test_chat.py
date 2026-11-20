# test del modello di chat di LM Studio con un client openai finto (nessuna chiamata di rete)
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.chat import ChatLMStudio
from app.errori import ErroreRicerca
from tests.finti import ChatFinta


# client openai finto: chat.completions.create registra gli argomenti e risponde con il contenuto preparato
class ClientChatFinto:
    def __init__(self, contenuto: str | None = "{}", errore: Exception | None = None):
        self.argomenti: list[dict] = []
        self.contenuto = contenuto
        self.errore = errore
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **argomenti):
        self.argomenti.append(argomenti)
        if self.errore is not None:
            raise self.errore
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.contenuto))])


# Verifica modello, temperatura 0, messaggi e schema JSON mandati a LM Studio.
def test_parametri_della_chiamata():
    client = ClientChatFinto(contenuto='{"query": []}')
    chat = ChatLMStudio("http://lm/v1", "gemma", client=client)
    assert chat.completa_json("sis", "ute", "riscrittura", {"type": "object"}) == '{"query": []}'
    argomenti = client.argomenti[0]
    assert argomenti["model"] == "gemma" and argomenti["temperature"] == 0
    assert argomenti["messages"] == [{"role": "system", "content": "sis"}, {"role": "user", "content": "ute"}]
    assert argomenti["response_format"]["type"] == "json_schema"
    assert argomenti["response_format"]["json_schema"]["name"] == "riscrittura"
    assert argomenti["response_format"]["json_schema"]["schema"] == {"type": "object"}


# Verifica che un errore di LM Studio diventi ErroreRicerca con indirizzo e modello.
def test_errore_di_lm_studio():
    errore = openai.APIConnectionError(request=httpx.Request("POST", "http://lm/v1"))
    chat = ChatLMStudio("http://lm/v1", "gemma", client=ClientChatFinto(errore=errore))
    with pytest.raises(ErroreRicerca, match="http://lm/v1.*gemma"):
        chat.completa_json("s", "u", "x", {})


# Verifica che una risposta senza contenuto sia un errore.
def test_contenuto_assente():
    chat = ChatLMStudio("http://lm/v1", "gemma", client=ClientChatFinto(contenuto=None))
    with pytest.raises(ErroreRicerca, match="vuota"):
        chat.completa_json("s", "u", "x", {})


# Verifica il modello finto usato dai test del recupero.
def test_chat_finta():
    chat = ChatFinta(['{"id": []}', ErroreRicerca("spenta")])
    assert chat.completa_json("s", "u", "reranking", {}) == '{"id": []}'
    with pytest.raises(ErroreRicerca):
        chat.completa_json("s", "u", "reranking", {})
    assert [c[2] for c in chat.chiamate] == ["reranking", "reranking"]


# Verifica che il client vero non ripeta le chiamate fallite (i retry moltiplicherebbero l'attesa dell'agente).
def test_nessun_retry_automatico():
    assert ChatLMStudio("http://lm/v1", "gemma").client.max_retries == 0
