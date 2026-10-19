import json
import sys
import threading
import time

import requests

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

BASE_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL = "google/gemma-4-e2b"
TEMPERATURE = 0.2
MAX_TOKENS = 1024
STREAM = True
SYSTEM_PROMPT = "Sei un assistente utile."
PROMPT = "Ciao"
EMPTY_REASONING_MSG = (
    "(risposta vuota: i token sono finiti nel ragionamento, aumenta MAX_TOKENS)"
)


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
                choice = resp.json()["choices"][0]
                content = choice["message"].get("content") or ""
                reasoning = choice["message"].get("reasoning_content")
                print(content)
                if not content and reasoning:
                    print(EMPTY_REASONING_MSG)
                elif choice.get("finish_reason") == "length":
                    print("(risposta troncata: aumenta MAX_TOKENS)")
                return content

            full = []
            reasoned = False
            finish_reason = None
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                raw = line[len("data: "):]
                if raw == "[DONE]":
                    break
                chunk = json.loads(raw)
                choice = chunk["choices"][0]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta", {})
                if delta.get("reasoning_content"):
                    reasoned = True
                content = delta.get("content")
                if content:
                    if not full:
                        clear()
                    full.append(content)
                    print(content, end="", flush=True)
            clear()
            if not full and reasoned:
                print(EMPTY_REASONING_MSG, end="")
            elif not full:
                print("(risposta vuota dal modello)", end="")
            elif finish_reason == "length":
                print("(risposta troncata: aumenta MAX_TOKENS)", end="")
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
