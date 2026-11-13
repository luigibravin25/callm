"""Agente senza interfaccia (step 6): avvio del server MCP, grafo, un turno, prompt.

Lo usa il servizio HTTP (app/api.py). Nessuna dipendenza da FastAPI e nessuno stato della
conversazione: cronologia e riassunto arrivano a ogni turno e tornano aggiornati.
"""
# librerie standard: log, classi di dati, tipi
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Callable

# messaggi della conversazione
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

# parti del progetto: configurazione, controllo degli argomenti dei prompt, tipi dei prompt
from app.comandi import MSG_PROMPT_SCONOSCIUTO, controlla_argomenti
from app.config import Ambito, Settings
from app.info_prompt import InfoPrompt
from app.sse import Evento

# logger dell'avvio MCP: nel terminale compare come [mcp]
log = logging.getLogger("mcp")

# stesso testo usato da /stato (app/stato.py)
from app.stato import MSG_MCP_NON_PARTITO  # noqa: E402


# risultato di un turno, pronto per la risposta dell'API
@dataclass
class EsitoTurno:
    messaggi: list[BaseMessage]  # cronologia aggiornata (gia' ridotta dal riassunto)
    riassunto: str
    risposta: str  # testo dell'ultimo messaggio
    strumenti_usati: list[dict]  # [{"nome": ..., "argomenti": {...}}] eseguiti in questo turno
    categoria: str
    argomento: str | None


# strumenti eseguiti in questo turno: chiamate nuove (id non in ingresso) con una risposta vera
def strumenti_del_turno(ingresso: list[BaseMessage], uscita: list[BaseMessage]) -> list[dict]:
    # import qui: graph importa i modelli; i testi fissi servono solo in questa funzione
    from app.graph import MSG_NON_DISPONIBILE, MSG_NON_ESEGUITA
    # id delle chiamate gia' presenti nella cronologia ricevuta (il riassunto puo' toglierne:
    # per questo si confrontano gli id, non le posizioni)
    vecchie = {c["id"] for m in ingresso if isinstance(m, AIMessage) for c in m.tool_calls}
    # risposta di ogni chiamata, per escludere quelle non eseguite (limite, server assente)
    risposte = {m.tool_call_id: m.content for m in uscita if isinstance(m, ToolMessage)}
    usati = []
    for m in uscita:
        if not isinstance(m, AIMessage):
            continue
        for c in m.tool_calls:
            if c["id"] in vecchie or c["id"] not in risposte:
                continue
            if risposte[c["id"]] in (MSG_NON_DISPONIBILE, MSG_NON_ESEGUITA):
                continue
            usati.append({"nome": c["name"], "argomenti": dict(c["args"])})
    return usati


# ingresso del grafo per un turno: cronologia + messaggi nuovi, contatori da 0
def _ingresso(nuovi: list[BaseMessage], cronologia: list[BaseMessage], riassunto: str) -> dict:
    return {"messages": list(cronologia) + list(nuovi), "steps": 0, "revisioni": 0,
            "riassunto": riassunto}


# esito del turno dallo stato finale del grafo (uguale per invoke e per lo streaming)
def _esito(ingresso: list[BaseMessage], out: dict, riassunto: str) -> EsitoTurno:
    messaggi = out["messages"]
    return EsitoTurno(messaggi=messaggi, riassunto=out.get("riassunto", riassunto),
                      risposta=str(messaggi[-1].content),
                      strumenti_usati=strumenti_del_turno(ingresso, messaggi),
                      categoria=out.get("categoria", ""), argomento=out.get("argomento"))


# l'agente pronto: grafo, prompt del server, esito dell'avvio MCP, controlli dello stato
@dataclass
class Agente:
    grafo: object
    prompts: list[InfoPrompt]
    mcp_partito: bool
    strumenti: tuple[str, ...]
    motivo_mcp: str  # perche' il server non e' partito (vuoto se e' partito)
    verifica_modello: Callable | None = field(default=None)  # -> StatoModello (app/stato.py)
    verifica_mcp: Callable | None = field(default=None)  # -> StatoMCP (app/stato.py)
    # fuso delle preferenze (lo stesso del grafo): completa tooltime senza fuso negli eventi
    fuso_predefinito: str = "Europe/Rome"

    # un turno del grafo; gli errori di LM Studio salgono al chiamante (l'API li traduce)
    def turno(self, nuovi: list[BaseMessage], cronologia: list[BaseMessage],
              riassunto: str) -> EsitoTurno:
        out = self.grafo.invoke(_ingresso(nuovi, cronologia, riassunto))
        return _esito(list(cronologia), out, riassunto)

    # lo stesso turno in streaming (step 10): eventi del grafo, l'ultimo e' "fine" con l'EsitoTurno
    # (stesso calcolo di turno); gli errori di LM Studio risalgono dal generatore
    def turno_in_flusso(self, nuovi: list[BaseMessage], cronologia: list[BaseMessage],
                        riassunto: str) -> Iterator[Evento]:
        # import qui: il flusso serve solo allo streaming
        from app.flusso import eventi_turno
        for evento in eventi_turno(self.grafo, _ingresso(nuovi, cronologia, riassunto),
                                   self.fuso_predefinito):
            if evento.tipo == "stato_finale":
                yield Evento("fine", _esito(list(cronologia), evento.dati, riassunto))
            else:
                yield evento

    # stato dal vivo (GET /stato): i due controlli piu' strumenti e prompt caricati all'avvio
    def stato(self):
        # import qui: gli schemi servono solo a /stato
        from app.schemi import Stato
        mcp = self.verifica_mcp()
        mcp.strumenti = list(self.strumenti)
        mcp.prompt = len(self.prompts)
        return Stato(agente="ok", mcp=mcp, modello=self.verifica_modello())

    # messaggi di un prompt del server: controllo con l'elenco, poi prompts/get
    def messaggi_prompt(self, nome: str, argomenti: dict[str, str]) -> list[BaseMessage]:
        # import come modulo: i test lo possono sostituire
        from app import adattatore_mcp
        if not self.mcp_partito:
            raise adattatore_mcp.ErroreMCP(MSG_MCP_NON_PARTITO)
        info = next((p for p in self.prompts if p.nome == nome), None)
        if info is None:
            raise adattatore_mcp.PromptNonValido(MSG_PROMPT_SCONOSCIUTO.format(nome=nome))
        errore = controlla_argomenti(info, argomenti)
        if errore:
            raise adattatore_mcp.PromptNonValido(errore)
        return adattatore_mcp.ottieni_prompt(nome, argomenti)


# all'avvio del servizio: server MCP (strumenti, preferenze, prompt) e grafo, una volta
def prepara(settings: Settings, ambito: Ambito) -> Agente:
    """tools/list, resources/read e prompts/list una volta; server che non parte: nessuno
    strumento, preferenze predefinite e nessun prompt, con un avviso nel log."""
    # import qui: adattatore e llm si leggono come moduli, cosi' i test li possono sostituire
    from app import adattatore_mcp, llm
    from app.graph import build_graph
    from app.preferenze import usa_predefinite, valida
    try:
        strumenti = adattatore_mcp.carica_strumenti()
    except adattatore_mcp.ErroreMCP as errore:
        log.warning("server MCP non disponibile (%s): nessuno strumento", errore)
        # resource e prompt stanno sullo stesso server: niente lettura ne' elenco
        strumenti, preferenze, prompts = [], usa_predefinite(settings.fuso_predefinito), []
        partito, motivo = False, str(errore)
    else:
        preferenze = valida(adattatore_mcp.leggi_preferenze(), settings.fuso_predefinito)
        prompts = adattatore_mcp.elenca_prompt()
        partito, motivo = True, ""
    grafo = build_graph(llm.build_llm(settings, strumenti), llm.build_router_llm(settings, ambito),
                        llm.build_revisore_llm(settings), llm.build_riassunto_llm(settings),
                        ambito, settings.max_steps, settings.max_revisioni,
                        settings.soglia_riassunto, settings.messaggi_recenti,
                        strumenti=strumenti,
                        system_prompt=llm.prompt_agente(preferenze, bool(strumenti)),
                        fuso_predefinito=preferenze.fuso)
    # controlli dal vivo di /stato con i valori di questa configurazione
    from app.stato import verifica_mcp, verifica_modello
    return Agente(grafo=grafo, prompts=prompts, mcp_partito=partito,
                  strumenti=tuple(t.name for t in strumenti), motivo_mcp=motivo,
                  verifica_modello=lambda: verifica_modello(settings.base_url, settings.model),
                  verifica_mcp=lambda: verifica_mcp(partito),
                  fuso_predefinito=preferenze.fuso)
