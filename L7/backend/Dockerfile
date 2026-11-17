# immagine del back-end (step 9): API delle chat, PostgreSQL, inoltro all'agente
FROM python:3.14-slim

# log di Python subito visibili in "docker compose logs" (niente buffer)
ENV PYTHONUNBUFFERED=1

# utente non root con la sua cartella home
RUN useradd --create-home --uid 1000 utente
WORKDIR /app

# prima le dipendenze: questo livello resta in cache finché requirements.txt non cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# codice del back-end
COPY app/ app/

USER utente

# nessun segreto nell'immagine: DATABASE_URL e il resto arrivano da compose.yaml
CMD ["python", "-m", "app.api"]
