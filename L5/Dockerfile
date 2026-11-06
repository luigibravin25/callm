FROM python:3.14-slim

# utente non root
RUN useradd --create-home --uid 1000 utente
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistente-laboratorio/app/ app/
# servizio HTTP (calcolatrice e date): stessa immagine, avviato da compose (servizio "servizio")
COPY assistente-laboratorio/servizio/ servizio/
# server MCP del catalogo: avviato da app.cli come sottoprocesso stdio
COPY assistente-laboratorio/mcp_catalogo/ mcp_catalogo/
# server MCP delle note e script di verifica dei server MCP (python -m tests.mcp_verifica)
COPY assistente-laboratorio/mcp_note/ mcp_note/
COPY assistente-laboratorio/tests/mcp_verifica.py tests/
# server MCP del meteo (Open-Meteo, serve la rete); legge le date con servizio/date_lavoro.py
COPY assistente-laboratorio/mcp_meteo/ mcp_meteo/
# cartella dell'archivio delle note, dell'utente non root: il volume note-dati ne eredita i permessi
RUN mkdir -p /app/dati && chown utente:utente /app/dati
USER utente

# nessun segreto nell'immagine: la configurazione arriva dall'ambiente (compose.yaml)
CMD ["python", "-m", "app.cli"]
