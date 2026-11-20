# Test del server MCP mcp_assistente: tooltime, resource utente://preferenze e prompt (step 5).
# Il client di FastMCP parla con il server in memoria (nessun sottoprocesso, nessun LM Studio).
# librerie standard: codice asincrono, JSON, espressioni regolari, istanti fissi
import asyncio
import json
import re
from datetime import datetime, timezone

import pytest
# Client: client MCP di FastMCP; con l'oggetto del server parla in memoria
from fastmcp import Client

from mcp_assistente import orologio
from mcp_assistente.server import (CARTELLA_PROGETTO, DESCRIZIONE_RIASSUMI, DESCRIZIONE_SPIEGA,
                                    LIVELLI, STILI, TESTO_RIASSUMI, URI_PREFERENZE, mcp,
                                    percorso_preferenze)


# esegue una funzione asincrona che riceve il client collegato al server
def _con_client(azione):
    async def corpo():
        async with Client(mcp) as client:
            return await azione(client)
    return asyncio.run(corpo())


# elenco dei tool pubblicati dal server (tools/list)
def _lista_tool():
    return _con_client(lambda c: c.list_tools())


# Verifica che il server pubblichi solo tooltime: la resource non e' un tool.
def test_tooltime_unico_tool_e_resource_non_tool():
    assert [t.name for t in _lista_tool()] == ["tooltime"]


# Verifica che la resource sia pubblicata come resource, con il suo URI e il tipo JSON.
def test_resource_pubblicata():
    risorse = _con_client(lambda c: c.list_resources())
    assert [str(r.uri) for r in risorse] == [URI_PREFERENZE]
    assert risorse[0].mimeType == "application/json"


# Verifica lo schema di tooltime: ogni argomento ha "type", niente "anyOf" (template di gemma),
# "parte" con 3 valori e nessun argomento obbligatorio.
def test_schema_tooltime_con_type():
    schema = _lista_tool()[0].inputSchema
    for nome, proprieta in schema["properties"].items():
        assert "type" in proprieta and "anyOf" not in proprieta, (nome, proprieta)
    assert schema["properties"]["parte"]["enum"] == ["ora", "data", "entrambe"]
    assert not schema.get("required")


# Verifica che la descrizione per il modello sia quella di sempre (nome IANA, ora a parole).
def test_descrizione_tooltime_uguale_a_prima():
    descrizione = _lista_tool()[0].description
    assert "nome IANA" in descrizione
    assert "sono le ore 10 e 32 minuti" in descrizione and "due punti" in descrizione


# Verifica che la resource restituisca il testo del file indicato da PREFERENZE_FILE.
def test_resource_restituisce_il_testo(tmp_path, monkeypatch):
    file = tmp_path / "prefs.json"
    file.write_text('{"lingua": "inglese"}', encoding="utf-8")
    monkeypatch.setenv("PREFERENZE_FILE", str(file))
    contenuti = _con_client(lambda c: c.read_resource(URI_PREFERENZE))
    assert contenuti[0].text == '{"lingua": "inglese"}'


# Verifica che un file salvato con il BOM (Blocco note) arrivi senza il carattere del BOM.
def test_resource_con_bom(tmp_path, monkeypatch):
    file = tmp_path / "prefs.json"
    file.write_text('{"stile": "dettagliato"}', encoding="utf-8-sig")
    monkeypatch.setenv("PREFERENZE_FILE", str(file))
    contenuti = _con_client(lambda c: c.read_resource(URI_PREFERENZE))
    assert contenuti[0].text == '{"stile": "dettagliato"}'


# Verifica che un file mancante dia un errore MCP che lo dice (l'host usera' i predefiniti).
def test_resource_file_mancante(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFERENZE_FILE", str(tmp_path / "manca.json"))
    with pytest.raises(Exception, match="non trovato"):
        _con_client(lambda c: c.read_resource(URI_PREFERENZE))


# Verifica che un percorso relativo parta dalla cartella del progetto, non da quella corrente.
def test_percorso_relativo_alla_cartella_del_progetto(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFERENZE_FILE", "config/preferenze.json")
    monkeypatch.chdir(tmp_path)
    assert percorso_preferenze() == CARTELLA_PROGETTO / "config" / "preferenze.json"


# Verifica che senza PREFERENZE_FILE si usi config/preferenze.json.
def test_percorso_predefinito(monkeypatch):
    monkeypatch.delenv("PREFERENZE_FILE", raising=False)
    assert percorso_preferenze() == CARTELLA_PROGETTO / "config" / "preferenze.json"


# Verifica che il file versionato contenga i valori predefiniti decisi nella spec.
def test_preferenze_versionate_sono_i_predefiniti():
    testo = (CARTELLA_PROGETTO / "config" / "preferenze.json").read_text(encoding="utf-8")
    assert json.loads(testo) == {"lingua": "italiano", "fuso": "Europe/Rome",
                                 "stile": "sintetico"}


# Verifica una chiamata vera di tooltime attraverso MCP (tools/call), con l'istante fisso.
def test_tooltime_via_mcp(monkeypatch):
    monkeypatch.setattr(orologio, "_adesso",
                        lambda: datetime(2026, 3, 1, 11, 0, 0, tzinfo=timezone.utc))
    risultato = _con_client(
        lambda c: c.call_tool("tooltime", {"fuso": "Asia/Tokyo", "parte": "ora"}))
    assert risultato.content[0].text == "Tokyo: sono le ore 20 in punto"


# Verifica che il server avviato come processo non scriva il banner di FastMCP: comparirebbe nel
# terminale della chat a ogni avvio e a ogni tools/call (visto nella CLI vera).
def test_server_senza_banner():
    import subprocess
    import sys
    # stdin vuoto: il server legge la fine dell'input e si chiude da solo
    finito = subprocess.run([sys.executable, "-m", "mcp_assistente.server"], input="",
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            cwd=CARTELLA_PROGETTO)
    assert "FastMCP" not in finito.stderr and "FastMCP" not in finito.stdout


# --- prompt (step 5) ---

# testo dell'unico messaggio restituito da un prompt (prompts/get)
def _testo_prompt(nome, argomenti):
    risultato = _con_client(lambda c: c.get_prompt(nome, argomenti))
    # un solo messaggio, dell'utente: e' la "domanda" che entra nella cronologia
    assert len(risultato.messages) == 1 and risultato.messages[0].role == "user"
    return risultato.messages[0].content.text


# Verifica che i due prompt siano pubblicati con descrizioni e argomenti, e che non siano tool.
def test_prompt_pubblicati_e_non_tool():
    prompts = _con_client(lambda c: c.list_prompts())
    assert [p.name for p in prompts] == ["spiega", "riassumi_conversazione"]
    assert prompts[0].description == DESCRIZIONE_SPIEGA
    assert prompts[1].description == DESCRIZIONE_RIASSUMI
    assert [(a.name, a.required) for a in prompts[0].arguments] == [("argomento", True),
                                                                    ("livello", False)]
    assert [(a.name, a.required) for a in prompts[1].arguments] == [("stile", False)]
    # argomenti senza descrizione: FastMCP vi aggiungerebbe "Provide as a JSON string..."
    assert all(a.description is None for p in prompts for a in p.arguments)
    assert [t.name for t in _lista_tool()] == ["tooltime"]


# Verifica il testo di spiega per ogni livello: domanda fissa piu' la frase del livello.
@pytest.mark.parametrize("livello", ["base", "intermedio", "avanzato"])
def test_spiega_per_livello(livello):
    testo = _testo_prompt("spiega", {"argomento": "MCP", "livello": livello})
    assert testo == f"Spiegami MCP. {LIVELLI[livello]}"


# Verifica che senza livello si usi base e che maiuscole e spazi del livello non contino.
def test_spiega_livello_predefinito_e_normalizzato():
    assert _testo_prompt("spiega", {"argomento": " MCP "}) == f"Spiegami MCP. {LIVELLI['base']}"
    assert (_testo_prompt("spiega", {"argomento": "MCP", "livello": " Avanzato "})
            == f"Spiegami MCP. {LIVELLI['avanzato']}")


# Verifica il testo di riassumi_conversazione per ogni stile e lo stile predefinito.
@pytest.mark.parametrize("stile", ["sintetico", "dettagliato"])
def test_riassumi_per_stile(stile):
    assert _testo_prompt("riassumi_conversazione", {"stile": stile}) == \
        f"{TESTO_RIASSUMI} {STILI[stile]}"
    assert _testo_prompt("riassumi_conversazione", {}) == f"{TESTO_RIASSUMI} {STILI['sintetico']}"


# Verifica che valori non ammessi e argomento vuoto diano un errore con il messaggio italiano.
@pytest.mark.parametrize("prompt,argomenti,messaggio", [
    ("spiega", {"argomento": "MCP", "livello": "pippo"},
     "livello non valido: 'pippo' (ammessi: base, intermedio, avanzato)"),
    ("riassumi_conversazione", {"stile": "lungo"},
     "stile non valido: 'lungo' (ammessi: sintetico, dettagliato)"),
    ("spiega", {"argomento": "  "}, "argomento vuoto: scrivi cosa spiegare"),
])
def test_valori_non_validi(prompt, argomenti, messaggio):
    with pytest.raises(Exception, match=re.escape(messaggio)):
        _con_client(lambda c: c.get_prompt(prompt, argomenti))
