"""Script di verifica dei server MCP senza l'assistente (python -m tests.mcp_verifica)."""
import os
import subprocess
import sys
from pathlib import Path

PROGETTO = Path(__file__).resolve().parent.parent


def _lancia(*argomenti, env=None):
    """Esegue lo script come farebbe l'utente e restituisce l'esito del processo."""
    return subprocess.run([sys.executable, "-m", "tests.mcp_verifica", *argomenti], cwd=PROGETTO,
                          capture_output=True, text=True, encoding="utf-8", timeout=180,
                          env=env)


def _ok_ed_errori(esito):
    righe = esito.stdout.splitlines()
    return [r for r in righe if r.startswith("OK")], [r for r in righe if r.startswith("ERRORE")]


def test_verifica_catalogo():
    esito = _lancia("catalogo")
    ok, errori = _ok_ed_errori(esito)
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 4 and errori == []


def test_verifica_note():
    esito = _lancia("note")
    ok, errori = _ok_ed_errori(esito)
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 6 and errori == []


def test_verifica_note_non_tocca_l_archivio_vero(tmp_path):
    from mcp_note.archivio import aggiungi, elenca
    vero = tmp_path / "vero.sqlite"
    aggiungi("nota da non toccare", vero)
    esito = _lancia("note", env=dict(os.environ, NOTE_DB=str(vero)))
    assert esito.returncode == 0, esito.stdout + esito.stderr
    note, totale = elenca(10, vero)
    assert totale == 1 and note[0]["testo"] == "nota da non toccare"


def test_server_sconosciuto():
    esito = _lancia("meteo")
    assert esito.returncode != 0
    assert "catalogo" in (esito.stdout + esito.stderr) and "note" in (esito.stdout + esito.stderr)
