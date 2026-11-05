"""Test del server MCP del meteo con il protocollo vero (client FastMCP in memoria).

Il client HTTP del server e' sostituito da quello finto (tests/meteo_finto.py): nessuna rete.
Il contatore usa il file temporaneo di tests/conftest.py (METEO_CONTATORE).
"""
import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from tests.meteo_finto import GEO_PARIS_IT, GEO_ROMA, GEO_VUOTO, METEO_ESEMPIO, client_finto

PROGETTO = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(monkeypatch, tmp_path):
    """Il server meteo con un contatore temporaneo e risposte di Roma simulate."""
    monkeypatch.setenv("METEO_CONTATORE", str(tmp_path / "contatore.sqlite"))
    from mcp_meteo import server as modulo
    monkeypatch.setattr(modulo, "crea_client",
                        lambda: client_finto(geo=GEO_ROMA, meteo=METEO_ESEMPIO))
    return modulo


def _esegui(server, fabbrica):
    """Apre una sessione MCP in memoria con il server ed esegue la coroutine di `fabbrica`."""
    async def corpo():
        """Sessione MCP aperta e chiusa intorno alla chiamata."""
        async with Client(server.mcp) as client:
            return await fabbrica(client)
    return asyncio.run(corpo())


def _testo(risultato) -> str:
    """Testo del risultato di tools/call."""
    return "".join(b.text for b in risultato.content if getattr(b, "type", "") == "text")


def _chiama(server, argomenti):
    """tools/call di get_weather senza sollevare eccezioni sugli errori del tool."""
    return _esegui(server, lambda c: c.call_tool("get_weather", argomenti, raise_on_error=False))


def test_elenco_e_annotazioni(server):
    """Un solo tool, sola lettura e mondo aperto, schema con type e predefiniti giusti."""
    tools = _esegui(server, lambda c: c.list_tools())
    assert [t.name for t in tools] == ["get_weather"]
    tool = tools[0]
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.openWorldHint is True
    proprieta = tool.inputSchema["properties"]
    for nome, schema in proprieta.items():
        assert "type" in schema and "anyOf" not in schema, (nome, schema)
    assert (proprieta["city"]["default"], proprieta["days"]["default"],
            proprieta["date"]["default"]) == ("", 0, "")
    assert proprieta["days"]["type"] == "integer"


def test_chiamata_riuscita(server):
    """La chiamata restituisce il testo del meteo di Roma, senza errore."""
    risultato = _chiama(server, {"city": "Roma"})
    assert not risultato.is_error
    assert "Meteo attuale a Roma (Lazio)" in _testo(risultato)


@pytest.mark.parametrize("geo, meteo, categoria", [
    (GEO_VUOTO, None, "Città non trovata"),
    (GEO_PARIS_IT, None, "Città non trovata"),  # citta' estera: solo nomi simili in Italia
    (httpx.ConnectError("rete assente"), None, "Rete non raggiungibile"),
    (GEO_ROMA, httpx.Response(503), "Servizio meteo non disponibile")])
def test_errore_come_iserror(server, monkeypatch, geo, meteo, categoria):
    """Gli errori arrivano al client come isError con la categoria giusta."""
    monkeypatch.setattr(server, "crea_client", lambda: client_finto(geo=geo, meteo=meteo))
    risultato = _chiama(server, {"city": "Roma"})
    assert risultato.is_error
    assert _testo(risultato).startswith(categoria), _testo(risultato)


@pytest.mark.parametrize("argomenti", [{"days": True}, {"days": 8}, {"city": "x" * 101}])
def test_argomenti_rifiutati(server, argomenti):
    """days booleano o fuori intervallo e city troppo lunga sono errori del tool."""
    assert _chiama(server, argomenti).is_error


def test_limite_raggiunto(server, monkeypatch):
    """Con METEO_LIMITE_GIORNALIERO=1 la chiamata (2 richieste) si ferma al limite."""
    monkeypatch.setenv("METEO_LIMITE_GIORNALIERO", "1")
    risultato = _chiama(server, {"city": "Roma"})
    assert risultato.is_error
    assert "riprova domani" in _testo(risultato)


def test_avvio_stdio_senza_traceback():
    """Il server si avvia come processo (python -m mcp_meteo.server) e si chiude senza errori."""
    esito = subprocess.run([sys.executable, "-m", "mcp_meteo.server"], cwd=PROGETTO,
                           input="", capture_output=True, text=True, timeout=60)
    assert esito.returncode == 0 and "Traceback" not in esito.stderr, esito.stderr
