# test del riassunto: prompt, trascrizione, punto di taglio per turni e chiamata al modello
import logging

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai import APIConnectionError

from app.riassunto import (FRASE_CONSERVA, FRASE_DATI_ESPLICITI, FRASE_LUNGHEZZA, indice_di_taglio,
                           messaggi_per_riassunto, prompt_riassunto, riassumi, trascrizione)
from tests.finti import RiassuntoFinto


# chiamata a tooltime come la scriverebbe il modello
def _chiamata(id_="c1"):
    return AIMessage("", tool_calls=[{"name": "tooltime", "args": {}, "id": id_}])


# risultato di tooltime per la chiamata con quell'id
def _risultato(id_="c1"):
    return ToolMessage("Tokyo: sono le ore 20", tool_call_id=id_, name="tooltime")


# Verifica che il prompt chieda di conservare nomi e fatti, in poche parole.
def test_prompt_contiene_le_regole():
    assert FRASE_CONSERVA in prompt_riassunto()
    assert FRASE_LUNGHEZZA in prompt_riassunto()
    assert FRASE_DATI_ESPLICITI in prompt_riassunto()


# Verifica il testo mandato al modello: una riga per messaggio, con chi parla.
def test_trascrizione():
    messaggi = [HumanMessage("Che ore sono a Tokyo?"), _chiamata(), _risultato(),
                AIMessage("A Tokyo sono le 20.")]
    assert trascrizione(messaggi) == ("Utente: Che ore sono a Tokyo?\n"
                                      "Assistente: (usa lo strumento tooltime)\n"
                                      "Strumento tooltime: Tokyo: sono le ore 20\n"
                                      "Assistente: A Tokyo sono le 20.")


# Verifica che il modello riceva il riassunto precedente ("nessuno" se vuoto) e la trascrizione.
def test_messaggi_per_riassunto_con_e_senza_vecchio():
    nuovi = [HumanMessage("Mi chiamo Luigi")]
    assert messaggi_per_riassunto("", nuovi)[1].content == (
        "Riassunto precedente: nessuno\n\nConversazione da aggiungere:\nUtente: Mi chiamo Luigi")
    assert messaggi_per_riassunto("Ha chiesto l'ora.", nuovi)[1].content.startswith(
        "Riassunto precedente: Ha chiesto l'ora.\n\n")


# Verifica il taglio che cade esattamente su una domanda: resta li'.
def test_taglio_su_una_domanda():
    messaggi = [HumanMessage("a"), AIMessage("1"), HumanMessage("b"), AIMessage("2"),
                HumanMessage("c"), AIMessage("3"), HumanMessage("d")]
    assert indice_di_taglio(messaggi, 3) == 4


# Verifica il taglio che cadrebbe dentro una catena di strumenti: arretra alla domanda.
def test_taglio_dentro_una_catena_di_strumenti():
    messaggi = [HumanMessage("a"), AIMessage("1"), HumanMessage("Tokyo?"), _chiamata(),
                _risultato(), AIMessage("le 20"), HumanMessage("d")]
    indice = indice_di_taglio(messaggi, 3)  # len - 3 = 4 e' il ToolMessage
    assert indice == 2
    assert isinstance(messaggi[indice], HumanMessage)


# Verifica un solo turno lungo: arretrando non resta niente, quindi si avanza alla domanda dopo.
def test_turno_unico_lungo_avanza():
    messaggi = [HumanMessage("a"), _chiamata("c1"), _risultato("c1"), _chiamata("c2"),
                _risultato("c2"), AIMessage("fine"), HumanMessage("b")]
    assert indice_di_taglio(messaggi, 2) == 6


# Verifica che senza un confine valido non si tagli niente.
def test_nessun_confine_valido():
    assert indice_di_taglio([HumanMessage("a"), AIMessage("1")], 1) == 0


# Verifica che il riassunto del modello venga restituito ripulito dagli spazi.
def test_riassumi_restituisce_il_testo():
    finto = RiassuntoFinto(["  L'utente si chiama Luigi.  "])
    assert riassumi(finto, "", [HumanMessage("Mi chiamo Luigi")]) == "L'utente si chiama Luigi."


# Verifica che un riassunto vuoto valga None con un avviso (i messaggi verranno conservati).
def test_riassumi_vuoto_e_none(caplog):
    caplog.set_level(logging.WARNING, logger="riassunto")
    assert riassumi(RiassuntoFinto([""]), "", [HumanMessage("a")]) is None
    assert "messaggi conservati" in caplog.text


# Verifica che un errore del modello che non e' di LM Studio valga None.
def test_riassumi_eccezione_e_none():
    assert riassumi(RiassuntoFinto([ValueError("rotto")]), "", [HumanMessage("a")]) is None


# Verifica che LM Studio irraggiungibile salga al chiamante.
def test_riassumi_errore_di_connessione_sale():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with pytest.raises(APIConnectionError):
        riassumi(RiassuntoFinto([errore]), "", [HumanMessage("a")])
