# test degli eventi del turno in streaming (step 10): grafo vero, modello finto a pezzi, router e
# revisore finti; nessuna richiesta a LM Studio
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError

from app.agente import Agente
from app.config import Ambito
from app.flusso import eventi_turno
from app.graph import MSG_VUOTO, build_graph
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from tests.finti import ModelloFlussoFinto, RevisoreFinto, RiassuntoFinto, RouterFinto, tooltime_finto

AMBITO = Ambito(descrizione="Solo ora, data e fusi orari.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="chiede l'ora")
FUORI = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
OK = DecisioneRevisore(motivo="risponde", coerente=True)


def NO(motivo):
    return DecisioneRevisore(motivo=motivo, coerente=False)


# grafo con il modello finto a pezzi e lo strumento finto
def _grafo(risposte, router=None, revisore=None, max_steps=5, max_revisioni=2):
    return build_graph(ModelloFlussoFinto(risposte=risposte), router or RouterFinto([IN_AMBITO]),
                       revisore or RevisoreFinto([OK]), RiassuntoFinto(["riassunto"]), AMBITO,
                       max_steps=max_steps, max_revisioni=max_revisioni,
                       strumenti=[tooltime_finto([])], fuso_predefinito="Europe/Rome")


def _ingresso(domanda="Che ore sono?"):
    return {"messages": [HumanMessage(domanda)], "steps": 0, "revisioni": 0, "riassunto": ""}


def _eventi(grafo, domanda="Che ore sono?"):
    return list(eventi_turno(grafo, _ingresso(domanda), "Europe/Rome"))


def _tipi(eventi):
    return [e.tipo for e in eventi]


def _testo(eventi):
    return "".join(e.dati["testo"] for e in eventi if e.tipo == "testo")


# Verifica l'ordine senza strumenti: fase pensa, bozza, testo a pezzi, fase revisore, stato finale.
def test_ordine_senza_strumenti():
    eventi = _eventi(_grafo([AIMessage("A Roma sono le 12 in punto.")]))
    tipi = _tipi(eventi)
    assert tipi[0] == "fase" and eventi[0].dati == {"fase": "pensa"}
    assert tipi[1] == "bozza"
    assert tipi.count("testo") >= 3
    assert {"fase": "revisore"} in [e.dati for e in eventi if e.tipo == "fase"]
    assert tipi[-1] == "stato_finale"
    assert _testo(eventi) == "A Roma sono le 12 in punto."
    assert eventi[-1].dati["messages"][-1].content == "A Roma sono le 12 in punto."


# Verifica l'evento strumento: fuso completato con quello delle preferenze, prima del testo finale.
def test_strumento_con_fuso_completato():
    chiamata = {"name": "tooltime", "args": {}, "id": "c1"}
    eventi = _eventi(_grafo([AIMessage("", tool_calls=[chiamata]), AIMessage("Sono le 12.")]))
    strumenti = [e for e in eventi if e.tipo == "strumento"]
    assert len(strumenti) == 1
    assert strumenti[0].dati["nome"] == "tooltime"
    assert strumenti[0].dati["argomenti"]["fuso"] == "Europe/Rome"
    tipi = _tipi(eventi)
    assert tipi.index("strumento") < max(i for i, t in enumerate(tipi) if t == "testo")
    # due esecuzioni del modello: due bozze
    assert tipi.count("bozza") == 2


# Verifica il revisore che rifiuta: evento revisione con il solo motivo, poi una nuova bozza.
def test_revisore_che_rifiuta():
    eventi = _eventi(_grafo([AIMessage("Bozza uno."), AIMessage("Bozza due completa.")],
                            revisore=RevisoreFinto([NO("ore a Tokyo: mancante"), OK])))
    revisioni = [e for e in eventi if e.tipo == "revisione"]
    assert [r.dati for r in revisioni] == [{"motivo": "ore a Tokyo: mancante"}]
    tipi = _tipi(eventi)
    assert tipi.count("bozza") == 2
    assert tipi.index("revisione") < len(tipi) - 1 - tipi[::-1].index("bozza")
    assert eventi[-1].dati["messages"][-1].content == "Bozza due completa."


# Verifica che il testo finale sia quello dello stato (ultima bozza dopo il limite di revisioni),
# anche se in streaming sono arrivate piu' bozze.
def test_fine_prevale_sulla_bozza():
    eventi = _eventi(_grafo([AIMessage("Prima."), AIMessage("Seconda.")], max_revisioni=1,
                            revisore=RevisoreFinto([NO("manca"), NO("manca ancora")])))
    assert eventi[-1].dati["messages"][-1].content == "Seconda."
    assert _testo(eventi) == "Prima.Seconda."


# Verifica il rifiuto fuori ambito: nessun testo dal modello, testo fisso nello stato finale.
def test_rifiuto_senza_testo():
    eventi = _eventi(_grafo([AIMessage("non deve arrivare")], router=RouterFinto([FUORI])))
    assert "testo" not in _tipi(eventi) and "bozza" not in _tipi(eventi)
    assert eventi[-1].dati["messages"][-1].content == "Fuori dal mio ambito."


# Verifica che la risposta fissa di risposta vuota non arrivi come testo della bozza.
def test_risposta_vuota_non_e_testo():
    eventi = _eventi(_grafo([AIMessage("")]))
    assert MSG_VUOTO not in _testo(eventi)
    assert eventi[-1].dati["messages"][-1].content == MSG_VUOTO


# Verifica che le chiamate fermate dal limite non vengano annunciate.
def test_limite_non_annuncia_strumenti():
    chiamata = {"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": "c1"}
    eventi = _eventi(_grafo([AIMessage("", tool_calls=[chiamata])], max_steps=0))
    assert "strumento" not in _tipi(eventi)


# Verifica che turno e turno_in_flusso diano lo stesso esito per lo stesso ingresso.
def test_fine_uguale_a_turno():
    chiamata = {"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": "c1"}
    risposte = [AIMessage("", tool_calls=[chiamata]), AIMessage("A Tokyo sono le 20.")]
    agente1 = Agente(grafo=_grafo(risposte), prompts=[], mcp_partito=True, strumenti=("tooltime",),
                     motivo_mcp="", fuso_predefinito="Europe/Rome")
    agente2 = Agente(grafo=_grafo(risposte), prompts=[], mcp_partito=True, strumenti=("tooltime",),
                     motivo_mcp="", fuso_predefinito="Europe/Rome")
    esito = agente1.turno([HumanMessage("Che ore sono a Tokyo?")], [], "")
    eventi = list(agente2.turno_in_flusso([HumanMessage("Che ore sono a Tokyo?")], [], ""))
    assert eventi[-1].tipo == "fine"
    fine = eventi[-1].dati
    assert fine.risposta == esito.risposta == "A Tokyo sono le 20."
    assert fine.strumenti_usati == esito.strumenti_usati
    assert [m.content for m in fine.messaggi] == [m.content for m in esito.messaggi]
    assert "stato_finale" not in _tipi(eventi)


# Verifica che un errore del modello a meta' turno risalga dal generatore.
def test_eccezione_a_meta():
    class Rotto(ModelloFlussoFinto):
        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            raise APIConnectionError(request=httpx.Request("POST", "http://lm"))

    grafo = build_graph(Rotto(risposte=[AIMessage("x")]), RouterFinto([IN_AMBITO]),
                        RevisoreFinto([OK]), RiassuntoFinto(["r"]), AMBITO,
                        strumenti=[tooltime_finto([])])
    with pytest.raises(APIConnectionError):
        list(eventi_turno(grafo, _ingresso(), "Europe/Rome"))
