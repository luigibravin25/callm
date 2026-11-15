# immagine dell'agente (step 9): servizio HTTP LangGraph + server MCP stdio come sottoprocesso
FROM python:3.14-slim

# log di Python subito visibili in "docker compose logs" (niente buffer)
ENV PYTHONUNBUFFERED=1

# utente non root con la sua cartella home (la eredita anche il processo del server MCP)
RUN useradd --create-home --uid 1000 utente
WORKDIR /app

# prima le dipendenze: questo livello resta in cache finché requirements.txt non cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# codice dell'agente, server MCP (avviato dall'agente con python -m mcp_assistente.server)
COPY app/ app/
COPY mcp_assistente/ mcp_assistente/
# ambito e preferenze predefiniti; con Compose la cartella arriva dall'host in sola lettura
COPY config/ config/

USER utente

# nessun segreto nell'immagine: la configurazione arriva dalle variabili d'ambiente (compose.yaml)
CMD ["python", "-m", "app.api"]
