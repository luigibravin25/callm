# Test dell'adattatore MCP con il server vero avviato come sottoprocesso (nessun LM Studio).
import logging
import sys

import pytest

from app.adattatore_mcp import ErroreMCP, carica_strumenti, configurazione_server, leggi_preferenze


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
