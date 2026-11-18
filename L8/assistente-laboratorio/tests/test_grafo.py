# test del grafo: router prima dell'agente, rifiuto fisso, ciclo agente-strumenti, limite,
# revisore dopo l'agente e pulizia a fine turno, riassunto della cronologia prima del router
import logging
from datetime import datetime, timezone

import pytest
import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import APIConnectionError

from app.config import Ambito
from app.graph import MSG_NON_DISPONIBILE, MSG_VUOTO, build_graph, messaggi_da_pulire
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from app.graph import completa_fuso
from app.llm import SYSTEM_PROMPT, prompt_agente
from app.preferenze import Preferenze
from mcp_assistente import orologio as modulo_orologio
from tests.finti import (ModelloFinto, RevisoreFinto, RiassuntoFinto, RouterFinto, search_documents_finto,
                         tooltime_finto)

AMBITO = Ambito(descrizione="Solo ora, data e fusi orari.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="chiede l'ora")
FUORI = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
OK = DecisioneRevisore(motivo="risponde", coerente=True)


# decisione negativa del revisore con il motivo dato
def NO(motivo="incompleta"):
    return DecisioneRevisore(motivo=motivo, coerente=False)


# tutti i log di router, agente e rifiuto finiscono in caplog
@pytest.fixture(autouse=True)
def log(caplog):
    for nome in ("router", "agente", "rifiuto", "revisore", "riassunto", "citazioni"):
        caplog.set_level(logging.INFO, logger=nome)
    return caplog


# orologio fisso: 1 marzo 2026 11:00 UTC
@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    monkeypatch.setattr(modulo_orologio, "_adesso",
                        lambda: datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc))


# chiamata a tooltime come la scriverebbe il modello
def _chiamata(id_="c1"):
    return {"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": id_}


# esegue il grafo con una domanda e restituisce lo stato finale
# (revisore predefinito: approva sempre; riassunto predefinito: testo fisso "riassunto")
def _esegui(agente, router, domanda="Che ore sono?", max_steps=5, revisore=None,
            max_revisioni=2, cronologia=(), riassunto="", riassunto_llm=None, soglia=16,
            recenti=6, registro=None, fuso="Europe/Rome", system_prompt=SYSTEM_PROMPT,
            strumenti=None):
    revisore = revisore or RevisoreFinto([OK])
    # strumento finto: registro raccoglie gli argomenti di ogni chiamata (lezione 8: strumenti a scelta)
    strumenti = strumenti or [tooltime_finto(registro if registro is not None else [])]
    riassunto_llm = riassunto_llm or RiassuntoFinto(["riassunto"])
    grafo = build_graph(agente, router, revisore, riassunto_llm, AMBITO, max_steps=max_steps,
                        max_revisioni=max_revisioni, soglia_riassunto=soglia,
                        messaggi_recenti=recenti, strumenti=strumenti,
                        system_prompt=system_prompt, fuso_predefinito=fuso)
    return grafo.invoke({"messages": list(cronologia) + [HumanMessage(domanda)], "steps": 0,
                         "revisioni": 0, "riassunto": riassunto})


# messaggi del revisore rimasti nello stato
def _del_revisore(out):
    return [m for m in out["messages"] if getattr(m, "name", None) == "revisore"]


# Verifica il percorso in ambito: log del router con categoria e motivo, poi nodo modello.
def test_in_ambito_passa_all_agente(log):
    agente = ModelloFinto([AIMessage("Sono le 10")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]))
    assert out["messages"][-1].content == "Sono le 10"
    assert len(agente.chiamate) == 1
    assert 'categoria=conversazione motivo="chiede l\'ora" → agente' in log.text
    assert "nodo modello" in log.text


# Verifica il percorso fuori ambito: rifiuto fisso e nessuna esecuzione del nodo modello.
def test_fuori_ambito_non_raggiunge_l_agente(log):
    agente = ModelloFinto([AIMessage("non dovrei rispondere")])
    out = _esegui(agente, RouterFinto([FUORI]), "Ricetta della carbonara")
    assert out["messages"][-1].content == AMBITO.rifiuto
    assert agente.chiamate == []
    assert 'categoria=fuori_ambito motivo="ricetta" → rifiuto' in log.text
    assert "risposta fissa inviata" in log.text
    assert "nodo modello" not in log.text


# Verifica che con un output non valido del router risponda l'agente.
def test_output_non_valido_passa_all_agente(log):
    agente = ModelloFinto([AIMessage("Ciao!")])
    out = _esegui(agente, RouterFinto([None]))
    assert out["messages"][-1].content == "Ciao!"
    assert len(agente.chiamate) == 1
    assert "la domanda passa all'agente" in log.text


# Verifica che in ambito l'agente usi tooltime e risponda con il risultato.
def test_in_ambito_con_strumento(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]),
                           AIMessage("A Tokyo sono le 20")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), "Che ore sono a Tokyo?")
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(risultati) == 1 and "Tokyo" in risultati[0].content
    assert out["messages"][-1].content == "A Tokyo sono le 20"
    assert "chiamata strumento tooltime" in log.text


# Verifica che il prompt mandato al router non nomini tooltime.
def test_router_non_riceve_strumenti():
    router = RouterFinto([IN_AMBITO])
    _esegui(ModelloFinto([AIMessage("ok")]), router)
    assert "tooltime" not in router.chiamate[0][0].content


# Verifica il limite di passaggi e che ogni tool_call abbia la sua risposta.
def test_limite_passaggi():
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()])])  # chiede sempre tooltime
    out = _esegui(agente, RouterFinto([IN_AMBITO]), max_steps=2)
    assert "limite di 2 passaggi" in out["messages"][-1].content
    # ogni tool_call ha la sua risposta: la cronologia resta valida
    chiamate = {c["id"] for m in out["messages"] if isinstance(m, AIMessage) for c in m.tool_calls}
    risposte = {m.tool_call_id for m in out["messages"] if isinstance(m, ToolMessage)}
    assert chiamate == risposte


# Verifica il messaggio fisso quando il modello non restituisce niente.
def test_risposta_vuota():
    out = _esegui(ModelloFinto([AIMessage("")]), RouterFinto([IN_AMBITO]))
    assert out["messages"][-1].content == MSG_VUOTO


# Verifica che categoria e motivo del router restino nello stato.
def test_stato_contiene_categoria_e_motivo():
    out = _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]))
    assert out["categoria"] == "fuori_ambito"
    assert out["motivo"] == "ricetta"


# Verifica che domanda e rifiuto restino nella cronologia della sessione.
def test_rifiuto_resta_in_cronologia():
    out = _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]), "Ricetta")
    assert [type(m) for m in out["messages"]] == [HumanMessage, AIMessage]
    assert out["messages"][0].content == "Ricetta"
    assert out["messages"][1].content == AMBITO.rifiuto


DUE_PARTI = "Che ore sono a Tokyo e che giorno è a New York?"
PARZIALE = "A Tokyo sono le 10."
COMPLETA = "A Tokyo sono le 10, a New York è il 1 marzo."


# Verifica la risposta parziale: rifiuto motivato, messaggio [Revisore] all'agente,
# risposta completa.
def test_risposta_parziale_torna_all_agente(log):
    agente = ModelloFinto([AIMessage(PARZIALE), AIMessage(COMPLETA)])
    revisore = RevisoreFinto([NO("manca New York"), OK])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI, revisore=revisore)
    assert len(agente.chiamate) == 2
    indicazione = agente.chiamate[1][-1]
    assert isinstance(indicazione, HumanMessage) and indicazione.name == "revisore"
    assert "manca New York" in indicazione.content
    assert out["messages"][-1].content == COMPLETA
    assert 'non coerente motivo="manca New York" → agente (revisione 1 di 2)' in log.text
    assert 'coerente motivo="risponde" → fine' in log.text


# Verifica la risposta coerente approvata al primo passaggio.
def test_coerente_al_primo_passaggio():
    agente, revisore = ModelloFinto([AIMessage(COMPLETA)]), RevisoreFinto([OK])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI, revisore=revisore)
    assert len(agente.chiamate) == 1 and len(revisore.chiamate) == 1
    assert _del_revisore(out) == []


# Verifica il limite con un revisore che rifiuta sempre: si consegna l'ultima risposta.
def test_limite_di_revisioni(log):
    agente = ModelloFinto([AIMessage("bozza 1"), AIMessage("bozza 2"), AIMessage("bozza 3")])
    revisore = RevisoreFinto([NO("x")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=revisore, max_revisioni=2)
    assert len(revisore.chiamate) == 3 and len(agente.chiamate) == 3
    assert "limite di revisioni raggiunto (2): restituisco l'ultima risposta" in log.text
    assert out["messages"][-1].content == "bozza 3"


# Verifica che la pulizia lasci solo la domanda e la risposta finale.
def test_pulizia_toglie_revisore_e_bozze(log):
    agente = ModelloFinto([AIMessage(PARZIALE), AIMessage(COMPLETA)])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), DUE_PARTI,
                  revisore=RevisoreFinto([NO(), OK]))
    assert [(type(m), m.content) for m in out["messages"]] == \
        [(HumanMessage, DUE_PARTI), (AIMessage, COMPLETA)]
    assert "pulizia: tolti 2 messaggi (indicazioni del revisore e bozze rifiutate)" in log.text


# Verifica che la pulizia non tocchi le coppie chiamata-strumento e risultato.
def test_pulizia_lascia_le_coppie_strumenti():
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]), AIMessage("bozza"),
                           AIMessage("completa")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO(), OK]))
    chiamate = [m for m in out["messages"] if isinstance(m, AIMessage) and m.tool_calls]
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(chiamate) == 1 and len(risultati) == 1
    assert "bozza" not in [m.content for m in out["messages"]]
    assert out["messages"][-1].content == "completa"


# Verifica che il percorso fuori ambito non passi dal revisore.
def test_fuori_ambito_salta_il_revisore():
    revisore = RevisoreFinto([OK])
    _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]), revisore=revisore)
    assert revisore.chiamate == []


# Verifica che il messaggio fisso di risposta vuota non passi dal revisore.
def test_risposta_vuota_salta_il_revisore():
    revisore = RevisoreFinto([OK])
    out = _esegui(ModelloFinto([AIMessage("")]), RouterFinto([IN_AMBITO]), revisore=revisore)
    assert revisore.chiamate == []
    assert out["messages"][-1].content == MSG_VUOTO


# Verifica che dopo una revisione il limite di strumenti non nasconda la bozza parziale:
# i [Revisore] spariscono, le coppie strumenti restano e l'utente vede l'ultima bozza.
def test_limite_dopo_revisione_mostra_la_bozza(log):
    agente = ModelloFinto([AIMessage("bozza"), AIMessage("", tool_calls=[_chiamata()])])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO()]),
                  max_steps=1)
    assert _del_revisore(out) == []
    assert out["messages"][-1].content == "bozza"
    assert "limite di 1 passaggi" not in [m.content for m in out["messages"]]
    chiamate = {c["id"] for m in out["messages"] if isinstance(m, AIMessage)
                for c in m.tool_calls}
    risposte = {m.tool_call_id for m in out["messages"] if isinstance(m, ToolMessage)}
    assert chiamate == risposte
    assert "restituisco l'ultima bozza" in log.text


# Verifica che dopo una revisione una risposta vuota non nasconda la bozza parziale.
def test_risposta_vuota_dopo_revisione_mostra_la_bozza():
    agente = ModelloFinto([AIMessage("bozza parziale"), AIMessage("")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO()]))
    assert out["messages"][-1].content == "bozza parziale"
    assert MSG_VUOTO not in [m.content for m in out["messages"]]
    assert _del_revisore(out) == []


# Verifica la catena bozza -> [Revisore] -> strumento -> risposta finale: la coppia resta, la
# bozza e il [Revisore] spariscono.
def test_strumenti_dopo_la_revisione():
    agente = ModelloFinto([AIMessage("bozza"), AIMessage("", tool_calls=[_chiamata()]),
                           AIMessage("completa")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO(), OK]))
    tipi = [type(m) for m in out["messages"]]
    assert tipi == [HumanMessage, AIMessage, ToolMessage, AIMessage]
    assert out["messages"][1].tool_calls and out["messages"][-1].content == "completa"


# Verifica MAX_REVISIONI=0: il revisore valuta e scrive il limite, ma non rimanda all'agente.
def test_max_revisioni_zero(log):
    agente = ModelloFinto([AIMessage("bozza")])
    _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([NO()]), max_revisioni=0)
    assert len(agente.chiamate) == 1
    assert "limite di revisioni raggiunto (0)" in log.text


# Verifica che un output non valido del revisore approvi la prima risposta.
def test_output_non_valido_del_revisore_approva():
    agente = ModelloFinto([AIMessage("prima"), AIMessage("seconda")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), revisore=RevisoreFinto([None]))
    assert len(agente.chiamate) == 1
    assert out["messages"][-1].content == "prima"


# Verifica quali id toglie la pulizia: messaggi del revisore e bozze rifiutate del turno in corso.
def test_messaggi_da_pulire():
    messaggi = [HumanMessage("vecchia", id="h0"), AIMessage("vecchia bozza", id="a0"),
                HumanMessage("[Revisore] vecchio", name="revisore", id="r0"),
                HumanMessage("domanda", id="h1"),
                AIMessage("", tool_calls=[_chiamata()], id="a1"),
                ToolMessage("Tokyo", tool_call_id="c1", id="t1"),
                AIMessage("bozza", id="a2"),
                HumanMessage("[Revisore] manca", name="revisore", id="r1"),
                AIMessage("completa", id="a3")]
    assert messaggi_da_pulire(messaggi) == ["a2", "r1"]


# cronologia di n turni da 2 messaggi (domanda e risposta)
def _turni(n):
    messaggi = []
    for i in range(n):
        messaggi += [HumanMessage(f"domanda {i}"), AIMessage(f"risposta {i}")]
    return messaggi


# Verifica che sotto la soglia il nodo non chiami il modello del riassunto e lo scriva nel log.
def test_sotto_la_soglia_nessuna_chiamata(log):
    riassunto_llm = RiassuntoFinto(["x"])
    _esegui(ModelloFinto([AIMessage("ok")]), RouterFinto([IN_AMBITO]), cronologia=_turni(2),
            riassunto_llm=riassunto_llm)
    assert riassunto_llm.chiamate == []
    assert "5 messaggi, soglia 16: nessun riassunto" in log.text


# Verifica che sopra la soglia i messaggi vecchi diventino il riassunto (log prima e dopo).
def test_sopra_la_soglia_riassume(log):
    out = _esegui(ModelloFinto([AIMessage("ok")]), RouterFinto([IN_AMBITO]),
                  cronologia=_turni(9), riassunto_llm=RiassuntoFinto(["nuovo riassunto"]))
    assert "messaggi prima 19, dopo 7 (riassunti 12)" in log.text
    assert 'nuovo riassunto: "nuovo riassunto"' in log.text
    assert out["riassunto"] == "nuovo riassunto"
    assert out["messages"][0].content == "domanda 6"  # i turni 0-5 sono stati riassunti


# Verifica che il nuovo riassunto parta dal vecchio e lo sostituisca, senza accumularli.
def test_secondo_riassunto_parte_dal_vecchio():
    riassunto_llm = RiassuntoFinto(["Si chiama Luigi e ha chiesto l'ora."])
    out = _esegui(ModelloFinto([AIMessage("ok")]), RouterFinto([IN_AMBITO]),
                  cronologia=_turni(9), riassunto="Si chiama Luigi.",
                  riassunto_llm=riassunto_llm)
    assert "Riassunto precedente: Si chiama Luigi." in riassunto_llm.chiamate[0][1].content
    assert out["riassunto"] == "Si chiama Luigi e ha chiesto l'ora."


# Verifica che il nome detto al primo turno arrivi all'agente dopo la compressione: un solo
# SystemMessage con il riassunto e nessun messaggio del primo turno.
def test_nome_usato_dopo_la_compressione():
    cronologia = [HumanMessage("Mi chiamo Luigi"), AIMessage("Piacere Luigi!")] + _turni(8)
    agente = ModelloFinto([AIMessage("Luigi, sono le 10")])
    _esegui(agente, RouterFinto([IN_AMBITO]), cronologia=cronologia,
            riassunto_llm=RiassuntoFinto(["L'utente si chiama Luigi."]))
    ricevuti = agente.chiamate[0]
    sistema = [m for m in ricevuti if isinstance(m, SystemMessage)]
    assert len(sistema) == 1 and "L'utente si chiama Luigi." in sistema[0].content
    assert "Riassunto della conversazione precedente: " in sistema[0].content
    assert "Mi chiamo Luigi" not in [m.content for m in ricevuti]


# Verifica che un riassunto vuoto non tolga nessun messaggio.
def test_riassunto_vuoto_conserva_i_messaggi(log):
    out = _esegui(ModelloFinto([AIMessage("ok")]), RouterFinto([IN_AMBITO]),
                  cronologia=_turni(9), riassunto_llm=RiassuntoFinto([""]))
    assert out["messages"][0].content == "domanda 0"
    assert "riassunto non riuscito (risposta vuota): messaggi conservati" in log.text


# Verifica che il riassunto si faccia anche prima di una domanda fuori ambito.
def test_riassunto_anche_prima_di_un_rifiuto():
    out = _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]), cronologia=_turni(9),
                  riassunto_llm=RiassuntoFinto(["riassunto"]))
    assert out["riassunto"] == "riassunto"
    assert out["messages"][-1].content == AMBITO.rifiuto


# Verifica che LM Studio irraggiungibile durante il riassunto salga al chiamante.
def test_errore_di_connessione_nel_riassunto_sale():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with pytest.raises(APIConnectionError):
        _esegui(ModelloFinto([AIMessage("x")]), RouterFinto([IN_AMBITO]),
                cronologia=_turni(9), riassunto_llm=RiassuntoFinto([errore]))


# Verifica che completa_fuso riempia il fuso assente, vuoto o di soli spazi, con lo stesso id.
@pytest.mark.parametrize("argomenti", [{}, {"fuso": ""}, {"fuso": "  "}, {"fuso": None},
                                       {"parte": "ora"}])
def test_completa_fuso_vuoto_e_spazi(argomenti):
    msg = AIMessage("", tool_calls=[{"name": "tooltime", "args": argomenti, "id": "c1"}], id="m1")
    nuovo = completa_fuso(msg, "America/New_York")
    assert nuovo.id == "m1"
    assert nuovo.tool_calls[0]["args"]["fuso"] == "America/New_York"
    # gli altri argomenti restano
    assert all(nuovo.tool_calls[0]["args"][k] == v for k, v in argomenti.items() if k != "fuso")


# Verifica che un fuso esplicito resti com'e' (nessuna copia).
def test_completa_fuso_esplicito_invariato():
    msg = AIMessage("", tool_calls=[_chiamata()], id="m1")
    assert completa_fuso(msg, "America/New_York") is None


# Verifica l'evidenza: tooltime senza fuso riceve il fuso delle preferenze, scritto nel log.
def test_tooltime_senza_fuso_usa_le_preferenze(log):
    registro = []
    chiamata = {"name": "tooltime", "args": {}, "id": "c1"}
    agente = ModelloFinto([AIMessage("", tool_calls=[chiamata]), AIMessage("Sono le 6 a New York")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), registro=registro, fuso="America/New_York")
    assert registro[0]["fuso"] == "America/New_York"
    assert "tooltime senza fuso: uso America/New_York (preferenze)" in log.text
    # nella cronologia la chiamata ha il fuso completato e un solo ToolMessage la segue
    chiamate = [m for m in out["messages"] if isinstance(m, AIMessage) and m.tool_calls]
    assert len(chiamate) == 1 and chiamate[0].tool_calls[0]["args"]["fuso"] == "America/New_York"
    risultati = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(risultati) == 1 and risultati[0].content.startswith("New York: ")


# Verifica che l'agente riceva un solo SystemMessage: blocco in cima, riassunto in fondo.
def test_un_solo_system_message_con_blocco_e_riassunto():
    agente = ModelloFinto([AIMessage("Ciao")])
    prompt = prompt_agente(Preferenze("inglese", "America/New_York", "sintetico"), True)
    _esegui(agente, RouterFinto([IN_AMBITO]), riassunto="L'utente si chiama Luigi.",
            system_prompt=prompt)
    sistemi = [m for m in agente.chiamate[0] if isinstance(m, SystemMessage)]
    assert len(sistemi) == 1
    assert sistemi[0].content.startswith("Preferenze dell'utente")
    assert sistemi[0].content.endswith("L'utente si chiama Luigi.")


# Verifica che senza strumenti (server MCP non partito) una chiamata del modello non faccia
# cadere la chat: riceve un ToolMessage d'errore e il modello risponde.
def test_chiamata_senza_strumenti_non_cade():
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]),
                           AIMessage("L'orologio non è disponibile.")])
    grafo = build_graph(agente, RouterFinto([IN_AMBITO]), RevisoreFinto([OK]),
                        RiassuntoFinto(["riassunto"]), AMBITO, strumenti=())
    out = grafo.invoke({"messages": [HumanMessage("Che ore sono?")], "steps": 0,
                        "revisioni": 0, "riassunto": ""})
    errori = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(errori) == 1 and errori[0].status == "error"
    assert "non disponibile" in errori[0].content
    assert out["messages"][-1].content == "L'orologio non è disponibile."


# Verifica che il messaggio di un prompt MCP (step 5) passi dal grafo come una domanda:
# router, agente e revisore lo ricevono, e la risposta dell'agente chiude il turno.
def test_messaggio_di_prompt_passa_da_router_agente_e_revisore(log):
    from mcp_assistente.server import LIVELLI
    testo = f"Spiegami MCP. {LIVELLI['base']}"
    agente = ModelloFinto([AIMessage("MCP collega un modello agli strumenti.")])
    router = RouterFinto([IN_AMBITO])
    revisore = RevisoreFinto([OK])
    out = _esegui(agente, router, testo, revisore=revisore)
    assert out["messages"][-1].content == "MCP collega un modello agli strumenti."
    # il router riceve il testo del prompt come ultima domanda
    assert router.chiamate[0][-1].content == testo
    assert len(agente.chiamate) == 1 and agente.chiamate[0][-1].content == testo
    # il revisore controlla la risposta contro il testo del prompt
    assert len(revisore.chiamate) == 1 and testo in revisore.chiamate[0][-1].content



# Verifica che il log del router mostri anche l'argomento scelto.
def test_log_del_router_con_argomento(log):
    decisione = DecisioneRouter(categoria="conversazione", motivo="ora", argomento="ora_data_fusi")
    _esegui(ModelloFinto([AIMessage("Sono le 10")]), RouterFinto([decisione]))
    assert 'categoria=conversazione motivo="ora" → agente (argomento ora_data_fusi)' in log.text


# --- step 6: argomento del router nello stato, testi fissi degli strumenti come costanti ---

# Verifica che l'argomento scelto dal router arrivi nello stato finale (lo restituisce l'API).
@pytest.mark.parametrize("decisione,atteso", [
    (DecisioneRouter(categoria="conversazione", motivo="ora", argomento="ora_data_fusi"),
     "ora_data_fusi"),
    (DecisioneRouter(categoria="fuori_ambito", motivo="ricetta", argomento="altro"), "altro"),
    (None, None),  # output non valido del router: nessun argomento
])
def test_argomento_nello_stato(decisione, atteso):
    out = _esegui(ModelloFinto([AIMessage("Ciao")]), RouterFinto([decisione]))
    assert out["argomento"] == atteso


# Verifica che i testi dei ToolMessage non eseguiti siano le costanti del grafo.
def test_testi_fissi_come_costanti():
    from app.graph import MSG_NON_DISPONIBILE, MSG_NON_ESEGUITA
    agente = ModelloFinto([AIMessage("", tool_calls=[_chiamata()])])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), max_steps=1)
    chiuse = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert chiuse[-1].content == MSG_NON_ESEGUITA
    grafo = build_graph(ModelloFinto([AIMessage("", tool_calls=[_chiamata()]), AIMessage("ok")]),
                        RouterFinto([IN_AMBITO]), RevisoreFinto([OK]), RiassuntoFinto(["r"]),
                        AMBITO, strumenti=())
    out = grafo.invoke({"messages": [HumanMessage("Che ore sono?")], "steps": 0, "revisioni": 0,
                        "riassunto": ""})
    assert [m.content for m in out["messages"] if isinstance(m, ToolMessage)] == \
        [MSG_NON_DISPONIBILE]


# --- lezione 8, esercizio 2: controllo delle citazioni a fine turno ---

# chiamata a search_documents come la scriverebbe il modello
def _cerca(id_="s1"):
    return {"name": "search_documents", "args": {"query": "gnocchi di patate"}, "id": id_}


# strumenti dei test delle citazioni: ricerca finta (passaggi R89-1, R89-2) e orologio
def _con_ricerca():
    return [search_documents_finto([]), tooltime_finto([])]


# righe del logger citazioni con il loro livello
def _citazioni(log):
    return [(r.levelname, r.getMessage()) for r in log.records if r.name == "citazioni"]


# Verifica la citazione valida: ricerca chiamata, id citato tra quelli ricevuti, riga INFO.
def test_citazione_valida(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_cerca()]), AIMessage("Patate e farina [R89-1].")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), domanda="Gnocchi?", strumenti=_con_ricerca())
    assert _citazioni(log) == [("INFO", "verificate=R89-1 sconosciute=- ricerche=1 passaggi=2")]
    assert out["messages"][-1].content == "Patate e farina [R89-1]."


# Verifica la citazione sconosciuta: riga WARNING, risposta del modello invariata (solo log).
def test_citazione_sconosciuta(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_cerca()]), AIMessage("Farina [R999-1].")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), domanda="Gnocchi?", strumenti=_con_ricerca())
    assert _citazioni(log) == [("WARNING", "verificate=- sconosciute=R999-1 ricerche=1 passaggi=2")]
    assert out["messages"][-1].content == "Farina [R999-1]."


# Verifica la risposta senza strumenti: nessuna citazione, nessuna ricerca.
def test_nessuna_citazione_senza_ricerca(log):
    _esegui(ModelloFinto([AIMessage("Ciao!")]), RouterFinto([IN_AMBITO]), domanda="Ciao",
            strumenti=_con_ricerca())
    assert _citazioni(log) == [("INFO", "verificate=- sconosciute=- ricerche=0 passaggi=0")]


# Verifica che contino solo i passaggi del turno: un id ricevuto nel turno precedente è sconosciuto.
def test_id_del_turno_precedente_sconosciuto(log):
    primo = ModelloFinto([AIMessage("", tool_calls=[_cerca()]), AIMessage("Patate [R89-1].")])
    out = _esegui(primo, RouterFinto([IN_AMBITO]), domanda="Gnocchi?", strumenti=_con_ricerca())
    log.clear()
    _esegui(ModelloFinto([AIMessage("Come detto, patate [R89-1].")]), RouterFinto([IN_AMBITO]),
            domanda="E quindi?", cronologia=out["messages"], strumenti=_con_ricerca())
    assert _citazioni(log) == [("WARNING", "verificate=- sconosciute=R89-1 ricerche=0 passaggi=0")]


# Verifica che una ricerca non eseguita (limite di passaggi) non conti come ricerca.
def test_chiamata_non_eseguita_non_conta(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_cerca()])])
    _esegui(agente, RouterFinto([IN_AMBITO]), domanda="Gnocchi?", max_steps=0, strumenti=_con_ricerca())
    assert _citazioni(log) == [("INFO", "verificate=- sconosciute=- ricerche=0 passaggi=0")]


# Verifica che il rifiuto del router non passi dal controllo delle citazioni.
def test_rifiuto_senza_riga_citazioni(log):
    _esegui(ModelloFinto([AIMessage("mai")]), RouterFinto([FUORI]), strumenti=_con_ricerca())
    assert _citazioni(log) == []


# finto search_documents che fallisce come il tool vero (errore del tool restituito al modello come testo)
def _ricerca_in_errore():
    from langchain_core.tools import ToolException, tool

    @tool("search_documents")
    def search_documents(query: str, top_k: int = 5, capitolo: str = "") -> str:
        """Ricerca finta che risponde sempre con un errore del tool."""
        raise ToolException("capitolo 'DOLCI' sconosciuto")
    # come i tool dell'adattatore MCP: l'errore diventa un messaggio per il modello
    search_documents.handle_tool_error = True
    return search_documents


# Verifica (revisione finale) un errore di search_documents attraverso il ToolNode: conta come ricerca,
# nessun passaggio ricevuto.
def test_errore_della_ricerca_nel_grafo(log):
    agente = ModelloFinto([AIMessage("", tool_calls=[_cerca()]), AIMessage("Non trovo nulla.")])
    _esegui(agente, RouterFinto([IN_AMBITO]), domanda="Dolci?", strumenti=[_ricerca_in_errore()])
    assert _citazioni(log) == [("INFO", "verificate=- sconosciute=- ricerche=1 passaggi=0")]


# Verifica (revisione finale) una chiamata a un tool che il grafo non ha (server non partito): risposta
# «non disponibile» come senza server, non l'errore di LangGraph; gli altri tool vengono eseguiti.
def test_tool_mancante_non_disponibile(log):
    chiamate = [{"name": "tooltime", "args": {"fuso": "Asia/Tokyo"}, "id": "t1"}, _cerca("s1")]
    agente = ModelloFinto([AIMessage("", tool_calls=chiamate), AIMessage("Patate [R89-1].")])
    out = _esegui(agente, RouterFinto([IN_AMBITO]), domanda="Ora e gnocchi?",
                  strumenti=[search_documents_finto([])])
    risposte = {m.name: m for m in out["messages"] if isinstance(m, ToolMessage)}
    assert risposte["tooltime"].content == MSG_NON_DISPONIBILE and risposte["tooltime"].status == "error"
    assert "R89-1" in risposte["search_documents"].content
    assert _citazioni(log) == [("INFO", "verificate=R89-1 sconosciute=- ricerche=1 passaggi=2")]
