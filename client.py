import json
import threading
import time

import requests

BASE_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL = "google/gemma-4-e2b"
TEMPERATURE = 0.2
MAX_TOKENS = 1024
STREAM = True
SYSTEM_PROMPT = "Sei un assistente utile."
PROMPT = "Ciao, presentati in una frase."


def chat(messages: list[dict]) -> str:
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": STREAM,
    }

    stop = threading.Event()
    start = time.time()

    def status() -> None:
        while not stop.wait(0.5):
            print(
                f"\rElaborazione in corso ({time.time() - start:.0f}s)",
                end="",
                flush=True,
            )

    worker = threading.Thread(target=status, daemon=True)
    worker.start()

    def clear() -> None:
        stop.set()
        worker.join(1)
        print("\r" + " " * 45 + "\r", end="", flush=True)

    try:
        with requests.post(BASE_URL, json=payload, stream=True, timeout=300) as resp:
            resp.raise_for_status()

            if not STREAM:
                clear()
                content = resp.json()["choices"][0]["message"].get("content") or ""
                print(content)
                return content

            full = []
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                raw = line[len("data: "):]
                if raw == "[DONE]":
                    break
                chunk = json.loads(raw)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    if not full:
                        clear()
                    full.append(content)
                    print(content, end="", flush=True)
            clear()
            if not full:
                print("(risposta vuota dal modello)", end="")
            print()
            return "".join(full)
    finally:
        stop.set()


if __name__ == "__main__":
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": PROMPT},
    ]
    print(f"Domanda: {PROMPT}")
    print("Assistente:", end=" ", flush=True)
    try:
        chat(messages)
    except requests.RequestException as e:
        print(f"Errore: {e}")
        raise SystemExit(1)
