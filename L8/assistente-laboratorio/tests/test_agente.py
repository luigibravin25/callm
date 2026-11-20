# test del modulo dell'agente (step 6): turno senza stato, strumenti del turno, prompt, avvio MCP
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from openai import APIStatusError, LengthFinishReasonError

from app import adattatore_mcp
from app.adattatore_mcp import ErroreMCP, PromptNonValido
from app.agente import Agente, prepara, strumenti_del_turno
from app.config import Ambito, Settings
from app.graph import MSG_NON_DISPONIBILE, MSG_NON_ESEGUITA, build_graph
from app.info_prompt import InfoArgomento, InfoPrompt
from app.revisore import DecisioneRevisore
from app.router import DecisioneRouter
from mcp_assistente import orologio as modulo_orologio
from tests.finti import (ModelloFinto, RevisoreFinto, RiassuntoFinto, RouterFinto, search_documents_finto,
                         tooltime_finto)

AMBITO = Ambito(descrizione="Solo ora.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="ora", argomento="ora_data_fusi")
OK = DecisioneRevisore(motivo="risponde", coerente=True)
SPIEGA = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                          InfoArgomento("livello", False)))
IMPOSTAZIONI = Settings(base_url="http://127.0.0.1:1234/v1", model="google/gemma-4-e2b",
                        max_steps=5, fuso_predefinito="Europe/Rome", ambito_file=None)


# orologio fisso: 1 marzo 2026 11:00 UTC
@pytest.fixture(autouse=True)
def orologio(monkeypatch):
    monkeypatch.setattr(modulo_orologio, "_adesso",
                        lambda: datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc))


# chiamata a tooltime come la scriverebbe il modello
def _chiamata(id_="c1", fuso="Asia/Tokyo"):
    return {"name": "tooltime", "args": {"fuso": fuso}, "id": id_}


# agente con il grafo vero e modelli finti
def _agente(modello, strumenti=True, soglia=16, recenti=6, max_steps=5, prompts=(),
            partito=True):
    grafo = build_graph(modello, RouterFinto([IN_AMBITO]), RevisoreFinto([OK]),
                        RiassuntoFinto(["riassunto"]), AMBITO, max_steps=max_steps,
                        soglia_riassunto=soglia, messaggi_recenti=recenti,
                        strumenti=[tooltime_finto([])] if strumenti else ())
    return Agente(grafo=grafo, prompts=list(prompts), mcp_partito=partito,
                  strumenti=("tooltime",) if strumenti else (), motivo_mcp="")


# Verifica un turno con tooltime: risposta, strumento con argomenti, categoria e argomento.
def test_turno_con_strumento():
    agente = _agente(ModelloFinto([AIMessage("", tool_calls=[_chiamata()]),
                                   AIMessage("A Tokyo sono le 20")]))
    esito = agente.turno([HumanMessage("Che ore sono a Tokyo?")], [], "")
    assert esito.risposta == "A Tokyo sono le 20"
    assert esito.strumenti_usati == [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]
    assert (esito.categoria, esito.argomento) == ("conversazione", "ora_data_fusi")
    assert isinstance(esito.messaggi[-1], AIMessage) and esito.riassunto == ""


# Verifica che l'agente sia senza stato: il secondo turno vede solo la cronologia che riceve.
def test_senza_stato():
    modello = ModelloFinto([AIMessage("ok")])
    agente = _agente(modello)
    agente.turno([HumanMessage("Mi chiamo Anna")], [], "")
    agente.turno([HumanMessage("Come mi chiamo?")], [], "")
    testi = [m.content for m in modello.chiamate[-1]]
    assert "Mi chiamo Anna" not in testi and "Come mi chiamo?" in testi


# Verifica che una tool_call gia' nella cronologia non conti, anche dopo un riassunto.
def test_strumenti_dopo_riassunto():
    vecchia = [HumanMessage("Che ore sono a Lima?"),
               AIMessage("", tool_calls=[_chiamata("vecchio", "America/Lima")]),
               ToolMessage("05:00", tool_call_id="vecchio", name="tooltime"),
               AIMessage("A Lima sono le 5")]
    modello = ModelloFinto([AIMessage("", tool_calls=[_chiamata("nuovo")]),
                            AIMessage("A Tokyo sono le 20")])
    esito = _agente(modello, soglia=4, recenti=2).turno(
        [HumanMessage("E a Tokyo?")], vecchia * 2, "")
    assert esito.riassunto == "riassunto"
    assert esito.strumenti_usati == [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]


# Verifica che chiamate chiuse dal limite o senza server MCP non contino.
def test_limite_e_non_disponibile_non_contano():
    # due chiamate con id diversi: la prima eseguita, la seconda chiusa dal limite
    modello = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]),
                            AIMessage("", tool_calls=[_chiamata("c2", "Europe/London")])])
    esito = _agente(modello, max_steps=1).turno([HumanMessage("Che ore sono?")], [], "")
    assert MSG_NON_ESEGUITA in [m.content for m in esito.messaggi]
    assert esito.strumenti_usati == [{"nome": "tooltime", "argomenti": {"fuso": "Asia/Tokyo"}}]
    modello = ModelloFinto([AIMessage("", tool_calls=[_chiamata()]), AIMessage("niente")])
    esito = _agente(modello, strumenti=False).turno([HumanMessage("Che ore sono?")], [], "")
    assert MSG_NON_DISPONIBILE in [m.content for m in esito.messaggi]
    assert esito.strumenti_usati == []


# Verifica strumenti_del_turno direttamente: esclude il limite (eseguita la prima, non la seconda).
def test_strumenti_del_turno_esclude_non_eseguite():
    uscita = [HumanMessage("x"),
              AIMessage("", tool_calls=[_chiamata("a")]),
              ToolMessage("20:00", tool_call_id="a", name="tooltime"),
              AIMessage("", tool_calls=[_chiamata("b", "Europe/London")]),
              ToolMessage(MSG_NON_ESEGUITA, tool_call_id="b", name="tooltime")]
    assert strumenti_del_turno([], uscita) == [{"nome": "tooltime",
                                               "argomenti": {"fuso": "Asia/Tokyo"}}]


# Verifica i prompt: server non partito, prompt sconosciuto, argomento mancante, mai prompts/get.
@pytest.mark.parametrize("partito,nome,argomenti,errore,testo", [
    (False, "spiega", {"argomento": "MCP"}, ErroreMCP, "non partito"),
    (True, "boh", {}, PromptNonValido, "Prompt sconosciuto"),
    (True, "spiega", {}, PromptNonValido, "argomento"),
])
def test_prompt_non_validi(monkeypatch, partito, nome, argomenti, errore, testo):
    chiamate = []
    monkeypatch.setattr(adattatore_mcp, "ottieni_prompt", lambda *a: chiamate.append(a))
    agente = _agente(ModelloFinto([AIMessage("ok")]), prompts=[SPIEGA], partito=partito)
    with pytest.raises(errore, match=testo):
        agente.messaggi_prompt(nome, argomenti)
    assert chiamate == []


# Verifica che un prompt valido passi a prompts/get e restituisca i messaggi.
def test_prompt_valido(monkeypatch):
    monkeypatch.setattr(adattatore_mcp, "ottieni_prompt",
                        lambda nome, argomenti: [HumanMessage(f"{nome} {argomenti}")])
    agente = _agente(ModelloFinto([AIMessage("ok")]), prompts=[SPIEGA])
    messaggi = agente.messaggi_prompt("spiega", {"argomento": "MCP"})
    assert messaggi[0].content == "spiega {'argomento': 'MCP'}"


# --- avvio (prepara): server MCP, preferenze, strumenti al modello ---

# sostituisce server MCP e modelli di LM Studio; registra gli strumenti dati a build_llm
# lezione 8: `ricerca` = tool restituiti dalla discovery del server di ricerca (predefinito nessuno);
# `modelli` raccoglie i modelli finti creati, per leggere il prompt di sistema che ricevono
def _finti_per_avvio(monkeypatch, server_ok=True, ricerca=(), modelli=None):
    from app import llm
    ricevuti = []

    # discovery finta: un tooltime finto, oppure il server che non parte
    def carica():
        if not server_ok:
            raise ErroreMCP("mcp_assistente.server: non parte")
        return [tooltime_finto([])]

    # build_llm finto: registra la lista degli strumenti ricevuti
    def build_llm(settings, strumenti):
        ricevuti.append(list(strumenti))
        modello = ModelloFinto([AIMessage("ok")])
        if modelli is not None:
            modelli.append(modello)
        return modello

    monkeypatch.setattr(adattatore_mcp, "carica_strumenti", carica)
    monkeypatch.setattr(adattatore_mcp, "carica_strumenti_ricerca", lambda: list(ricerca))
    monkeypatch.setattr(adattatore_mcp, "leggi_preferenze", lambda: '{"lingua": "inglese"}')
    monkeypatch.setattr(adattatore_mcp, "elenca_prompt", lambda: [SPIEGA])
    monkeypatch.setattr(llm, "build_llm", build_llm)
    monkeypatch.setattr(llm, "build_router_llm", lambda s, a: RouterFinto([IN_AMBITO]))
    monkeypatch.setattr(llm, "build_revisore_llm", lambda s: RevisoreFinto([OK]))
    monkeypatch.setattr(llm, "build_riassunto_llm", lambda s: RiassuntoFinto(["riassunto"]))
    return ricevuti


# Verifica l'avvio con il server: strumenti, prompt, stato MCP e un turno che funziona.
def test_prepara_con_server(monkeypatch):
    _finti_per_avvio(monkeypatch)
    agente = prepara(IMPOSTAZIONI, AMBITO)
    assert agente.mcp_partito and agente.strumenti == ("tooltime",)
    assert agente.prompts == [SPIEGA]
    assert agente.turno([HumanMessage("Ciao")], [], "").risposta == "ok"


# Verifica (minore 10 dello step 4): server non partito = un solo avviso sul server, nessun
# avviso sulla resource, preferenze predefinite con la fonte nel log.
def test_prepara_server_non_partito(monkeypatch, caplog):
    _finti_per_avvio(monkeypatch, server_ok=False)
    caplog.set_level(logging.INFO)
    agente = prepara(IMPOSTAZIONI, AMBITO)
    assert not agente.mcp_partito and agente.strumenti == () and agente.prompts == []
    assert "non parte" in agente.motivo_mcp
    testi = [r.getMessage() for r in caplog.records]
    assert not any("resource non disponibile" in t for t in testi)
    assert any("server MCP non disponibile" in t for t in testi)
    assert any("(predefinite)" in t for t in testi)


# Verifica (minore 11 dello step 4): al modello arrivano solo tool, mai la resource.
def test_bind_tools_solo_tool(monkeypatch):
    ricevuti = _finti_per_avvio(monkeypatch)
    prepara(IMPOSTAZIONI, AMBITO)
    assert len(ricevuti) == 1
    assert all(isinstance(t, BaseTool) for t in ricevuti[0])
    assert [t.name for t in ricevuti[0]] == ["tooltime"]


# --- messaggi degli errori del modello (minore 7 dello step 1) ---

# errore HTTP finto di LM Studio con il codice dato
def _errore_http(codice):
    richiesta = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
    return APIStatusError("errore", response=httpx.Response(codice, request=richiesta), body=None)


# Verifica i consigli per 400 e 404 e il testo per LengthFinishReasonError.
def test_messaggi_errore():
    from app.errori import messaggio_errore_generico, messaggio_errore_http
    assert "Context Length" in messaggio_errore_http(_errore_http(400))
    assert "LM_MODEL" in messaggio_errore_http(_errore_http(404))
    assert "token" in messaggio_errore_generico(LengthFinishReasonError(completion=SimpleNamespace(usage=None)))


# --- lezione 8, esercizio 2: avvio con il server di ricerca ---

# prompt di sistema ricevuto dal modello finto alla prima chiamata
def _prompt_di_sistema(modello) -> str:
    return str(modello.chiamate[0][0].content)


# Verifica l'avvio con entrambi i server: tutti i tool, stato MCP dell'assistente, istruzioni di ricerca.
def test_prepara_con_ricerca(monkeypatch):
    from app.llm import FRASI_RICERCA
    modelli = []
    _finti_per_avvio(monkeypatch, ricerca=[search_documents_finto([])], modelli=modelli)
    agente = prepara(IMPOSTAZIONI, AMBITO)
    assert agente.strumenti == ("tooltime", "search_documents") and agente.mcp_partito
    agente.turno([HumanMessage("Ciao")], [], "")
    assert FRASI_RICERCA in _prompt_di_sistema(modelli[0])


# Verifica l'avvio con la sola ricerca: stato MCP «non partito» (assistente), prompt senza orologio.
def test_prepara_solo_ricerca(monkeypatch):
    from app.llm import FRASE_SENZA_STRUMENTI, FRASI_RICERCA
    modelli = []
    _finti_per_avvio(monkeypatch, server_ok=False, ricerca=[search_documents_finto([])], modelli=modelli)
    agente = prepara(IMPOSTAZIONI, AMBITO)
    assert not agente.mcp_partito and agente.strumenti == ("search_documents",)
    agente.turno([HumanMessage("Ciao")], [], "")
    prompt = _prompt_di_sistema(modelli[0])
    assert FRASE_SENZA_STRUMENTI in prompt and FRASI_RICERCA in prompt


# Verifica (revisione finale) l'avvio senza server di ricerca: il modello riceve la frase del ricettario
# non disponibile e non le istruzioni di ricerca.
def test_prepara_senza_ricerca(monkeypatch):
    from app.llm import FRASE_SENZA_RICERCA, FRASI_RICERCA
    modelli = []
    _finti_per_avvio(monkeypatch, modelli=modelli)
    agente = prepara(IMPOSTAZIONI, AMBITO)
    assert agente.strumenti == ("tooltime",)
    agente.turno([HumanMessage("Ciao")], [], "")
    prompt = _prompt_di_sistema(modelli[0])
    assert FRASE_SENZA_RICERCA in prompt and FRASI_RICERCA not in prompt


# --- lezione 8, esercizio 4: fasce di affidabilità ---

# Verifica la frase sulle fasce in coda alle istruzioni della ricerca (testo approvato nella specifica, §10).
def test_frase_delle_fasce_nelle_istruzioni():
    from app.llm import FRASI_RICERCA
    # ritocco dopo la prova reale (gemma non dichiarava la verifica): una frase fissa in fondo alla risposta
    assert "anche un solo passaggio con affidabilita «media»" in FRASI_RICERCA
    # ritocco 2: un esempio concreto (come per le citazioni nell'esercizio 2)
    assert ("termina la risposta con la frase «Da verificare sulla fonte.», per esempio: «Si usa vino rosso "
            "[R208-1]. Da verificare sulla fonte.»") in FRASI_RICERCA
    assert "lista di passaggi vuota" in FRASI_RICERCA and FRASI_RICERCA.endswith("non citare nessun id.")
    # ritocco approvato dopo la prova nel browser: gemma scriveva «(affidabile)» accanto alle citazioni
    assert ("Non scrivere nella risposta il valore del campo affidabilita; per i passaggi affidabili non "
            "aggiungere nulla.") in FRASI_RICERCA
