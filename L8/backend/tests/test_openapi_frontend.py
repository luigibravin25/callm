# il contratto salvato nel front-end (frontend/openapi.json) deve coincidere con l'OpenAPI del back-end
# librerie standard: JSON e percorsi
import json
from pathlib import Path

# parti del back-end: applicazione e client dell'agente (mai usato: serve solo a crea_app)
from app.api import crea_app
from app.client_agente import ClientAgente

# file generato da npm run genera-api in L6/frontend
FILE = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
MSG_NON_ALLINEATO = ("openapi.json del front-end non allineato: eseguire npm run genera-api "
                     "in L6/frontend")


# nessun database: openapi() non esegue il lifespan e non apre connessioni
def test_openapi_del_frontend_allineato():
    assert FILE.exists(), MSG_NON_ALLINEATO
    salvato = json.loads(FILE.read_text(encoding="utf-8"))
    client = ClientAgente("http://non-usato", 1)
    try:
        # andata e ritorno in JSON: stessi tipi del file salvato
        attuale = json.loads(json.dumps(crea_app(None, client).openapi()))
    finally:
        client.chiudi()
    assert salvato == attuale, MSG_NON_ALLINEATO
