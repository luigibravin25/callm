# test dell'embedder di LM Studio con un client openai finto (nessuna chiamata di rete)
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.embedding import EmbedderLMStudio
from app.errori import ErroreRicerca
from tests.finti import EmbedderFinto


# client openai finto: embeddings.create registra gli input e risponde con un vettore per testo
class ClientFinto:
    def __init__(self, risposta=None, errore=None):
        self.input: list[list[str]] = []
        self.risposta = risposta  # funzione input → data, per risposte malformate
        self.errore = errore
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model, input):
        self.input.append(list(input))
        if self.errore is not None:
            raise self.errore
        data = self.risposta(input) if self.risposta else [SimpleNamespace(embedding=[float(len(t))])
                                                            for t in input]
        return SimpleNamespace(data=data)


def test_lotti():
    client = ClientFinto()
    embedder = EmbedderLMStudio("http://lm:1234/v1", "bge", lotto=32, client=client)
    testi = [f"testo {i}" for i in range(70)]
    vettori = embedder.incorpora(testi)
    assert [len(lotto) for lotto in client.input] == [32, 32, 6]
    assert vettori == [[float(len(t))] for t in testi]


@pytest.mark.parametrize("client", [
    ClientFinto(errore=openai.APIConnectionError(request=httpx.Request("POST", "http://lm:1234/v1"))),
    ClientFinto(risposta=lambda testi: [SimpleNamespace(embedding=[1.0])]),
])
def test_errori_comprensibili(client):
    embedder = EmbedderLMStudio("http://lm:1234/v1", "bge", client=client)
    with pytest.raises(ErroreRicerca) as errore:
        embedder.incorpora(["uno", "due"])
    assert "http://lm:1234/v1" in str(errore.value) and "bge" in str(errore.value)


def test_embedder_finto_deterministico():
    finto = EmbedderFinto()
    a, b, a2 = finto.incorpora(["a", "b", "a"])
    assert a == a2 and a != b and len(a) == 8
