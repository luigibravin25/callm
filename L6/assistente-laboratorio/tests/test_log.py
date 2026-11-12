# test della configurazione dei log: niente LangChain, flussi in cp1252 che non si rompono
import io
import subprocess
import sys

from app.log import rendi_sicuro


# Verifica che "→" su un flusso cp1252 (stderr rediretto su Windows) non sollevi un errore e
# arrivi come → (minore dello step 1).
def test_freccia_con_stderr_cp1252():
    grezzo = io.BytesIO()
    flusso = io.TextIOWrapper(grezzo, encoding="cp1252")
    rendi_sicuro(flusso)
    flusso.write("→")
    flusso.flush()
    assert b"\u2192" in grezzo.getvalue()


# Verifica che app.log si importi senza LangChain (lo usa anche la CLI client).
def test_log_senza_langchain():
    codice = "import app.log, sys; print('langchain_core' in sys.modules)"
    uscita = subprocess.run([sys.executable, "-c", codice], capture_output=True, text=True,
                            check=True)
    assert uscita.stdout.strip() == "False"
