"""Scrive frontend/openapi.json con l'OpenAPI attuale del back-end (contratto del front-end).

Non serve il database né la rete: openapi() non esegue il lifespan del servizio.
Uso (da L6/frontend): npm run genera-api, oppure ..\\venv\\Scripts\\python.exe scripts\\esporta_openapi.py
"""
# librerie standard: JSON, percorsi, percorso di ricerca dei moduli
import json
import sys
from pathlib import Path

# cartelle: frontend/ (destinazione) e backend/ (codice del back-end da importare)
FRONTEND = Path(__file__).resolve().parents[1]
BACKEND = FRONTEND.parent / "backend"
DESTINAZIONE = FRONTEND / "openapi.json"


def main() -> None:
    # il pacchetto app del back-end si importa da L6/backend
    sys.path.insert(0, str(BACKEND))
    from app.api import crea_app
    from app.client_agente import ClientAgente

    # client mai usato: crea_app lo richiede, openapi() non chiama l'agente
    client = ClientAgente("http://non-usato", 1)
    try:
        documento = crea_app(None, client).openapi()
    finally:
        client.chiudi()
    # UTF-8 leggibile (accenti non tradotti in \u...), indentato, a capo finale
    testo = json.dumps(documento, ensure_ascii=False, indent=2) + "\n"
    DESTINAZIONE.write_text(testo, encoding="utf-8", newline="\n")
    print(f"openapi.json scritto ({len(documento.get('paths', {}))} percorsi)")


if __name__ == "__main__":
    main()
