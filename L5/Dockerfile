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
# server MCP delle note e script di verifica dei server MCP (python -m mcp_verifica)
COPY assistente-laboratorio/mcp_note/ mcp_note/
COPY assistente-laboratorio/mcp_verifica.py .
# cartella dell'archivio delle note, dell'utente non root: il volume note-dati ne eredita i permessi
RUN mkdir -p /app/dati && chown utente:utente /app/dati
USER utente

# nessun segreto nell'immagine: la configurazione arriva dall'ambiente (compose.yaml)
CMD ["python", "-m", "app.cli"]
