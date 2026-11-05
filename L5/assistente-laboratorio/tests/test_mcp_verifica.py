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
    """Righe OK e righe ERRORE stampate dallo script."""
    righe = esito.stdout.splitlines()
    return [r for r in righe if r.startswith("OK")], [r for r in righe if r.startswith("ERRORE")]


def test_verifica_catalogo():
    """La verifica del catalogo termina con codice 0 e nessun ERRORE."""
    esito = _lancia("catalogo")
    ok, errori = _ok_ed_errori(esito)
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 4 and errori == []


def test_verifica_note():
    """La verifica delle note termina con codice 0 e nessun ERRORE."""
    esito = _lancia("note")
    ok, errori = _ok_ed_errori(esito)
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 6 and errori == []


def test_verifica_note_non_tocca_l_archivio_vero(tmp_path):
    """La verifica usa un archivio temporaneo: la nota dell'archivio vero resta."""
    from mcp_note.archivio import aggiungi, elenca
    vero = tmp_path / "vero.sqlite"
    aggiungi("nota da non toccare", vero)
    esito = _lancia("note", env=dict(os.environ, NOTE_DB=str(vero)))
    assert esito.returncode == 0, esito.stdout + esito.stderr
    note, totale = elenca(10, vero)
    assert totale == 1 and note[0]["testo"] == "nota da non toccare"


def test_server_sconosciuto():
    """Un server sconosciuto: uso stampato con i server ammessi e codice d'uscita diverso da 0."""
    esito = _lancia("inesistente")
    uscita = esito.stdout + esito.stderr
    assert esito.returncode != 0
    assert "catalogo" in uscita and "note" in uscita and "meteo" in uscita


def test_meteo_tra_i_server_verificabili():
    """Il server meteo e' verificabile (la verifica vera usa la rete: si lancia a mano)."""
    from tests.mcp_verifica import MODULI
    assert MODULI["meteo"] == "mcp_meteo.server"
