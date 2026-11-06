"""Script di verifica dei server MCP senza l'assistente (python -m tests.mcp_verifica)."""
# librerie standard: ambiente, processi figli, interprete, percorsi
import os
import subprocess
import sys
from pathlib import Path

# cartella assistente-laboratorio/: lo script si lancia da qui, come fa l'utente
PROGETTO = Path(__file__).resolve().parent.parent


# avvia lo script in un processo separato e ne cattura l'uscita (timeout di 3 minuti)
def _lancia(*argomenti, env=None):
    """Esegue lo script come farebbe l'utente e restituisce l'esito del processo."""
    return subprocess.run([sys.executable, "-m", "tests.mcp_verifica", *argomenti], cwd=PROGETTO,
                          capture_output=True, text=True, encoding="utf-8", timeout=180,
                          env=env)


# separa le righe stampate in passi riusciti e passi falliti
def _ok_ed_errori(esito):
    """Righe OK e righe ERRORE stampate dallo script."""
    righe = esito.stdout.splitlines()
    return [r for r in righe if r.startswith("OK")], [r for r in righe if r.startswith("ERRORE")]


# il server del catalogo risponde davvero via protocollo MCP: tutti i passi OK
def test_verifica_catalogo():
    """La verifica del catalogo termina con codice 0 e nessun ERRORE."""
    esito = _lancia("catalogo")  # azione: verifica completa del catalogo via stdio
    ok, errori = _ok_ed_errori(esito)
    # codice 0 (in caso contrario si mostra l'uscita) e almeno 4 passi OK, nessun ERRORE
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 4 and errori == []


# il server delle note supera il ciclo add -> list -> delete -> list e gli errori del contratto
def test_verifica_note():
    """La verifica delle note termina con codice 0 e nessun ERRORE."""
    esito = _lancia("note")
    ok, errori = _ok_ed_errori(esito)
    # codice 0 e almeno 6 passi OK, nessun ERRORE
    assert esito.returncode == 0, esito.stdout + esito.stderr
    assert len(ok) >= 6 and errori == []


# la verifica crea ed elimina note: non deve mai farlo sull'archivio dell'utente
def test_verifica_note_non_tocca_l_archivio_vero(tmp_path):
    """La verifica usa un archivio temporaneo: la nota dell'archivio vero resta."""
    from mcp_note.archivio import aggiungi, elenca
    # preparazione: un archivio "vero" (in una cartella temporanea) con una nota
    vero = tmp_path / "vero.sqlite"
    aggiungi("nota da non toccare", vero)
    # azione: lo script riceve NOTE_DB che punta a quell'archivio
    esito = _lancia("note", env=dict(os.environ, NOTE_DB=str(vero)))
    assert esito.returncode == 0, esito.stdout + esito.stderr
    # controllo: l'archivio contiene ancora solo la nota iniziale
    note, totale = elenca(10, vero)
    assert totale == 1 and note[0]["testo"] == "nota da non toccare"


# un nome sbagliato non avvia nulla: lo script spiega l'uso ed esce con errore
def test_server_sconosciuto():
    """Un server sconosciuto: uso stampato con i server ammessi e codice d'uscita diverso da 0."""
    esito = _lancia("inesistente")
    uscita = esito.stdout + esito.stderr  # il messaggio d'uso va su stderr
    # controlli: codice diverso da 0 e i tre server ammessi elencati nel messaggio
    assert esito.returncode != 0
    assert "catalogo" in uscita and "note" in uscita and "meteo" in uscita


# il meteo e' tra i server verificabili, senza lanciarlo (servirebbe la rete)
def test_meteo_tra_i_server_verificabili():
    """Il server meteo e' verificabile (la verifica vera usa la rete: si lancia a mano)."""
    from tests.mcp_verifica import MODULI
    assert MODULI["meteo"] == "mcp_meteo.server"  # il nome punta al modulo del server meteo
