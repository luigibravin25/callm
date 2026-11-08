# Test del server MCP delle note (mcp_note/server.py) attraverso il protocollo MCP:
# tool, annotazioni, messaggi, errori e log delle modifiche.

# librerie standard: asincronia, JSON, ambiente, processi, interprete, percorsi
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

# pytest e il client MCP di FastMCP
import pytest
from fastmcp import Client

# cartella assistente-laboratorio/: da qui si avvia il processo del server
PROGETTO = Path(__file__).resolve().parent.parent


# il server delle note con un archivio temporaneo nuovo per ogni test
@pytest.fixture
def mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTE_DB", str(tmp_path / "note.sqlite"))
    from mcp_note.server import mcp as server
    return server


# apre una sessione MCP in memoria con il server ed esegue un'operazione
def _esegui(server, fabbrica):
    async def corpo():
        async with Client(server) as client:
            return await fabbrica(client)
    return asyncio.run(corpo())


# unisce i blocchi di testo della risposta di un tool
def _testo(risultato) -> str:
    return "".join(b.text for b in risultato.content if getattr(b, "type", "") == "text")


# chiama un tool; un errore torna come risposta con is_error invece che come eccezione
def _chiama(server, nome, argomenti):
    return _esegui(server, lambda c: c.call_tool(nome, argomenti, raise_on_error=False))


# tools/list: tre tool con le annotazioni MCP giuste (servono alla conferma) e schemi semplici
def test_elenco_dei_tool_e_annotazioni(mcp):
    tools = {t.name: t for t in _esegui(mcp, lambda c: c.list_tools())}
    assert set(tools) == {"add_note", "list_notes", "delete_note"}
    # list_notes legge soltanto; delete_note distrugge ma ripeterlo non cambia nulla
    # (idempotente); add_note scrive senza distruggere
    assert tools["list_notes"].annotations.readOnlyHint is True
    assert tools["delete_note"].annotations.destructiveHint is True
    assert tools["delete_note"].annotations.idempotentHint is True
    assert tools["add_note"].annotations.destructiveHint is False
    assert tools["add_note"].annotations.readOnlyHint is False
    # ogni argomento ha "type" e nessun "anyOf" (richiesto da gemma in LM Studio)
    for t in tools.values():
        for nome, schema in t.inputSchema["properties"].items():
            assert "type" in schema and "anyOf" not in schema, (t.name, nome, schema)
    assert tools["list_notes"].inputSchema["properties"]["limit"]["default"] == 10


# ciclo completo: crea, legge, elimina, rilegge; controlla anche il testo di ogni risposta
def test_add_poi_list_poi_delete(mcp):
    # 1. creazione: ID, data e testo nella risposta
    creata = _testo(_chiama(mcp, "add_note", {"text": "consegnare il report venerdì"}))
    assert creata.startswith("Nota 1 creata il ")
    assert creata.endswith(": consegnare il report venerdì")
    # 2. elenco: "Note: " seguito da una lista JSON con la nota creata
    elenco = _testo(_chiama(mcp, "list_notes", {}))
    assert elenco.startswith("Note: ")
    note = json.loads(elenco.removeprefix("Note: "))
    assert note[0]["id"] == 1 and note[0]["testo"] == "consegnare il report venerdì"
    # 3. eliminazione: la risposta ripete testo e data della nota cancellata
    eliminata = _testo(_chiama(mcp, "delete_note", {"note_id": 1}))
    assert eliminata.startswith("Nota 1 eliminata: consegnare il report venerdì (creata il ")
    assert eliminata.endswith(").")
    # 4. l'archivio e' di nuovo vuoto
    assert _testo(_chiama(mcp, "list_notes", {})) == "Nessuna nota salvata."


# archivio vuoto: una frase chiara, non una lista vuota
def test_list_vuota(mcp):
    assert _testo(_chiama(mcp, "list_notes", {})) == "Nessuna nota salvata."


# oltre il limite predefinito (10) l'elenco e' tagliato e l'avviso dice come vedere tutto
def test_list_tagliata(mcp):
    # preparazione: 12 note
    for i in range(12):
        _chiama(mcp, "add_note", {"text": f"nota {i}"})
    testo = _testo(_chiama(mcp, "list_notes", {}))
    lista, avviso = testo.split("\n", 1)  # prima riga: note; seconda: avviso
    assert len(json.loads(lista.removeprefix("Note: "))) == 10
    assert avviso == "Mostrate 10 di 12 note: richiama list_notes con limit=12 per vederle tutte."


# gli errori dell'archivio arrivano al client come isError con il messaggio esatto
@pytest.mark.parametrize("nome, argomenti, messaggio", [
    # testo vuoto, testo troppo lungo, limit fuori intervallo, nota inesistente
    ("add_note", {"text": "  "}, "Il testo della nota è vuoto: scrivi che cosa ricordare."),
    ("add_note", {"text": "x" * 501},
     "Il testo della nota è troppo lungo: 501 caratteri, massimo 500."),
    ("list_notes", {"limit": 0}, "limit deve essere tra 1 e 50, ricevuto 0."),
    ("delete_note", {"note_id": 99}, "La nota 99 non esiste: nessuna nota eliminata."),
])
def test_errori_isError(mcp, nome, argomenti, messaggio):
    r = _chiama(mcp, nome, argomenti)
    assert r.is_error and _testo(r) == messaggio


# un booleano al posto di un numero e' rifiutato; il messaggio nomina l'argomento sbagliato
@pytest.mark.parametrize("nome, argomenti, parola", [
    ("list_notes", {"limit": True}, "limit"),
    ("delete_note", {"note_id": True}, "note_id"),
])
def test_booleani_rifiutati(mcp, nome, argomenti, parola):
    r = _chiama(mcp, nome, argomenti)
    assert r.is_error and parola in _testo(r)


# il modello a volte passa l'ID come testo ("1"): viene accettato e convertito
def test_note_id_stringa_numerica(mcp):
    _chiama(mcp, "add_note", {"text": "uno"})
    r = _chiama(mcp, "delete_note", {"note_id": "1"})
    assert not r.is_error and _testo(r).startswith("Nota 1 eliminata")


# ogni modifica (creazione, eliminazione) lascia una riga di log su stderr; le letture no
def test_log_su_stderr_per_le_modifiche(tmp_path):
    # messaggi JSON-RPC scritti a mano: handshake, poi add_note, delete_note e list_notes
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
    # archivio temporaneo; FastMCP mostra solo gli avvisi, cosi' su stderr restano i nostri log
    ambiente = dict(os.environ, NOTE_DB=str(tmp_path / "note.sqlite"),
                    FASTMCP_LOG_LEVEL="WARNING")
    # il server parte come processo vero, con stdin, stdout e stderr collegati al test
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
            righe.append(processo.stdout.readline())  # attende la risposta prima di proseguire
    processo.stdin.close()  # fine delle richieste: il server termina
    righe += processo.stdout.read().splitlines(keepends=True)
    errori = processo.stderr.read()
    processo.wait(timeout=30)
    # stdout contiene solo JSON-RPC; i log delle due modifiche sono su stderr
    assert all(json.loads(r)["jsonrpc"] == "2.0" for r in righe if r.strip())
    assert "[note] creata nota 1: comprare il latte" in errori
    assert "[note] eliminata nota 1: comprare il latte" in errori
    assert "list_notes" not in errori  # nessun log per le letture
