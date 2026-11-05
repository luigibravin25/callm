import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from mcp_catalogo.server import mcp

PROGETTO = Path(__file__).resolve().parent.parent


def _esegui(coroutine_factory):
    async def corpo():
        async with Client(mcp) as client:
            return await coroutine_factory(client)
    return asyncio.run(corpo())


def _testo(risultato) -> str:
    return "".join(b.text for b in risultato.content if getattr(b, "type", "") == "text")


def _chiama(nome, argomenti):
    return _esegui(lambda c: c.call_tool(nome, argomenti, raise_on_error=False))


def _lista(testo: str) -> list:
    """Prima riga del risultato di search_catalog: "[]" oppure "Trovati N prodotti: [...]"."""
    prima = testo.split("\n")[0]
    if prima == "[]":
        return []
    intestazione, _, dati = prima.partition(": ")
    lista = json.loads(dati)
    assert intestazione == f"Trovati {len(lista)} prodotti", prima
    return lista


def test_elenco_dei_tool():
    tools = _esegui(lambda c: c.list_tools())
    assert {t.name for t in tools} == {"search_catalog", "get_item"}
    for t in tools:
        for nome, schema in t.inputSchema["properties"].items():
            assert "type" in schema and "anyOf" not in schema, (t.name, nome, schema)
    ricerca = next(t for t in tools if t.name == "search_catalog")
    assert ricerca.inputSchema["properties"]["max_results"]["type"] == "integer"
    assert ricerca.inputSchema["properties"]["max_results"]["default"] == 5


def test_ricerca_vuota_e_lista_vuota():
    r = _chiama("search_catalog", {"query": "pattini a rotelle"})
    assert not r.is_error
    assert _testo(r) == "[]"


def test_ricerca_restituisce_json_sintetico():
    r = _chiama("search_catalog", {"query": "nuoto"})
    assert _lista(_testo(r)) == [
        {"codice": "PRD030", "nome": "Occhialini Nuoto", "categoria": "Sport"}]


def test_dettaglio_json_completo():
    r = _chiama("get_item", {"code": "prd001"})
    p = json.loads(_testo(r))
    assert p["codice"] == "PRD001" and p["prezzo_euro"] == 499.99
    assert "Caffè" in _testo(_chiama("get_item", {"code": "PRD005"}))


@pytest.mark.parametrize("nome, argomenti, messaggio", [
    ("get_item", {"code": "PRD999"},
     "Codice PRD999 non presente nel catalogo. Usa search_catalog per trovare il codice giusto."),
    ("search_catalog", {"query": "libri", "max_results": 0},
     "max_results deve essere tra 1 e 20, ricevuto 0."),
    ("search_catalog", {"query": "libri", "max_results": 21},
     "max_results deve essere tra 1 e 20, ricevuto 21."),
    ("search_catalog", {"query": ""},
     "La query è vuota: indica almeno una parola da cercare."),
])
def test_errori_come_tool_error(nome, argomenti, messaggio):
    r = _chiama(nome, argomenti)
    assert r.is_error
    assert _testo(r) == messaggio


def test_max_results_stringa_numerica():
    r = _chiama("search_catalog", {"query": "libri", "max_results": "3"})
    if not r.is_error:
        # i libri sono 10: dopo la lista c'e' la riga di avviso
        assert len(_lista(_testo(r))) == 3
    else:
        assert _testo(r)


def test_resource_catalogo():
    contenuti = _esegui(lambda c: c.read_resource("catalog://prodotti"))
    dati = json.loads(contenuti[0].text)
    assert len(dati) == 50
    assert dati[3]["stato"] == "Esaurito"


def test_csv_malformato_ferma_il_server(tmp_path):
    rotto = tmp_path / "prodotti.csv"
    rotto.write_text("Codice,Nome\nPRD001,A\n", encoding="utf-8")
    codice = ("import pathlib, runpy, sys, mcp_catalogo.catalogo as c; "
              "c.carica_catalogo.__defaults__ = (pathlib.Path(sys.argv[1]),); "
              "runpy.run_module('mcp_catalogo.server', run_name='__main__')")
    esito = subprocess.run([sys.executable, "-c", codice, str(rotto)],
                           capture_output=True, text=True, cwd=PROGETTO, timeout=30)
    assert esito.returncode != 0
    assert esito.stdout == ""
    assert "Catalogo non valido" in esito.stderr and "intestazione" in esito.stderr
    assert "Traceback" not in esito.stderr


# --- minori della revisione finale ---

def test_max_results_booleano_rifiutato():
    r = _chiama("search_catalog", {"query": "libri", "max_results": True})
    assert r.is_error, _testo(r)
    assert "max_results" in _testo(r)


def test_max_results_booleano_schema_intero():
    tools = _esegui(lambda c: c.list_tools())
    ricerca = next(t for t in tools if t.name == "search_catalog")
    schema = ricerca.inputSchema["properties"]["max_results"]
    assert schema["type"] == "integer" and "anyOf" not in schema


_RICHIESTE = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "search_catalog", "arguments": {"query": "nuoto"}}},
]


def _stdout_del_server(modulo, cartella):
    """Avvia il server via stdio, manda le richieste e restituisce le righe di stdout."""
    ingresso = "".join(json.dumps(r) + "\n" for r in _RICHIESTE)
    processo = subprocess.Popen([sys.executable, "-m", modulo], cwd=cartella, text=True,
                                encoding="utf-8", stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    righe = []
    processo.stdin.write(ingresso)
    processo.stdin.flush()
    for riga in processo.stdout:
        righe.append(riga)
        if '"id":3' in riga.replace(" ", ""):
            break
    processo.stdin.close()
    # anche cio' che resta nei buffer e viene scritto all'uscita
    righe += processo.stdout.read().splitlines(keepends=True)
    processo.wait(timeout=30)
    return [r for r in righe if r.strip()]


def _non_json(righe):
    cattive = []
    for r in righe:
        try:
            assert json.loads(r)["jsonrpc"] == "2.0"
        except (ValueError, KeyError, AssertionError):
            cattive.append(r)
    return cattive


def test_stdout_solo_protocollo():
    righe = _stdout_del_server("mcp_catalogo.server", PROGETTO)
    assert len(righe) == 3, righe  # risposte a initialize, tools/list, tools/call
    assert _non_json(righe) == []
    assert "PRD030" in righe[-1]


def test_stdout_controllo_rileva_le_stampe(tmp_path):
    # il controllo funziona davvero: un server che stampa su stdout viene scoperto
    sorgente = (PROGETTO / "tests" / "server_mcp_anyof.py").read_text(encoding="utf-8")
    # flush=True: senza, FastMCP chiude stdout e la riga bufferizzata va persa
    (tmp_path / "server_rumoroso.py").write_text('print("rumore", flush=True)\n' + sorgente,
                                                 encoding="utf-8")
    righe = _stdout_del_server("server_rumoroso", tmp_path)
    assert _non_json(righe) == ["rumore\n"]


# --- avviso quando il risultato e' tagliato ---

def test_risultato_tagliato_con_avviso():
    testo = _testo(_chiama("search_catalog", {"query": "casa e cucina"}))
    lista, avviso = testo.split("\n", 1)
    assert len(_lista(lista)) == 5
    assert avviso == ("Mostrati 5 di 10 risultati: richiama search_catalog con max_results=10 "
                      "per vederli tutti.")


def test_risultato_completo_senza_avviso():
    testo = _testo(_chiama("search_catalog", {"query": "casa e cucina", "max_results": 10}))
    assert len(_lista(testo)) == 10
    assert "Mostrati" not in testo


def test_oltre_il_massimo_avviso_fino_a_20(monkeypatch):
    import mcp_catalogo.server as server
    molti = [dict(server.CATALOGO[0], codice=f"PRX{i:03d}") for i in range(25)]
    monkeypatch.setattr(server, "CATALOGO", molti)
    testo = _testo(_chiama("search_catalog", {"query": "smartphone", "max_results": 20}))
    lista, avviso = testo.split("\n", 1)
    assert len(_lista(lista)) == 20
    assert avviso == ("Mostrati 20 di 25 risultati (massimo 20 per chiamata): "
                      "rendi la query più precisa per trovare gli altri.")


# --- eco [TOOL_RESULT]: con una lista JSON pura gemma ripeteva il risultato grezzo ---

def test_risultati_preceduti_da_una_riga_di_testo():
    testo = _testo(_chiama("search_catalog", {"query": "smartphone"}))
    assert testo.startswith("Trovati 1 prodotti: [")
    assert not testo.startswith("[")


def test_ricerca_vuota_resta_lista_vuota_esatta():
    assert _testo(_chiama("search_catalog", {"query": "pattini a rotelle"})) == "[]"
