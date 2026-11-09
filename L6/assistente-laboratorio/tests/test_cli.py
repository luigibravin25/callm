# test della CLI: chat da terminale con grafo reale e modelli finti
import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import APIConnectionError

from app import cli
from app.cli import MSG_CONNESSIONE, main
from app.config import Ambito
from app.graph import build_graph
from app.router import DecisioneRouter
from app.revisore import DecisioneRevisore
from tests.finti import ModelloFinto, RevisoreFinto, RouterFinto

AMBITO = Ambito(descrizione="Solo ora.", rifiuto="Fuori dal mio ambito.")
IN_AMBITO = DecisioneRouter(categoria="conversazione", motivo="ora")
FUORI = DecisioneRouter(categoria="fuori_ambito", motivo="ricetta")
OK = DecisioneRevisore(motivo="risponde", coerente=True)


# esegue la chat con le righe date e restituisce cio' che e' stato stampato
def _chat(righe, agente, router, revisore=None):
    input_righe = iter(righe)

    # finto input(): restituisce le righe in ordine, poi EOF come Ctrl+Z
    def leggi(_prompt=""):
        try:
            return next(input_righe)
        except StopIteration:
            raise EOFError

    stampato = []
    revisore = revisore or RevisoreFinto([OK])
    main(build_graph(agente, router, revisore, AMBITO), input_fn=leggi,
         output_fn=stampato.append)
    return "\n".join(stampato)


# Verifica che la CLI mostri la risposta dell'agente a una domanda in ambito.
def test_domanda_in_ambito_e_risposta():
    out = _chat(["Che ore sono?", "esci"], ModelloFinto([AIMessage("Sono le 10")]),
                RouterFinto([IN_AMBITO]))
    assert "Assistente: Sono le 10" in out


# Verifica che la CLI mostri la frase di rifiuto del file dell'ambito.
def test_domanda_fuori_ambito_rifiutata():
    out = _chat(["Carbonara?", "esci"], ModelloFinto([AIMessage("x")]), RouterFinto([FUORI]))
    assert "Assistente: " + AMBITO.rifiuto in out


# Verifica che il secondo turno riceva la cronologia del primo.
def test_cronologia_passata_al_turno_successivo():
    agente = ModelloFinto([AIMessage("Sono le 10"), AIMessage("Prego")])
    _chat(["Che ore sono?", "grazie", "esci"], agente, RouterFinto([IN_AMBITO]))
    testi = [m.content for m in agente.chiamate[1]]
    assert "Che ore sono?" in testi and "Sono le 10" in testi and "grazie" in testi


# Verifica LM Studio spento durante il router: messaggio, domanda fuori dalla cronologia,
# chat aperta.
def test_connessione_assente_durante_il_router():
    errore = APIConnectionError(request=httpx.Request("POST", "http://x"))
    agente = ModelloFinto([AIMessage("Risposta a b")])
    out = _chat(["a", "b", "esci"], agente, RouterFinto([errore, IN_AMBITO]))
    assert MSG_CONNESSIONE in out
    assert "Assistente: Risposta a b" in out
    # la domanda fallita non entra nella cronologia
    assert "a" not in [m.content for m in agente.chiamate[0]]


# Verifica l'uscita con EXIT (maiuscole indifferenti) e con la fine dell'input.
@pytest.mark.parametrize("righe", [["EXIT"], []])
def test_uscita_con_exit_e_eof(righe):
    agente = ModelloFinto([AIMessage("x")])
    _chat(righe, agente, RouterFinto([IN_AMBITO]))  # [] = EOF subito
    assert agente.chiamate == []


# Verifica che LOG_HTTP spento zittisca sia httpx sia httpx2.
def test_log_http_spegne_httpx_e_httpx2():
    # il client OpenAI scrive le richieste dal logger httpx2 (visto con LM Studio vero)
    import logging
    cli.imposta_log(log_http=False, log_grafo=True)
    assert logging.getLogger("httpx").level == logging.CRITICAL
    assert logging.getLogger("httpx2").level == logging.CRITICAL
    cli.imposta_log()  # rimette i valori predefiniti


# Verifica che l'avvio con configurazione mancante si fermi con un messaggio chiaro.
def test_configurazione_non_valida(monkeypatch):
    monkeypatch.delenv("LM_BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="Configurazione non valida"):
        cli.avvia()


# Verifica che dopo un rifiuto del revisore l'utente veda solo la risposta finale e che il turno
# successivo non riceva il messaggio [Revisore] ne' la bozza.
def test_turno_successivo_senza_revisore():
    no = DecisioneRevisore(motivo="parziale", coerente=False)
    agente = ModelloFinto([AIMessage("bozza"), AIMessage("completa"), AIMessage("prego")])
    out = _chat(["domanda", "grazie", "esci"], agente, RouterFinto([IN_AMBITO]),
                RevisoreFinto([no, OK, OK]))
    assert "Assistente: completa" in out
    assert "[Revisore]" not in out and "bozza" not in out
    secondo_turno = agente.chiamate[2]
    assert all(getattr(m, "name", None) != "revisore" for m in secondo_turno)
    assert "bozza" not in [m.content for m in secondo_turno]


# Verifica che i log del revisore siano accesi con LOG_GRAFO.
def test_imposta_log_accende_il_revisore():
    import logging
    cli.imposta_log()
    assert logging.getLogger("revisore").level == logging.INFO
