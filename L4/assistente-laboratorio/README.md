# Assistente del laboratorio

App da terminale basata su un grafo LangGraph che parla con un modello locale in
LM Studio (API compatibile OpenAI). La cronologia resta solo in memoria. Il modello
dispone dello strumento `ora_corrente(fuso)` (ora attuale per un fuso IANA, es.
`Asia/Tokyo`). LM Studio resta sul computer host e non e' containerizzato.

## Configurazione

L'app legge solo variabili d'ambiente (non il file `.env`). `.env.example` e' un
promemoria dei valori; con Docker Compose il file `.env` (facoltativo) viene letto da Compose.

| Variabile | Significato |
|---|---|
| `LM_BASE_URL` | URL base di LM Studio, finisce con `/v1` (non `/chat/completions`) |
| `LM_MODEL` | identificativo del modello (da `GET /v1/models`) |
| `MAX_STEPS` | massimo di passaggi per strumenti a ogni domanda, predefinito 5 |

Senza `LM_BASE_URL` o `LM_MODEL` l'app si ferma con un errore che nomina la variabile.
In Docker `LM_BASE_URL` deve usare `host.docker.internal` al posto di `127.0.0.1`
(dentro il container `127.0.0.1` e' il container stesso). Se crei un `.env` per Compose,
usa quindi `LM_BASE_URL=http://host.docker.internal:1234/v1`.

## Avvio locale

Da questa cartella, con LM Studio avviato e il modello caricato:

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:MAX_STEPS = "5"   # facoltativa
& ..\venv\Scripts\python.exe -m app.cli
```

Scrivi un messaggio; `exit`, Ctrl+C o Ctrl+Z (EOF) per uscire.

## Strumenti, limite e log

- Se il modello chiede lo strumento, il grafo lo esegue e rimanda il risultato al modello.
- Raggiunto `MAX_STEPS`, l'app risponde con un messaggio e si ferma.
- Ogni chiamata agli strumenti (nome, argomenti, risultato) e' scritta nel terminale
  dal logger `app.graph` (livello INFO, su stderr).

## Test

```powershell
& ..\venv\Scripts\python.exe -m pytest
```

`test_compose_valido` esegue `docker compose config` (non serve LM Studio ne' un
container); viene saltato se `docker` non e' nel PATH.

Prove reali con LM Studio attivo (attivate esplicitamente):

```powershell
$env:RUN_LM_STUDIO = "1"
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
& ..\venv\Scripts\python.exe -m pytest tests\test_modello.py tests\test_instradamento.py -k reale
```

## Docker

LM Studio deve essere avviato sull'host. La configurazione predefinita (`compose.yaml`)
punta a `http://host.docker.internal:1234/v1` con `google/gemma-4-e2b`; i valori si
cambiano con variabili d'ambiente o con un `.env`.

```powershell
docker compose config                 # validazione (nessun container)
docker compose build                  # costruisce l'immagine (python:3.14-slim, utente non root)
"Ciao, rispondi con una parola`nexit" | docker compose run --rm -T app
```

`-T` serve perche' l'input da pipe non ha un terminale. Per la sessione interattiva
si usa `docker compose run --rm app` (non eseguita in questa verifica: richiede un terminale).

## Diagnosi

- **LM Studio spento o URL errato**: l'app stampa
  `Impossibile raggiungere LM Studio. Controlla che il server sia avviato e che LM_BASE_URL sia corretto.`
  e il ciclo continua. In Docker controlla che l'URL usi `host.docker.internal`.
- **Errore 400 del server**: l'app stampa
  `Il server di LM Studio ha risposto con errore 400. ...` e il ciclo continua.
  Con `google/gemma-4-e2b` osservato: `Error rendering prompt with jinja template:
  "Cannot call something that is not a function: got UndefinedValue"`. E' un problema
  del template di prompt di quel modello in LM Studio quando la richiesta contiene
  strumenti con parametri (l'app li allega a ogni richiesta). Vedi sotto.

## Stato delle verifiche

Eseguito:

- `python -m pytest`: 20 passati, 2 saltati (le prove reali, non attivate).
- `docker compose config` e `docker compose build`: ok.
- Raggiungibilita' di LM Studio dal container: ok (`http://host.docker.internal:1234/v1/models`
  risponde 200 dal container; le richieste di chat arrivano al server, che risponde 400).
- LM Studio risponde alla chat senza strumenti (richiesta diretta, risposta `Pace.`).

Non riuscito:

- Qualunque domanda tramite l'app (anche "Ciao, rispondi con una parola"), sia in locale sia
  in Docker, ottiene HTTP 400 dal template jinja del modello, perche' l'app allega sempre lo
  strumento. L'app mostra l'errore leggibile e il ciclo sopravvive.
- Le due prove reali (`-k reale`) falliscono con lo stesso 400.
- **Lo strumento orologio tramite il modello reale NON e' verificato.** E' verificato solo
  con modelli simulati nei test automatici.

Da provare: un modello il cui template accetti i tool (per esempio una variante
`lmstudio-community`, o un template sovrascritto in My Models > Prompt Template) e poi
ripetere la prova reale e la domanda "Che ore sono a Tokyo?".
