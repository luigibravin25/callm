# test degli schemi dell'API: validazione delle richieste, conversione OpenAI <-> LangChain
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from app.info_prompt import InfoArgomento, InfoPrompt
from app.schemi import (MessaggioOpenAI, RichiestaChat, a_info, a_openai, da_info, da_openai)

# conversazione con uno strumento e una risposta fissa del programma
CONVERSAZIONE = [
    HumanMessage("Che ore sono a Tokyo?"),
    AIMessage("", tool_calls=[{"id": "c1", "name": "tooltime", "args": {"fuso": "Asia/Tokyo"}}]),
    ToolMessage("01:12", tool_call_id="c1", name="tooltime"),
    AIMessage("Sono le 01:12.", name="programma"),
]


# riduce un messaggio ai campi che il grafo usa (niente id dei messaggi ne' status)
def _essenziale(m):
    chiamate = [(c["id"], c["name"], c["args"]) for c in getattr(m, "tool_calls", [])]
    return (type(m), m.content, chiamate, getattr(m, "tool_call_id", None), m.name)


# Verifica che il giro LangChain -> OpenAI -> LangChain non perda nulla di cio' che usa il grafo.
def test_giro_senza_perdite():
    ritorno = da_openai(a_openai(CONVERSAZIONE))
    assert [_essenziale(m) for m in ritorno] == [_essenziale(m) for m in CONVERSAZIONE]


# Verifica che il formato OpenAI abbia role, tool_calls con arguments in testo e tool_call_id.
def test_formato_openai():
    o = a_openai(CONVERSAZIONE)
    assert [m.role for m in o] == ["user", "assistant", "tool", "assistant"]
    assert o[1].tool_calls[0].function.name == "tooltime"
    assert o[1].tool_calls[0].function.arguments == '{"fuso": "Asia/Tokyo"}'
    assert o[2].tool_call_id == "c1" and o[3].name == "programma"


# Verifica che accenti ed emoji facciano il giro intatti.
def test_accenti_ed_emoji():
    testo = "Perché? 🕐 àèìòù"
    assert da_openai(a_openai([HumanMessage(testo)]))[0].content == testo


# Verifica le richieste valide: solo messaggio, solo prompt, cronologia con "programma".
def test_richieste_valide():
    RichiestaChat(messaggio="Ciao")
    RichiestaChat(prompt={"nome": "spiega", "argomenti": {"argomento": "MCP"}})
    RichiestaChat(messaggio="e a Londra?", cronologia=a_openai(CONVERSAZIONE), riassunto="r")


# Verifica le richieste non valide (ognuna con il suo motivo).
@pytest.mark.parametrize("dati,motivo", [
    ({}, "serve messaggio oppure prompt"),
    ({"messaggio": "a", "prompt": {"nome": "spiega"}}, "messaggio e prompt insieme"),
    ({"messaggio": "   "}, "messaggio vuoto"),
    ({"messaggio": "a", "cronologia": [{"role": "system", "content": "x"}]},
     "messaggi di sistema non ammessi"),
    ({"messaggio": "a", "cronologia": [{"role": "user", "content": "x", "name": "revisore"}]},
     "name 'revisore' riservato"),
    ({"messaggio": "a", "cronologia": [{"role": "tool", "content": "x"}]}, "tool_call_id"),
    ({"messaggio": "a", "cronologia": [{"role": "capo", "content": "x"}]}, "role"),
    ({"messaggio": "a", "cronologia": "x"}, "cronologia"),
    ({"messaggio": "a", "altro": 1}, "altro"),
    ({"prompt": {"nome": "spiega", "argomenti": {"a": 1}}}, "argomenti"),
    ({"messaggio": "a", "cronologia": [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "tooltime", "arguments": "non json"}}]}]},
     "arguments"),
])
def test_richieste_non_valide(dati, motivo):
    with pytest.raises(ValidationError) as errore:
        RichiestaChat.model_validate(dati)
    assert motivo in str(errore.value)


# Verifica che "programma" sia ammesso su un messaggio dell'assistente.
def test_programma_ammesso():
    m = MessaggioOpenAI(role="assistant", content="limite", name="programma")
    assert da_openai([m])[0].name == "programma"


# Verifica la conversione dei tipi dei prompt verso il JSON e ritorno (la usa la CLI).
def test_prompt_pubblicato_e_ritorno():
    info = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                            InfoArgomento("livello", False)))
    pubblicato = da_info(info)
    assert pubblicato.model_dump()["argomenti"][0] == {"nome": "argomento", "obbligatorio": True}
    assert a_info(pubblicato.model_dump()) == info
