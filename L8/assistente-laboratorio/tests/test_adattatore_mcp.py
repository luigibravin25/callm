# Test dell'adattatore MCP con il server vero avviato come sottoprocesso (nessun LM Studio).
import logging
import sys
from pathlib import Path

import pytest

from langchain_core.messages import HumanMessage

from app.adattatore_mcp import (ErroreMCP, InfoArgomento, carica_strumenti, carica_strumenti_ricerca,
                                configurazione_ricerca, configurazione_server,
                                elenca_prompt, leggi_preferenze, ottieni_prompt)

# cartella del progetto: i sottoprocessi importano app/ da qui, da qualsiasi cartella
# partano i test
CARTELLA = Path(__file__).resolve().parent.parent


# messaggi del logger "mcp" registrati da caplog
def _log_mcp(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "mcp"]


# Verifica come parte il server: stesso interprete, variabili passate solo se impostate.
def test_configurazione_passa_le_variabili(monkeypatch):
    monkeypatch.setenv("PREFERENZE_FILE", "prefs.json")
    monkeypatch.setenv("FUSO_PREDEFINITO", "Asia/Tokyo")
    conf = configurazione_server()
    assert conf["command"] == sys.executable
    assert conf["args"] == ["-m", "mcp_assistente.server"]
    assert conf["env"]["PREFERENZE_FILE"] == "prefs.json"
    assert conf["env"]["FUSO_PREDEFINITO"] == "Asia/Tokyo"
    assert conf["env"]["FASTMCP_LOG_LEVEL"] == "CRITICAL"
    assert conf["env"]["PYTHONIOENCODING"] == "utf-8"
    monkeypatch.delenv("PREFERENZE_FILE")
    monkeypatch.delenv("FUSO_PREDEFINITO")
    env = configurazione_server()["env"]
    assert "PREFERENZE_FILE" not in env and "FUSO_PREDEFINITO" not in env


# Verifica la discovery: un solo strumento, tooltime, e il log tools/list.
def test_carica_strumenti_solo_tooltime(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        strumenti = carica_strumenti()
    assert [t.name for t in strumenti] == ["tooltime"]
    assert "tools/list: tooltime" in _log_mcp(caplog)


# Verifica una chiamata sincrona del tool attraverso MCP e il suo log tools/call.
def test_tools_call_con_log(caplog):
    tooltime = carica_strumenti()[0]
    with caplog.at_level(logging.INFO, logger="mcp"):
        risultato = tooltime.invoke({"fuso": "Asia/Tokyo", "parte": "ora"})
    assert risultato.startswith("Tokyo: ")
    assert any(m.startswith("tools/call tooltime") and "Asia/Tokyo" in m
               for m in _log_mcp(caplog))


# Verifica la lettura della resource dal file di PREFERENZE_FILE e il log resources/read.
def test_leggi_preferenze(tmp_path, monkeypatch, caplog):
    file = tmp_path / "prefs.json"
    file.write_text('{"lingua": "inglese"}', encoding="utf-8")
    monkeypatch.setenv("PREFERENZE_FILE", str(file))
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert leggi_preferenze() == '{"lingua": "inglese"}'
    assert "resources/read utente://preferenze" in _log_mcp(caplog)


# Verifica che un file mancante dia None con un avviso (l'host usera' i predefiniti).
def test_leggi_preferenze_file_mancante(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("PREFERENZE_FILE", str(tmp_path / "manca.json"))
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert leggi_preferenze() is None
    assert any(r.levelno == logging.WARNING for r in caplog.records if r.name == "mcp")


# Verifica che un server che non parte dia ErroreMCP nella discovery.
def test_server_inesistente():
    with pytest.raises(ErroreMCP):
        carica_strumenti("modulo_che_non_esiste")


# Verifica che un server che non parte dia None (con avviso) nella lettura della resource.
def test_leggi_preferenze_server_inesistente(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert leggi_preferenze("modulo_che_non_esiste") is None
    assert any(r.levelno == logging.WARNING for r in caplog.records if r.name == "mcp")


# --- prompt (step 5) ---

# Verifica la discovery dei prompt (prompts/list): nomi, descrizione, argomenti e log.
def test_elenca_prompt(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        prompts = elenca_prompt()
    assert [p.nome for p in prompts] == ["spiega", "riassumi_conversazione"]
    assert prompts[0].argomenti == (InfoArgomento("argomento", True),
                                    InfoArgomento("livello", False))
    assert prompts[1].argomenti == (InfoArgomento("stile", False),)
    assert prompts[0].descrizione.startswith("Spiega un argomento")
    assert "prompts/list: spiega, riassumi_conversazione" in _log_mcp(caplog)


# Verifica prompts/get: messaggi LangChain dal server e log con argomenti e testo ottenuto.
def test_ottieni_prompt_con_log(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        messaggi = ottieni_prompt("spiega", {"argomento": "Model Context Protocol",
                                             "livello": "base"})
    assert len(messaggi) == 1 and isinstance(messaggi[0], HumanMessage)
    assert messaggi[0].content.startswith("Spiegami Model Context Protocol.")
    log = _log_mcp(caplog)
    assert any(r.startswith("prompts/get spiega {'argomento': 'Model Context Protocol'")
               for r in log)
    assert any(r.startswith("prompts/get spiega: 1 messaggio: human: Spiegami") for r in log)


# Verifica che un valore rifiutato dal server diventi ErroreMCP con il motivo del server.
def test_ottieni_prompt_valore_non_valido():
    with pytest.raises(ErroreMCP, match="livello non valido"):
        ottieni_prompt("spiega", {"argomento": "MCP", "livello": "pippo"})


# Verifica che senza server l'elenco dei prompt sia vuoto, con un avviso.
def test_elenca_prompt_server_inesistente(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert elenca_prompt("modulo_che_non_esiste") == []
    assert any(r.levelno == logging.WARNING and "prompts/list non riuscita" in r.getMessage()
               for r in caplog.records if r.name == "mcp")


# Verifica che senza server prompts/get dia ErroreMCP.
def test_ottieni_prompt_server_inesistente():
    with pytest.raises(ErroreMCP):
        ottieni_prompt("spiega", {"argomento": "MCP"}, "modulo_che_non_esiste")


# --- step 6: tipi dei prompt senza MCP, prompt rifiutato distinto, avviso su prompts/get ---

# Verifica che i tipi dei prompt si importino senza caricare MCP ne' LangChain (li usa la CLI).
def test_info_prompt_senza_mcp():
    import subprocess
    codice = ("import app.info_prompt, sys; "
              "print('mcp' in sys.modules, 'langchain_core' in sys.modules)")
    uscita = subprocess.run([sys.executable, "-c", codice], capture_output=True, text=True,
                            cwd=CARTELLA, check=True)
    assert uscita.stdout.split() == ["False", "False"]


# Verifica che un valore rifiutato dal server diventi PromptNonValido, con un WARNING nel log.
def test_prompt_rifiutato_e_prompt_non_valido(caplog):
    from app.adattatore_mcp import PromptNonValido
    caplog.set_level(logging.INFO, logger="mcp")
    with pytest.raises(PromptNonValido):
        ottieni_prompt("spiega", {"argomento": "MCP", "livello": "esperto"})
    assert any(r.levelno == logging.WARNING and "prompts/get spiega non riuscita" in r.getMessage()
               for r in caplog.records)


# Verifica che un server che non parte dia ErroreMCP (non PromptNonValido), con un WARNING.
def test_server_rotto_e_errore_mcp(caplog):
    from app.adattatore_mcp import PromptNonValido
    caplog.set_level(logging.INFO, logger="mcp")
    with pytest.raises(ErroreMCP) as errore:
        ottieni_prompt("spiega", {"argomento": "MCP"}, "modulo_che_non_esiste")
    assert not isinstance(errore.value, PromptNonValido)
    assert any(r.levelno == logging.WARNING and "prompts/get spiega non riuscita" in r.getMessage()
               for r in caplog.records)


# --- lezione 8, esercizio 2: server di ricerca accanto a quello dell'assistente ---

# Verifica come parte il server di ricerca: cartella ricerca/, variabili passate solo se impostate.
def test_configurazione_ricerca_passa_le_variabili(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    monkeypatch.setenv("QDRANT_URL", "")
    conf = configurazione_ricerca()
    assert conf["command"] == sys.executable
    assert conf["args"] == ["-m", "mcp_ricerca.server"]
    assert Path(conf["cwd"]).name == "ricerca" and Path(conf["cwd"]).parent == CARTELLA.parent
    assert conf["env"]["EMBEDDING_MODEL"] == "bge"
    assert "QDRANT_URL" not in conf["env"]
    assert conf["env"]["FASTMCP_LOG_LEVEL"] == "CRITICAL" and conf["env"]["PYTHONIOENCODING"] == "utf-8"


# Verifica la discovery del server di ricerca vero (nessun servizio: tools/list non usa Qdrant).
def test_carica_strumenti_ricerca(caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        strumenti = carica_strumenti_ricerca()
    assert [t.name for t in strumenti] == ["search_documents"]
    assert "tools/list ricerca: search_documents" in _log_mcp(caplog)


# Verifica che un errore del tool di ricerca arrivi come testo per il modello (capitolo controllato
# prima di Qdrant e LM Studio: nessun servizio).
def test_ricerca_errore_del_tool(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "bge")
    cerca = carica_strumenti_ricerca()[0]
    risultato = cerca.invoke({"query": "brodo", "capitolo": "DOLCI"})
    assert "sconosciuto" in risultato and "PASTICCERIA" in risultato


# Verifica che un server di ricerca che non parte non fermi l'agente: nessun tool e un avviso.
def test_ricerca_cartella_inesistente(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert carica_strumenti_ricerca(tmp_path / "manca") == []
    assert any(m.startswith("server ricerca non disponibile") for m in _log_mcp(caplog))


# Verifica (revisione finale) un server di ricerca che parte ma non ha tool utilizzabili: avviso come se
# non fosse partito, non una riga tools/list vuota.
def test_ricerca_senza_tool_validi(monkeypatch, caplog):
    from app import adattatore_mcp
    monkeypatch.setattr(adattatore_mcp, "schema_valido", lambda tool: False)
    with caplog.at_level(logging.INFO, logger="mcp"):
        assert carica_strumenti_ricerca() == []
    messaggi = _log_mcp(caplog)
    assert any(m.startswith("server ricerca non disponibile") for m in messaggi)
    assert not any(m.startswith("tools/list ricerca") for m in messaggi)


# --- lezione 8, esercizio 3: modalità della ricerca ---

# Verifica che modello di chat, modalità, candidati e tetto arrivino al server di ricerca.
def test_configurazione_ricerca_passa_la_modalita(monkeypatch):
    for nome, valore in {"LM_MODEL": "gemma", "RICERCA_MODALITA": "entrambe", "RICERCA_CANDIDATI": "12",
                         "RERANK_TETTO": "10"}.items():
        monkeypatch.setenv(nome, valore)
    env = configurazione_ricerca()["env"]
    assert (env["LM_MODEL"], env["RICERCA_MODALITA"], env["RICERCA_CANDIDATI"], env["RERANK_TETTO"]) == \
        ("gemma", "entrambe", "12", "10")


# Verifica il tempo massimo di una chiamata MCP: 60 s, perché una ricerca in modalità entrambe dura fino a ~28 s
# più l'avvio del server (decisione dell'utente, 2026-11-20).
def test_timeout_mcp_60_secondi():
    from app import adattatore_mcp
    assert adattatore_mcp.TIMEOUT_S == 60
