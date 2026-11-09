# test del revisore: prompt, messaggi, schema e comportamento con un output non valido
import logging

import httpx
import pytest
from openai import APIConnectionError

from app.revisore import (FRASE_NON_I_DATI, FRASE_SALUTI, FRASE_TUTTE_LE_PARTI,
                          DecisioneRevisore, messaggi_per_revisore, prompt_revisore, valuta)
from tests.finti import RevisoreFinto

DOMANDA = "Che ore sono a Tokyo e che giorno è a New York?"
RISPOSTA = "A Tokyo sono le 10."


# Verifica che il prompt del revisore contenga le tre regole e non parli di strumenti.
def test_prompt_contiene_le_regole():
    prompt = prompt_revisore()
    for frase in (FRASE_TUTTE_LE_PARTI, FRASE_NON_I_DATI, FRASE_SALUTI):
        assert frase in prompt
    assert "tooltime" not in prompt


# Verifica che il revisore riceva solo la domanda e la risposta proposta.
def test_messaggi_per_revisore():
    messaggi = messaggi_per_revisore(DOMANDA, RISPOSTA)
    assert len(messaggi) == 2
    assert messaggi[1].content == f"Domanda dell'utente: {DOMANDA}\n\nRisposta proposta: {RISPOSTA}"


# Verifica l'ordine dei campi: prima il motivo, poi la decisione.
def test_motivo_prima_di_coerente():
    assert list(DecisioneRevisore.model_json_schema()["properties"]) == ["motivo", "coerente"]


# Verifica che una decisione valida venga usata cosi' com'e'.
def test_decisione_valida():
    attesa = DecisioneRevisore(motivo="manca New York", coerente=False)
    assert valuta(RevisoreFinto([attesa]), DOMANDA, RISPOSTA) == attesa


# Verifica che una risposta vuota del revisore approvi la risposta con un avviso.
def test_revisore_none_approva(caplog):
    caplog.set_level(logging.WARNING, logger="revisore")
    decisione = valuta(RevisoreFinto([None]), DOMANDA, RISPOSTA)
    assert decisione.coerente is True
    assert decisione.motivo.startswith("output del revisore non valido")
    assert "risposta approvata" in caplog.text


# Verifica che un output non leggibile del revisore approvi la risposta.
def test_eccezione_approva(caplog):
    caplog.set_level(logging.WARNING, logger="revisore")
    decisione = valuta(RevisoreFinto([ValueError("json rotto")]), DOMANDA, RISPOSTA)
    assert decisione.coerente is True
    assert "json rotto" in caplog.text


# Verifica che LM Studio irraggiungibile non sia trattato come output non valido.
def test_errore_di_connessione_sale():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with pytest.raises(APIConnectionError):
        valuta(RevisoreFinto([errore]), DOMANDA, RISPOSTA)
