# Librerie standard: json per leggere lo stream, os per le variabili
# d'ambiente, sys per la gestione della console
import json
import os
import sys

# requests: invia la richiesta HTTP al server dell'LLM
# python-dotenv: legge le variabili dal file .env
import requests
from dotenv import load_dotenv

# La console Windows usa l'encoding cp1252: senza questa riga i caratteri
# speciali prodotti dal modello (accenti rari, ecc.) fanno crashare lo script.
# Con errors="replace" i caratteri non rappresentabili diventano "?"
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass  # se la console non lo permette, si continua senza

# Cerca il file .env nella cartella del progetto e carica le variabili
# in esso contenute come variabili d'ambiente
load_dotenv()

# Endpoint dell'API (compatibile OpenAI) e nome del modello:
# entrambi letti dal file .env, non scritti qui nel codice
BASE_URL = os.environ["BASE_URL"]  # es. http://127.0.0.1:1234/v1/chat/completions
MODEL = os.environ["MODEL"]  # es. google/gemma-4-e2b

# --- Parametri di generazione ---
TEMPERATURE = 0.2  # casualità: basso = risposte sempre simili, alto = creative
MAX_TOKENS = 1024  # massimo di token totali (pensiero + risposta)
STREAM = True  # True = la risposta arriva token per token, False = tutta insieme

# --- Testo della conversazione ---
SYSTEM_PROMPT = "Sei un assistente utile."  # istruzioni di sistema (ruolo "system")
PROMPT = "Ciao"  # la domanda da inviare (ruolo "user")

# Messaggio d'errore mostrato quando il modello "pensa" a lungo e il budget
# MAX_TOKENS finisce prima di produrre la risposta visibile
EMPTY_REASONING_MSG = (
    "(risposta vuota: i token sono finiti nel ragionamento, aumenta MAX_TOKENS)"
)


def chat(messages: list[dict]) -> str:
    """Invia i messaggi all'LLM e restituisce la risposta come stringa."""
    # Corpo della richiesta nel formato richiesto dall'API (stile OpenAI):
    # messages è la lista completa della conversazione (system, user, ...)
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": STREAM,
    }

    try:
        # POST al server; stream=True = leggiamo la risenza man mano che arriva;
        # timeout=300 secondi di attesa massima
        with requests.post(BASE_URL, json=payload, stream=True, timeout=300) as resp:
            # Se il server risponde con errore (404, 500, ...) lancia un'eccezione
            resp.raise_for_status()

            # --- Caso STREAM=False: risposta unica in formato JSON ---
            if not STREAM:
                # choices[0] = prima (e unica) risposta generata
                choice = resp.json()["choices"][0]
                # content = testo visibile; reasoning_content = "pensiero" nascosto
                content = choice["message"].get("content") or ""
                reasoning = choice["message"].get("reasoning_content")
                print(content)
                if not content and reasoning:
                    # Il modello ha solo pensato, non ha prodotto testo
                    print(EMPTY_REASONING_MSG)
                elif choice.get("finish_reason") == "length":
                    # finish_reason "length" = token esauriti, risposta troncata
                    print("(risposta troncata: aumenta MAX_TOKENS)")
                return content

            # --- Caso STREAM=True: la risposta arriva in righe "data: {...}" ---
            full = []  # lista dei pezzi di testo ricevuti, uniti alla fine
            reasoned = False  # diventa True se il modello invia il suo "pensiero"
            finish_reason = None  # conterrà "stop" (fine) o "length" (troncata)

            # Per "text/event-stream" requests assume ISO-8859-1 e storpia gli
            # accenti (à -> Ã\xa0): si forza UTF-8, la codifica usata dal server
            resp.encoding = "utf-8"

            # iter_lines legge lo stream una riga alla volta (decodificata in testo)
            for line in resp.iter_lines(decode_unicode=True):
                # Le righe utili iniziano con "data: "; le altre (vuote, ecc.) si saltano
                if not line or not line.startswith("data: "):
                    continue
                # Si toglie il prefisso "data: " per avere solo il JSON
                raw = line[len("data: "):]
                # "[DONE]" è il segnale di fine stream inviato dal server
                if raw == "[DONE]":
                    break
                # Parsing del JSON del pezzo corrente
                # Un chunk malformato (JSON rotto o senza "choices") viene saltato
                try:
                    chunk = json.loads(raw)
                    choice = chunk["choices"][0]
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                # L'ultimo chunk contiene il motivo di fine generazione
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                # delta contiene le differenze rispetto al testo già inviato
                delta = choice.get("delta", {})
                # Il reasoning_content è il pensiero del modello: qui viene solo
                # rilevato (per diagnosticare risposte vuote), non stampato
                if delta.get("reasoning_content"):
                    reasoned = True
                # Il testo visibile della risposta è in delta.content
                content = delta.get("content")
                if content:
                    full.append(content)
                    # end="" evita il a capo dopo ogni pezzo; flush=True forza
                    # la scritta subito sullo schermo (importante per lo stream)
                    print(content, end="", flush=True)

            # A fine stream: avvisi nel caso la risposta sia vuota o troncata
            if not full and reasoned:
                # Solo pensiero, nessun testo: quasi sempre token finiti
                print(EMPTY_REASONING_MSG, end="")
            elif not full:
                # Nessun testo e nessun pensiero: risposta completamente vuota
                print("(risposta vuota dal modello)", end="")
            elif finish_reason == "length":
                # Risposta presente ma tagliata perché MAX_TOKENS è finito
                print("(risposta troncata: aumenta MAX_TOKENS)", end="")
            print()  # a capo finale
            return "".join(full)  # restituisce la risposta completa come stringa

    except KeyboardInterrupt:
        # L'utente ha premuto Ctrl+C durante la risposta: si segnala e si
        # rilancia, così il ciclo di chat in __main__ può terminare
        print("\n(interrotto)")
        raise


# Questo blocco viene eseguito solo se lo script è avviato direttamente
# (python client.py), non quando viene importato da un altro script
if __name__ == "__main__":
    # La cronologia parte dal solo messaggio di sistema e cresce a ogni turno,
    # così il modello ricorda la conversazione
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("Chat con l'LLM. Scrivi 'esci' o premi Ctrl+C per terminare.")
    try:
        while True:
            domanda = input("\nTu: ").strip()
            if not domanda:
                continue
            if domanda.lower() == "esci":
                break
            messages.append({"role": "user", "content": domanda})
            # Il modello può mettere parecchi secondi prima del primo token
            print("Assistente: ", end="", flush=True)
            try:
                # Stampa la risposta in streaming e la restituisce completa
                risposta = chat(messages)
            except requests.RequestException as e:
                # Server spento, URL sbagliato, timeout, errore di rete...
                print(f"Errore: {e}")
                raise SystemExit(1)
            if risposta:
                messages.append({"role": "assistant", "content": risposta})
            else:
                # Risposta vuota: si toglie la domanda per non sporcare la cronologia
                messages.pop()
    except (KeyboardInterrupt, EOFError):
        print()
    print("Chat terminata.")
