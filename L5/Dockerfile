FROM python:3.14-slim

# utente non root
RUN useradd --create-home --uid 1000 utente
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistente-laboratorio/app/ app/
# servizio HTTP della calcolatrice: stessa immagine, avviato da compose con un altro comando
COPY assistente-laboratorio/servizio/ servizio/
# server MCP del catalogo: avviato da app.cli come sottoprocesso stdio
COPY assistente-laboratorio/mcp_catalogo/ mcp_catalogo/
USER utente

# nessun segreto nell'immagine: la configurazione arriva dall'ambiente (compose.yaml)
CMD ["python", "-m", "app.cli"]
