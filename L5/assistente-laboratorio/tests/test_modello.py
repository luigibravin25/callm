# Test del collegamento al modello: cronologia, configurazione da variabili d'ambiente,
# errori del server LM Studio. Il modello vero e' sostituito da ModelloFinto.
# os legge RUN_LM_STUDIO; httpx e openai servono a costruire gli errori del server
import os

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage

# parti dell'app da provare: CLI, configurazione, grafo, prompt di sistema
from app.cli import ETICHETTA_ASSISTENTE, main
from app.config import load_settings
from app.graph import build_graph
from app.llm import SYSTEM_PROMPT


# Supporto: modello finto senza rete. Ogni chiamata usa la risposta successiva della lista;
# se la risposta e' un'eccezione la solleva (per simulare gli errori del server).
class ModelloFinto:
    """Modello finto: registra i messaggi ricevuti e risponde con i contenuti dati."""

    def __init__(self, risposte):
        self.risposte = list(risposte)
        # una voce per chiamata: i messaggi ricevuti, da controllare nei test
        self.chiamate = []

    def invoke(self, messaggi):
        self.chiamate.append(list(messaggi))
        r = self.risposte.pop(0)
        if isinstance(r, BaseException):
            raise r
        return AIMessage(r)


# Supporto: esegue la CLI con righe preparate e il modello dato; restituisce le uscite stampate.
def _esegui(righe, llm):
    it = iter(righe)

    # input finto: finite le righe simula la fine dell'input (EOFError)
    def input_fn(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    uscite = []
    main(input_fn=input_fn, output_fn=uscite.append, llm=llm, stream=False)
    return uscite


# Verifica che al secondo turno il modello riceva tutta la cronologia (requisito: memoria
# della sessione), con il prompt di sistema in testa.
def test_cronologia_passata_al_modello():
    llm = ModelloFinto(["Ciao Luigi", "Ti chiami Luigi"])
    uscite = _esegui(["Mi chiamo Luigi", "Come mi chiamo?", "exit"], llm)
    assert len(llm.chiamate[0]) == 2  # prompt di sistema + domanda
    assert [m.content for m in llm.chiamate[1]] == [
        SYSTEM_PROMPT, "Mi chiamo Luigi", "Ciao Luigi", "Come mi chiamo?"]
    assert ETICHETTA_ASSISTENTE + "Ti chiami Luigi" in uscite


# Verifica che senza LM_MODEL o LM_BASE_URL l'app si fermi con un errore che nomina la variabile.
def test_config_mancante(monkeypatch):
    # primo caso: manca LM_MODEL
    monkeypatch.setenv("LM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.delenv("LM_MODEL", raising=False)
    with pytest.raises(ValueError, match="LM_MODEL"):
        load_settings()
    # secondo caso: manca LM_BASE_URL
    monkeypatch.delenv("LM_BASE_URL")
    monkeypatch.setenv("LM_MODEL", "m")
    with pytest.raises(ValueError, match="LM_BASE_URL"):
        load_settings()


# Verifica MAX_STEPS: predefinito 5 passaggi del grafo; un valore 0 e' rifiutato.
def test_config_valida(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("LM_MODEL", "m")
    monkeypatch.delenv("MAX_STEPS", raising=False)
    assert load_settings().max_steps == 5
    # controllo: zero passaggi non ha senso, quindi errore
    monkeypatch.setenv("MAX_STEPS", "0")
    with pytest.raises(ValueError, match="MAX_STEPS"):
        load_settings()


# Verifica FUSO_PREDEFINITO: riserva Europe/Rome, un fuso IANA valido e' accettato, un nome
# non IANA ("Roma") e' rifiutato all'avvio.
def test_config_fuso_predefinito(monkeypatch):
    monkeypatch.setenv("LM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("LM_MODEL", "m")
    monkeypatch.delenv("FUSO_PREDEFINITO", raising=False)
    assert load_settings().fuso_predefinito == "Europe/Rome"
    monkeypatch.setenv("FUSO_PREDEFINITO", "Asia/Tokyo")
    assert load_settings().fuso_predefinito == "Asia/Tokyo"
    # "Roma" non e' un identificativo IANA: errore che nomina la variabile
    monkeypatch.setenv("FUSO_PREDEFINITO", "Roma")
    with pytest.raises(ValueError, match="FUSO_PREDEFINITO"):
        load_settings()


# Verifica la risposta vuota (solo spazi): il modello ha speso i token nel ragionamento, e il
# grafo lo spiega all'utente invece di mostrare una riga vuota.
def test_risposta_vuota():
    llm = ModelloFinto(["  \n"])
    out = build_graph(llm).invoke({"messages": [HumanMessage("ciao")], "steps": 0})
    assert "i token sono finiti nel ragionamento" in out["messages"][-1].content


# Verifica LM Studio spento: messaggio che indica LM_BASE_URL e la CLI che continua.
def test_server_non_raggiungibile():
    # preparazione: la prima chiamata fallisce per connessione, la seconda risponde "Eccomi"
    errore = openai.APIConnectionError(
        request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    llm = ModelloFinto([errore, "Eccomi"])
    uscite = _esegui(["ciao", "di nuovo", "exit"], llm)
    assert any("LM_BASE_URL" in u for u in uscite)
    assert ETICHETTA_ASSISTENTE + "Eccomi" in uscite  # il ciclo continua dopo l'errore
    # la domanda fallita non resta nella cronologia
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "di nuovo"]


# Verifica che Ctrl+C mentre il modello risponde chiuda la CLI senza Traceback.
def test_ctrl_c_durante_la_richiesta():
    # il modello finto solleva KeyboardInterrupt, come se l'utente premesse Ctrl+C
    llm = ModelloFinto([KeyboardInterrupt()])
    _esegui(["ciao"], llm)  # deve uscire senza propagare


# Prova reale con il modello di LM Studio: saltata se RUN_LM_STUDIO non vale "1" (nessun
# modello attivo). Verifica che il modello vero ricordi il nome detto al turno prima.
@pytest.mark.skipif(os.environ.get("RUN_LM_STUDIO") != "1",
                    reason="serve LM Studio attivo e RUN_LM_STUDIO=1")
def test_prova_reale_lm_studio():
    from app.llm import build_llm

    # modello vero, configurato da LM_BASE_URL e LM_MODEL
    llm = build_llm(load_settings())
    uscite = _esegui(["Mi chiamo Luigi.", "Come mi chiamo?", "exit"], llm)
    assert "Luigi" in uscite[-1]


# Verifica l'errore 500 del server: si mostra il testo del server, senza suggerimenti fuori
# luogo; la domanda fallita non resta nella cronologia e la CLI continua.
def test_errore_http_del_server():
    # preparazione: risposta HTTP 500 finta e l'eccezione che openai solleverebbe
    risposta = httpx.Response(
        500, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    errore = openai.InternalServerError("boom", response=risposta, body=None)
    llm = ModelloFinto([errore, "Eccomi"])
    uscite = _esegui(["ciao", "di nuovo", "exit"], llm)
    # la riga d'errore stampata e' quella che contiene "500"
    messaggio = next(u for u in uscite if "500" in u)
    assert "boom" in messaggio  # il testo del server
    assert "Prompt Template" not in messaggio and "LM_MODEL" not in messaggio
    assert ETICHETTA_ASSISTENTE + "Eccomi" in uscite
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "di nuovo"]


# Verifica l'errore 400 del template jinja (es. schema con anyOf): messaggio del server e
# suggerimento sul template di prompt, non su LM_MODEL.
def test_errore_400_con_messaggio_e_suggerimento():
    risposta = httpx.Response(
        400, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    errore = openai.BadRequestError("Error rendering prompt with jinja template",
                                    response=risposta, body=None)
    llm = ModelloFinto([errore, "Eccomi"])
    uscite = _esegui(["ciao", "di nuovo", "exit"], llm)
    messaggio = next(u for u in uscite if "400" in u)
    assert "Error rendering prompt with jinja template" in messaggio
    assert "template di prompt" in messaggio
    assert "LM_MODEL" not in messaggio
    assert [m.content for m in llm.chiamate[1]] == [SYSTEM_PROMPT, "di nuovo"]


# Verifica l'errore 404 (modello non trovato): il messaggio suggerisce di controllare LM_MODEL.
def test_errore_404_suggerisce_il_modello():
    risposta = httpx.Response(
        404, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))
    errore = openai.NotFoundError("model not found", response=risposta, body=None)
    uscite = _esegui(["ciao", "exit"], ModelloFinto([errore]))
    messaggio = next(u for u in uscite if "404" in u)
    assert "model not found" in messaggio and "LM_MODEL" in messaggio
