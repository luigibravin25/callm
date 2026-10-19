import json
import os
import sys

import requests
from dotenv import load_dotenv

# Su Windows la console usa cp1252: con errors="replace" i caratteri
# speciali del modello non fanno più crashare lo script
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# Carica le variabili dal file .env nella cartella del progetto
load_dotenv()

# Configurazione letta da .env (BASE_URL e MODEL)
BASE_URL = os.environ["BASE_URL"]
MODEL = os.environ["MODEL"]

# Parametri di generazione
TEMPERATURE = 0.2  # più basso = risposte più deterministiche
MAX_TOKENS = 1024  # budget totale: ragionamento + risposta
STREAM = True  # True = token per token, False = risposta in blocco

# Testo fisso della conversazione
SYSTEM_PROMPT = "Sei un assistente utile."
PROMPT = "Ciao"

# Messaggio mostrato quando il modello pensa a lungo e i token finiscono
# prima di produrre la risposta vera e propria
EMPTY_REASONING_MSG = (
    "(risposta vuota: i token sono finiti nel ragionamento, aumenta MAX_TOKENS)"
)


def chat(messages: list[dict]) -> str:
    """Invia i messaggi all'LLM e stampa la risposta (in stream se STREAM=True).

    Restituisce il testo della risposta ("" se vuota o interrotta).
    """
    # Corpo della richiesta API compatibile OpenAI
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": STREAM,
    }

    try:
        # stream=True: la risposta arriva a pezzi (SSE), timeout di 300s
        with requests.post(BASE_URL, json=payload, stream=True, timeout=300) as resp:
            resp.raise_for_status()

            # --- Modalità non stream: una singola risposta JSON ---
            if not STREAM:
                choice = resp.json()["choices"][0]
                content = choice["message"].get("content") or ""
                reasoning = choice["message"].get("reasoning_content")
                print(content)
                if not content and reasoning:
                    # Il modello ha solo "pensato": nessuna risposta visibile
                    print(EMPTY_REASONING_MSG)
                elif choice.get("finish_reason") == "length":
                    # Token esauriti: la risposta è stata troncata
                    print("(risposta troncata: aumenta MAX_TOKENS)")
                return content

            # --- Modalità stream: righe "data: {...}" una alla volta ---
            full = []  # pezzi di risposta raccolti
            reasoned = False  # True se il modello ha inviato del "pensiero"
            finish_reason = None  # "stop" oppure "length"

            for line in resp.iter_lines(decode_unicode=True):
                # Ignora righe vuote e quelle che non sono eventi SSE
                if not line or not line.startswith("data: "):
                    continue
                raw = line[len("data: "):]
                # Fine dello stream
                if raw == "[DONE]":
                    break

                chunk = json.loads(raw)
                choice = chunk["choices"][0]
                # Il server indica fine generazione nell'ultimo chunk
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                delta = choice.get("delta", {})
                # Il reasoning_content è il "pensiero" del modello: qui viene
                # rilevato ma non stampato
                if delta.get("reasoning_content"):
                    reasoned = True

                # Il testo visibile è solo in delta.content
                content = delta.get("content")
                if content:
                    full.append(content)
                    print(content, end="", flush=True)

            # Messaggi a fine stream secondo il caso riscontrato
            if not full and reasoned:
                print(EMPTY_REASONING_MSG, end="")
            elif not full:
                print("(risposta vuota dal modello)", end="")
            elif finish_reason == "length":
                print("(risposta troncata: aumenta MAX_TOKENS)", end="")
            print()
            return "".join(full)

    except KeyboardInterrupt:
        # Ctrl+C durante la generazione
        print("\n(interrotto)")
        return ""


if __name__ == "__main__":
    # Conversazione a turno singolo: system + user
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": PROMPT},
    ]
    print(f"Domanda: {PROMPT}")
    print("Assistente (in attesa del modello, puo' richiedere qualche secondo)...")
    try:
        chat(messages)
    except requests.RequestException as e:
        # Server spento, endpoint errato, timeout, ecc.
        print(f"Errore: {e}")
        raise SystemExit(1)
