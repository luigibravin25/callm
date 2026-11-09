# test del router: prompt costruito dall'ambito, messaggi passati al modello, decisione e
# comportamento con un output non valido (la domanda passa all'agente)
import logging

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import APIConnectionError
from pydantic import ValidationError

from app.config import Ambito
from app.router import (FRASE_NO_STRUMENTI, DecisioneRouter, decidi, messaggi_per_router,
                        prompt_router)
from tests.finti import RouterFinto

# ambito di prova: testi riconoscibili nel prompt
AMBITO = Ambito(descrizione="Solo ora e fusi orari.", rifiuto="No.",
                esempi_in_ambito=("Che ore sono a Lima?",),
                esempi_fuori_ambito=("Ricetta del tiramisù",))


def test_prompt_contiene_ambito_ed_esempi():
    prompt = prompt_router(AMBITO)
    assert "Solo ora e fusi orari." in prompt
    assert "Che ore sono a Lima?" in prompt
    assert "Ricetta del tiramisù" in prompt


def test_prompt_non_parla_di_strumenti():
    prompt = prompt_router(AMBITO)
    assert "tooltime" not in prompt
    assert FRASE_NO_STRUMENTI in prompt


def test_messaggi_router_solo_domanda():
    messaggi = messaggi_per_router(AMBITO, [HumanMessage("Che ore sono?")])
    assert len(messaggi) == 2
    assert isinstance(messaggi[0], SystemMessage)
    assert messaggi[1].content == "Che ore sono?"


def test_messaggi_router_con_risposta_precedente():
    # la domanda di seguito "e a Londra?" si capisce solo con la risposta precedente
    chiamata = {"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": "c1"}
    cronologia = [HumanMessage("Che ore sono a Tokyo?"),
                  AIMessage("", tool_calls=[chiamata]),
                  ToolMessage("Tokyo: sono le ore 10", tool_call_id="c1", name="tooltime"),
                  AIMessage("A Tokyo sono le 10"),
                  HumanMessage("e a Londra?")]
    messaggi = messaggi_per_router(AMBITO, cronologia)
    assert len(messaggi) == 2  # niente ToolMessage, niente cronologia completa
    assert messaggi[1].content == ("Risposta precedente dell'assistente: A Tokyo sono le 10"
                                   "\n\nDomanda dell'utente: e a Londra?")


def test_decisione_valida():
    attesa = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
    assert decidi(RouterFinto([attesa]), AMBITO, [HumanMessage("carbonara")]) == attesa


def test_decisione_none_va_all_agente(caplog):
    caplog.set_level(logging.WARNING, logger="router")
    decisione = decidi(RouterFinto([None]), AMBITO, [HumanMessage("ciao")])
    assert decisione.categoria == "conversazione"
    assert decisione.motivo.startswith("output del router non valido")
    assert "la domanda passa all'agente" in caplog.text


def test_eccezione_di_validazione_va_all_agente(caplog):
    caplog.set_level(logging.WARNING, logger="router")
    decisione = decidi(RouterFinto([ValueError("json rotto")]), AMBITO, [HumanMessage("ciao")])
    assert decisione.categoria == "conversazione"
    assert decisione.motivo.startswith("output del router non valido")
    assert "json rotto" in caplog.text


def test_categoria_sconosciuta_rifiutata_dallo_schema():
    with pytest.raises(ValidationError):
        DecisioneRouter(categoria="altro", motivo="x")


def test_errore_di_connessione_non_e_output_non_valido():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with pytest.raises(APIConnectionError):
        decidi(RouterFinto([errore]), AMBITO, [HumanMessage("ciao")])
