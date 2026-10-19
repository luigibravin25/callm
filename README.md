# Client LLM

Client Python per un server LM Studio locale (API compatibile OpenAI).
`BASE_URL` e `MODEL` si configurano nel file `.env` (vedi `.env.example`).

## Installazione ed esecuzione

```bash
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe client.py
```

## Estensione 1: chiamata all'LLM

- `client.py` invia a `BASE_URL` una richiesta `POST` con system prompt e prompt
  (`model`, `messages`, `temperature`, `max_tokens`) usando `requests`.
- Con `STREAM = False` la risposta arriva in un unico JSON e il testo viene stampato a terminale.
- Gli errori di rete o del server (server spento, timeout, 404, 500) sono catturati
  e mostrati come `Errore: ...`.
- Se il modello esaurisce i token ragionando, o la risposta è troncata, il client lo segnala
  (`MAX_TOKENS` è 4096 per lasciare spazio al ragionamento di Gemma).
- `BASE_URL` e `MODEL` sono letti dal file `.env` con `python-dotenv`.

## Estensione 2: risposta in streaming e chat interattiva

- Con `STREAM = True` (valore attuale) il payload include `"stream": true` e la risposta
  arriva a pezzi (eventi `data: {...}`), parola per parola.
- Ogni evento è letto con `iter_lines` e interpretato con il modulo `json`;
  il testo di ogni frammento (`delta.content`) è stampato subito con `flush=True`.
- Il flusso termina con `data: [DONE]`; alla fine il client va a capo e restituisce
  il testo completo.
- I frammenti malformati vengono saltati senza interrompere il programma.
- La codifica è forzata a UTF-8: per `text/event-stream` `requests` assume ISO-8859-1
  e storpierebbe le lettere accentate.
- Con `STREAM = False` il testo compare tutto insieme.
- `client.py` è un ciclo `while`: scrivi una domanda qualsiasi e il modello risponde
  in streaming. Per uscire scrivi `esci` oppure premi `Ctrl+C` (anche durante la risposta).

## Estensione 3: history della conversazione

- Il client tiene una `history` con tutte le domande e le risposte della chat e la invia
  intera, insieme al system prompt, a ogni richiesta: il modello ricorda cosa è stato detto.
- Se una risposta è vuota, la domanda corrispondente viene tolta dalla `history`.
- La `history` esiste solo in memoria: all'uscita dalla chat (`esci`, `Ctrl+C` o errore)
  viene cancellata e il client stampa "Chat terminata, history cancellata.".
  Nulla viene salvato su disco: una nuova chat riparte da zero.
