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



# Verifica (M-2) il formato OpenAI standard: content null con tool_calls e content a blocchi.
def test_content_null_e_a_blocchi():
    m = MessaggioOpenAI.model_validate({"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "tooltime", "arguments": "{}"}}]})
    assert m.content == ""
    m = MessaggioOpenAI.model_validate({"role": "user",
                                        "content": [{"type": "text", "text": "ciao"}]})
    assert m.content == "ciao"


# --- coerenza della cronologia (minore 1 dello step 6) ---

# messaggi OpenAI di comodo per costruire le cronologie dei test
def _utente(testo="domanda"):
    return {"role": "user", "content": testo}


def _chiamate(*ids):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": "tooltime", "arguments": "{}"}}
        for i in ids]}


def _strumento(id_chiamata):
    return {"role": "tool", "content": "01:12", "tool_call_id": id_chiamata, "name": "tooltime"}


def _risposta(testo="Sono le 01:12."):
    return {"role": "assistant", "content": testo}


# Verifica che un messaggio 'tool' senza la chiamata che lo ha chiesto sia rifiutato.
def test_tool_orfano_rifiutato():
    with pytest.raises(ValidationError) as errore:
        RichiestaChat.model_validate({"messaggio": "a", "cronologia": [_utente(), _strumento("c1")]})
    assert ("cronologia[1]: messaggio 'tool' senza una chiamata corrispondente "
            "(tool_call_id 'c1')") in str(errore.value)


# Verifica che una chiamata senza risposta dello strumento sia rifiutata, sia prima del messaggio
# successivo sia a fine lista.
@pytest.mark.parametrize("cronologia, testo", [
    ([_utente(), _chiamate("c1"), _utente()],
     "cronologia[2]: chiamata 'c1' senza risposta dello strumento"),
    ([_utente(), _chiamate("c1")], "cronologia[1]: chiamata 'c1' senza risposta dello strumento"),
])
def test_tool_calls_senza_risposta_rifiutate(cronologia, testo):
    with pytest.raises(ValidationError) as errore:
        RichiestaChat.model_validate({"messaggio": "a", "cronologia": cronologia})
    assert testo in str(errore.value)


# Verifica che lo stesso id usato in due turni completi sia ammesso (LM Studio puo' riusarlo).
def test_id_riusato_in_turno_successivo_ammesso():
    turno = [_utente(), _chiamate("c1"), _strumento("c1"), _risposta()]
    RichiestaChat.model_validate({"messaggio": "a", "cronologia": turno + turno})


# Verifica due chiamate nello stesso messaggio con le risposte in ordine diverso.
def test_cronologia_coerente_con_due_chiamate():
    RichiestaChat.model_validate({"messaggio": "a", "cronologia": [
        _utente(), _chiamate("c1", "c2"), _strumento("c2"), _strumento("c1"), _risposta()]})
