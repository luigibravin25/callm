# test della CLI client (step 6): parla solo HTTP con l'agente, simulato con httpx.MockTransport
import io
import json
import subprocess
import sys

import httpx
import pytest

from app import cli
from app.cli import (MSG_AGENTE_NON_RAGGIUNGIBILE, MSG_PROMPT, MSG_RISPOSTA_NON_VALIDA,
                     MSG_STATO, ClientAgente, main)
from app.comandi import MSG_ARG_SCONOSCIUTO, MSG_NESSUN_PROMPT, elenco_prompt
from app.info_prompt import InfoArgomento, InfoPrompt

URL = "http://127.0.0.1:8000"
SPIEGA = InfoPrompt("spiega", "Spiega.", (InfoArgomento("argomento", True),
                                          InfoArgomento("livello", False)))
PROMPTS_JSON = [{"nome": "spiega", "descrizione": "Spiega.",
                 "argomenti": [{"nome": "argomento", "obbligatorio": True},
                               {"nome": "livello", "obbligatorio": False}]}]
STATO_OK = {"agente": "ok", "mcp": {"stato": "ok", "messaggio": "", "strumenti": ["tooltime"],
                                     "prompt": 1},
            "modello": {"stato": "ok", "messaggio": "", "nome": "google/gemma-4-e2b"}}


# agente finto: risponde a /stato, /prompts e /chat; registra i corpi di /chat
class AgenteFinto:
    def __init__(self, risposte_chat=None, stato=(200, STATO_OK), prompts=PROMPTS_JSON):
        # ogni elemento: (codice, corpo) oppure un'eccezione da sollevare
        self.risposte_chat = list(risposte_chat or [])
        self.stato = stato
        self.prompts = prompts
        self.corpi = []  # corpi ricevuti da POST /chat
        self.giu = False  # True = agente spento (connessione rifiutata)

    def __call__(self, richiesta: httpx.Request) -> httpx.Response:
        if self.giu:
            raise httpx.ConnectError("rifiutata", request=richiesta)
        if richiesta.url.path == "/stato":
            return httpx.Response(self.stato[0], json=self.stato[1])
        if richiesta.url.path == "/prompts":
            return httpx.Response(200, json=self.prompts)
        self.corpi.append(json.loads(richiesta.content))
        risposta = self.risposte_chat.pop(0)
        if isinstance(risposta, BaseException):
            raise risposta
        codice, corpo = risposta
        if isinstance(corpo, str):
            return httpx.Response(codice, text=corpo)
        return httpx.Response(codice, json=corpo)


# risposta 200 di /chat con il testo dato e una cronologia riconoscibile
def _ok(testo, cronologia=None, riassunto=""):
    return (200, {"risposta": testo, "strumenti_usati": [], "categoria": "conversazione",
                  "argomento": "saluti", "riassunto": riassunto,
                  "cronologia": cronologia or [{"role": "user", "content": "x"},
                                               {"role": "assistant", "content": testo}]})


# esegue la chat con le righe date e restituisce cio' che e' stato stampato
def _chat(righe, agente):
    input_righe = iter(righe)

    # finto input(): restituisce le righe in ordine, poi EOF come Ctrl+Z
    def leggi(_prompt=""):
        try:
            return next(input_righe)
        except StopIteration:
            raise EOFError
    stampato = []
    main(ClientAgente(URL, 5, transport=httpx.MockTransport(agente)), input_fn=leggi,
         output_fn=stampato.append)
    return stampato


# Verifica che la CLI non carichi grafo, modelli, adattatore MCP ne' langchain_openai.
def test_cli_non_importa_il_grafo():
    codice = ("import app.cli, sys; print([m for m in ('app.graph', 'app.llm', "
              "'app.adattatore_mcp', 'langchain_openai') if m in sys.modules])")
    uscita = subprocess.run([sys.executable, "-c", codice], capture_output=True, text=True,
                            check=True)
    assert uscita.stdout.strip() == "[]"


# Verifica il giro della cronologia: la seconda domanda manda cronologia e riassunto della prima.
def test_cronologia_e_riassunto_tra_i_turni():
    cronologia = [{"role": "user", "content": "Ciao"}, {"role": "assistant", "content": "Ciao!"}]
    agente = AgenteFinto([_ok("Ciao!", cronologia, "riass"), _ok("Bene")])
    out = _chat(["Ciao", "Come stai?", "esci"], agente)
    assert "Assistente: Ciao!" in out and "Assistente: Bene" in out
    assert agente.corpi[0] == {"messaggio": "Ciao", "cronologia": [], "riassunto": ""}
    assert agente.corpi[1] == {"messaggio": "Come stai?", "cronologia": cronologia,
                               "riassunto": "riass"}


# Verifica un errore con corpo: si stampa il messaggio e la cronologia resta quella di prima.
def test_errore_con_corpo_cronologia_invariata():
    cronologia = [{"role": "user", "content": "Ciao"}, {"role": "assistant", "content": "Ciao!"}]
    errore = (503, {"errore": "modello_non_raggiungibile", "messaggio": "LM Studio spento."})
    agente = AgenteFinto([_ok("Ciao!", cronologia), errore, _ok("ok")])
    out = _chat(["Ciao", "Che ore sono?", "Riprovo", "esci"], agente)
    assert "LM Studio spento." in out
    assert agente.corpi[2]["cronologia"] == cronologia


# Verifica un errore senza corpo JSON: messaggio fisso con il codice.
def test_errore_senza_json():
    out = _chat(["Ciao", "esci"], AgenteFinto([(502, "Bad Gateway")]))
    assert MSG_RISPOSTA_NON_VALIDA.format(codice=502) in out


# Verifica l'agente non raggiungibile all'avvio: messaggio con il comando, nessun input letto.
def test_agente_spento_all_avvio():
    agente = AgenteFinto()
    agente.giu = True
    letto = []
    stampato = []
    main(ClientAgente(URL, 5, transport=httpx.MockTransport(agente)),
         input_fn=lambda p="": letto.append(1) or "esci", output_fn=stampato.append)
    assert MSG_AGENTE_NON_RAGGIUNGIBILE.format(url=URL) in stampato
    assert "python.exe -m app.api" in MSG_AGENTE_NON_RAGGIUNGIBILE
    assert letto == []


# Verifica (Review 4) l'agente che cade durante la chat: messaggio, la chat continua e la
# cronologia resta.
def test_agente_spento_durante_la_chat():
    cronologia = [{"role": "user", "content": "Ciao"}, {"role": "assistant", "content": "Ciao!"}]
    agente = AgenteFinto([_ok("Ciao!", cronologia),
                          httpx.ConnectError("rifiutata"), _ok("Eccomi")])
    out = _chat(["Ciao", "Ci sei?", "E adesso?", "esci"], agente)
    assert MSG_AGENTE_NON_RAGGIUNGIBILE.format(url=URL) in out
    assert "Assistente: Eccomi" in out
    assert agente.corpi[2]["cronologia"] == cronologia


# Verifica /stato 503 all'avvio: righe di avviso per le parti non pronte, poi la chat parte.
def test_stato_non_pronto_all_avvio():
    stato = {**STATO_OK, "modello": {"stato": "modello_assente", "messaggio": "non caricato",
                                     "nome": "x"}}
    out = _chat(["esci"], AgenteFinto(stato=(503, stato)))
    assert MSG_STATO.format(parte="modello", messaggio="non caricato") in out
    assert not any("mcp non pronto" in s for s in out)


# Verifica /prompts dall'elenco di GET /prompts, senza chiamare /chat.
def test_prompts_dall_agente():
    agente = AgenteFinto()
    out = _chat(["/prompts", "esci"], agente)
    assert elenco_prompt([SPIEGA]) in out and agente.corpi == []


# Verifica /prompt valido: corpo con il prompt e la riga che lo annuncia.
def test_prompt_valido():
    agente = AgenteFinto([_ok("MCP e' un protocollo")])
    out = _chat(['/prompt spiega argomento="Model Context Protocol"', "esci"], agente)
    assert MSG_PROMPT.format(nome="spiega") in out
    assert agente.corpi[0]["prompt"] == {"nome": "spiega",
                                         "argomenti": {"argomento": "Model Context Protocol"}}
    assert "messaggio" not in agente.corpi[0]


# Verifica /prompt con argomento sconosciuto: errore della CLI, nessuna chiamata.
def test_prompt_argomento_sconosciuto():
    agente = AgenteFinto()
    out = _chat(["/prompt spiega tema=MCP", "esci"], agente)
    assert MSG_ARG_SCONOSCIUTO.format(argomento="tema", nome="spiega",
                                      ammessi="argomento, livello") in out
    assert agente.corpi == []


# Verifica i comandi senza prompt (server MCP non partito).
def test_nessun_prompt():
    out = _chat(["/prompts", "esci"], AgenteFinto(prompts=[]))
    assert MSG_NESSUN_PROMPT in out


# Verifica (minore 1 dello step 5) Ctrl+C durante la chiamata: uscita pulita, niente traceback.
def test_ctrl_c_durante_la_chiamata():
    agente = AgenteFinto([KeyboardInterrupt()])
    out = _chat(["Ciao", "non letta"], agente)
    assert len(agente.corpi) == 1
    assert not any(s.startswith("Assistente:") for s in out)


# Verifica il BOM della pipe di PowerShell: /prompts resta un comando ed esci chiude.
def test_bom_iniziale():
    agente = AgenteFinto()
    out = _chat(["﻿﻿/prompts", "﻿esci", "Che ore sono?"], agente)
    assert elenco_prompt([SPIEGA]) in out and agente.corpi == []


# Verifica la configurazione: predefiniti e AGENTE_TIMEOUT non valido.
def test_configurazione(monkeypatch):
    monkeypatch.delenv("AGENTE_URL", raising=False)
    monkeypatch.delenv("AGENTE_TIMEOUT", raising=False)
    assert cli.leggi_configurazione() == (URL, 300)
    monkeypatch.setenv("AGENTE_TIMEOUT", "0")
    with pytest.raises(SystemExit, match="AGENTE_TIMEOUT"):
        cli.leggi_configurazione()


# Verifica la pipe di PowerShell senza PYTHONIOENCODING: stdin cp1252 con il BOM; avvia la legge
# in UTF-8, cosi' /prompts resta un comando.
def test_pipe_in_cp1252_con_bom(monkeypatch):
    agente = AgenteFinto()
    monkeypatch.setattr(cli, "ClientAgente",
                        lambda url, timeout: ClientAgente(url, timeout,
                                                          transport=httpx.MockTransport(agente)))
    pipe = io.TextIOWrapper(io.BytesIO("﻿/prompts\nesci\n".encode("utf-8")),
                            encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", pipe)
    stampato = []
    cli.avvia(output_fn=stampato.append)
    assert elenco_prompt([SPIEGA]) in stampato and agente.corpi == []
