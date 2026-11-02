FROM python:3.14-slim

# utente non root
RUN useradd --create-home --uid 1000 utente
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistente-laboratorio/app/ app/
USER utente

# nessun segreto nell'immagine: la configurazione arriva dall'ambiente (compose.yaml)
CMD ["python", "-m", "app.cli"]
