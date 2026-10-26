# Assistente del laboratorio

App da terminale basata su un grafo LangGraph che parla con un modello locale in
LM Studio. La cronologia resta solo in memoria. Il modello dispone dello strumento
`ora_corrente(fuso)` (ora attuale per un fuso IANA, es. `Asia/Tokyo`).

## Configurazione

Copia `.env.example` come promemoria dei valori e imposta le variabili d'ambiente
in PowerShell (l'app legge solo le variabili d'ambiente, non il file `.env`):

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:MAX_STEPS = "5"   # facoltativa, predefinito 5
```

`LM_BASE_URL` e' l'URL base (finisce con `/v1`), non l'URL di `/chat/completions`.
Senza `LM_BASE_URL` o `LM_MODEL` l'app si ferma con un errore che nomina la variabile.

## Avvio

Da questa cartella, con LM Studio avviato e il modello caricato:

```powershell
& ..\venv\Scripts\python.exe -m app.cli
```

Scrivi un messaggio; `exit`, Ctrl+C o Ctrl+Z (EOF) per uscire.

## Strumenti, limite e log

- Se il modello chiede lo strumento, il grafo lo esegue e rimanda il risultato al modello.
- `MAX_STEPS` (predefinito 5) e' il massimo di passaggi per strumenti a ogni domanda:
  raggiunto il limite, l'app risponde con un messaggio e si ferma.
- Ogni chiamata agli strumenti (nome, argomenti, risultato) e' scritta nel terminale
  dal logger `app.graph` (livello INFO, su stderr).

## Test

```powershell
& ..\venv\Scripts\python.exe -m pytest
```

Prova reale con LM Studio attivo (due domande collegate):

```powershell
$env:RUN_LM_STUDIO = "1"
& ..\venv\Scripts\python.exe -m pytest tests\test_modello.py -k reale
```

Prova reale dello strumento (richiede LM Studio attivo e un modello con template
compatibile con i tool):

```powershell
$env:RUN_LM_STUDIO = "1"
& ..\venv\Scripts\python.exe -m pytest tests\test_instradamento.py -k reale
```
