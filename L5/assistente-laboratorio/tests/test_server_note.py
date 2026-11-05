import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client

PROGETTO = Path(__file__).resolve().parent.parent


@pytest.fixture
def mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTE_DB", str(tmp_path / "note.sqlite"))
    from mcp_note.server import mcp as server
    return server


def _esegui(server, fabbrica):
    async def corpo():
        async with Client(server) as client:
            return await fabbrica(client)
    return asyncio.run(corpo())


def _testo(risultato) -> str:
    return "".join(b.text for b in risultato.content if getattr(b, "type", "") == "text")


def _chiama(server, nome, argomenti):
    return _esegui(server, lambda c: c.call_tool(nome, argomenti, raise_on_error=False))


def test_elenco_dei_tool_e_annotazioni(mcp):
    tools = {t.name: t for t in _esegui(mcp, lambda c: c.list_tools())}
    assert set(tools) == {"add_note", "list_notes", "delete_note"}
    assert tools["list_notes"].annotations.readOnlyHint is True
    assert tools["delete_note"].annotations.destructiveHint is True
    assert tools["delete_note"].annotations.idempotentHint is True
    assert tools["add_note"].annotations.destructiveHint is False
    assert tools["add_note"].annotations.readOnlyHint is False
    for t in tools.values():
        for nome, schema in t.inputSchema["properties"].items():
            assert "type" in schema and "anyOf" not in schema, (t.name, nome, schema)
    assert tools["list_notes"].inputSchema["properties"]["limit"]["default"] == 10


def test_add_poi_list_poi_delete(mcp):
    creata = _testo(_chiama(mcp, "add_note", {"text": "consegnare il report venerdì"}))
    assert creata.startswith("Nota 1 creata il ")
    assert creata.endswith(": consegnare il report venerdì")
    elenco = _testo(_chiama(mcp, "list_notes", {}))
    assert elenco.startswith("Note: ")
    note = json.loads(elenco.removeprefix("Note: "))
    assert note[0]["id"] == 1 and note[0]["testo"] == "consegnare il report venerdì"
    eliminata = _testo(_chiama(mcp, "delete_note", {"note_id": 1}))
    assert eliminata.startswith("Nota 1 eliminata: consegnare il report venerdì (creata il ")
    assert eliminata.endswith(").")
    assert _testo(_chiama(mcp, "list_notes", {})) == "Nessuna nota salvata."


def test_list_vuota(mcp):
    assert _testo(_chiama(mcp, "list_notes", {})) == "Nessuna nota salvata."


def test_list_tagliata(mcp):
    for i in range(12):
        _chiama(mcp, "add_note", {"text": f"nota {i}"})
    testo = _testo(_chiama(mcp, "list_notes", {}))
    lista, avviso = testo.split("\n", 1)
    assert len(json.loads(lista.removeprefix("Note: "))) == 10
    assert avviso == "Mostrate 10 di 12 note: richiama list_notes con limit=12 per vederle tutte."


@pytest.mark.parametrize("nome, argomenti, messaggio", [
    ("add_note", {"text": "  "}, "Il testo della nota è vuoto: scrivi che cosa ricordare."),
    ("add_note", {"text": "x" * 501},
     "Il testo della nota è troppo lungo: 501 caratteri, massimo 500."),
    ("list_notes", {"limit": 0}, "limit deve essere tra 1 e 50, ricevuto 0."),
    ("delete_note", {"note_id": 99}, "La nota 99 non esiste: nessuna nota eliminata."),
])
def test_errori_isError(mcp, nome, argomenti, messaggio):
    r = _chiama(mcp, nome, argomenti)
    assert r.is_error and _testo(r) == messaggio


@pytest.mark.parametrize("nome, argomenti, parola", [
    ("list_notes", {"limit": True}, "limit"),
    ("delete_note", {"note_id": True}, "note_id"),
])
def test_booleani_rifiutati(mcp, nome, argomenti, parola):
    r = _chiama(mcp, nome, argomenti)
    assert r.is_error and parola in _testo(r)


def test_note_id_stringa_numerica(mcp):
    _chiama(mcp, "add_note", {"text": "uno"})
    r = _chiama(mcp, "delete_note", {"note_id": "1"})
    assert not r.is_error and _testo(r).startswith("Nota 1 eliminata")


def test_log_su_stderr_per_le_modifiche(tmp_path):
    richieste = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "add_note", "arguments": {"text": "comprare il latte"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "delete_note", "arguments": {"note_id": 1}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "list_notes", "arguments": {}}},
    ]
    ambiente = dict(os.environ, NOTE_DB=str(tmp_path / "note.sqlite"),
                    FASTMCP_LOG_LEVEL="WARNING")
    processo = subprocess.Popen([sys.executable, "-m", "mcp_note.server"], cwd=PROGETTO,
                                text=True, encoding="utf-8", env=ambiente,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    # una richiesta alla volta, come l'adattatore: il server elabora in parallelo le richieste
    # che arrivano insieme (delete_note potrebbe partire prima che add_note abbia salvato)
    righe = []
    for richiesta in richieste:
        processo.stdin.write(json.dumps(richiesta) + "\n")
        processo.stdin.flush()
        if "id" in richiesta:
            righe.append(processo.stdout.readline())
    processo.stdin.close()
    righe += processo.stdout.read().splitlines(keepends=True)
    errori = processo.stderr.read()
    processo.wait(timeout=30)
    assert all(json.loads(r)["jsonrpc"] == "2.0" for r in righe if r.strip())
    assert "[note] creata nota 1: comprare il latte" in errori
    assert "[note] eliminata nota 1: comprare il latte" in errori
    assert "list_notes" not in errori  # nessun log per le letture
