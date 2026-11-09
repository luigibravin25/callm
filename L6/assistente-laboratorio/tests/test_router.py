# test del router: prompt costruito dall'ambito, messaggi passati al modello, decisione e
# comportamento con un output non valido (la domanda passa all'agente)
import logging

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import APIConnectionError
from pydantic import ValidationError

from app.config import Ambito
from app.router import (FRASE_NEL_DUBBIO, FRASE_NO_STRUMENTI, FRASE_SOLO_ARGOMENTO,
                        DecisioneRouter, decidi, messaggi_per_router, prompt_router)
from tests.finti import RouterFinto

# ambito di prova: testi riconoscibili nel prompt
AMBITO = Ambito(descrizione="Solo ora e fusi orari.", rifiuto="No.",
                esempi_in_ambito=("Che ore sono a Lima?",),
                esempi_fuori_ambito=("Ricetta del tiramisù",))


# Verifica che il prompt del router contenga descrizione ed esempi dell'ambito.
def test_prompt_contiene_ambito_ed_esempi():
    prompt = prompt_router(AMBITO)
    assert "Solo ora e fusi orari." in prompt
    assert "Che ore sono a Lima?" in prompt
    assert "Ricetta del tiramisù" in prompt


# Verifica che il router non nomini gli strumenti e dica di non sceglierli.
def test_prompt_non_parla_di_strumenti():
    prompt = prompt_router(AMBITO)
    assert "tooltime" not in prompt
    assert FRASE_NO_STRUMENTI in prompt


# Verifica le due regole aggiunte dopo la prova con gemma: solo l'argomento, nel dubbio conversazione.
def test_prompt_valuta_solo_l_argomento():
    # con gemma il router rifiutava "Che ore sono a Tokyo?" perche' giudicava se l'assistente
    # avesse abbastanza dettagli: deve guardare solo l'argomento, e nel dubbio far passare
    prompt = prompt_router(AMBITO)
    assert FRASE_SOLO_ARGOMENTO in prompt
    assert FRASE_NEL_DUBBIO in prompt


# Verifica che senza risposte precedenti il router riceva solo la domanda.
def test_messaggi_router_solo_domanda():
    messaggi = messaggi_per_router(AMBITO, [HumanMessage("Che ore sono?")])
    assert len(messaggi) == 2
    assert isinstance(messaggi[0], SystemMessage)
    assert messaggi[1].content == "Che ore sono?"


# Verifica che una domanda di seguito arrivi al router con la risposta precedente, senza ToolMessage.
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


# Verifica che una decisione valida del router venga usata cosi' com'e'.
def test_decisione_valida():
    attesa = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
    assert decidi(RouterFinto([attesa]), AMBITO, [HumanMessage("carbonara")]) == attesa


# Verifica che una risposta vuota del router mandi la domanda all'agente con un avviso.
def test_decisione_none_va_all_agente(caplog):
    caplog.set_level(logging.WARNING, logger="router")
    decisione = decidi(RouterFinto([None]), AMBITO, [HumanMessage("ciao")])
    assert decisione.categoria == "conversazione"
    assert decisione.motivo.startswith("output del router non valido")
    assert "la domanda passa all'agente" in caplog.text


# Verifica che un output non leggibile del router mandi la domanda all'agente con un avviso.
def test_eccezione_di_validazione_va_all_agente(caplog):
    caplog.set_level(logging.WARNING, logger="router")
    decisione = decidi(RouterFinto([ValueError("json rotto")]), AMBITO, [HumanMessage("ciao")])
    assert decisione.categoria == "conversazione"
    assert decisione.motivo.startswith("output del router non valido")
    assert "json rotto" in caplog.text


# Verifica l'ordine dei campi dello schema: prima il motivo, poi la categoria.
def test_motivo_prima_della_categoria():
    # il modello genera i campi nell'ordine dello schema: prima ragiona (motivo), poi decide.
    # Con categoria per prima gemma scriveva "rientra nell'ambito" e categoria fuori_ambito
    assert list(DecisioneRouter.model_json_schema()["properties"]) == ["motivo", "categoria"]


# Verifica che lo schema rifiuti una categoria diversa dalle due ammesse.
def test_categoria_sconosciuta_rifiutata_dallo_schema():
    with pytest.raises(ValidationError):
        DecisioneRouter(categoria="altro", motivo="x")


# Verifica che LM Studio irraggiungibile non sia trattato come output non valido.
def test_errore_di_connessione_non_e_output_non_valido():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with pytest.raises(APIConnectionError):
        decidi(RouterFinto([errore]), AMBITO, [HumanMessage("ciao")])
