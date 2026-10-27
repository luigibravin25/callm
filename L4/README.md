# Assistente del laboratorio

App da terminale basata su un grafo LangGraph che parla con un modello locale in
LM Studio (API compatibile OpenAI). La cronologia resta solo in memoria. Il modello
riceve a ogni richiesta il prompt di sistema `SYSTEM_PROMPT` e dispone dello strumento
`tooltime(fuso, parte)` (data e/o ora attuali per un fuso IANA, es. `Asia/Tokyo`). La risposta compare
token per token (`STREAM = True`) oppure in blocco (`STREAM = False`). LM Studio resta
sul computer host e non e' containerizzato.

## Requisiti

Python 3.14 (provato in locale con 3.14.5; l'immagine Docker usa `python:3.14-slim`) e le librerie
di `requirements.txt`, con versioni fissate. Python non si puo' fissare in `requirements.txt`: la
versione e' indicata nel commento in testa al file e nel `Dockerfile`.

## Configurazione

L'app legge solo variabili d'ambiente, non il file `.env`. `assistente-laboratorio/.env.example`
e' un promemoria dei valori. Con Docker Compose il file `.env` di questa cartella (ignorato da
Git) fornisce `LM_MODEL` e `MAX_STEPS`.

| Variabile | Significato |
|---|---|
| `LM_BASE_URL` | URL base di LM Studio, finisce con `/v1` (non `/chat/completions`) |
| `LM_MODEL` | identificativo del modello (da `GET /v1/models`) |
| `MAX_STEPS` | massimo di passaggi per strumenti a ogni domanda, predefinito 5 |

Senza `LM_BASE_URL` o `LM_MODEL` l'app si ferma con un errore che nomina la variabile.
In Docker l'URL deve usare `host.docker.internal` al posto di `127.0.0.1` (dentro il
container `127.0.0.1` e' il container stesso): Compose lo imposta da solo e ignora
`LM_BASE_URL`; per cambiarlo si usa `DOCKER_LM_BASE_URL`.

## Avvio locale

Con LM Studio avviato e il modello caricato, da `assistente-laboratorio/`:

```powershell
cd assistente-laboratorio
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:MAX_STEPS = "5"   # facoltativa
& ..\venv\Scripts\python.exe -m app.cli
```

Il terminale mostra la chat con `Tu:` per i tuoi messaggi e `Assistente:` per le risposte.
`exit`, Ctrl+C o Ctrl+Z (EOF) per uscire.

## Costanti in `assistente-laboratorio/app/llm.py`

| Costante | Valore | Effetto |
|---|---|---|
| `SYSTEM_PROMPT` | `"Sei un assistente utile"` | anteposto a ogni richiesta al modello; non entra nella cronologia |
| `STREAM` | `True` | `True` = token per token, `False` = risposta in blocco |
| `HISTORY` | `True` | `True` = il modello ricorda i messaggi precedenti della sessione, `False` = ogni domanda parte da zero |
| `LOG_GRAFO` | `False` | `True` = mostra nel terminale i log del grafo (`app.graph`: chiamate agli strumenti, risultati, limite) |
| `LOG_HTTP` | `False` | `True` = mostra nel terminale le righe `HTTP Request: POST ...` verso LM Studio |

## Strumenti e limite

- Il modello richiama lo strumento con il nome `tooltime`. L'argomento `fuso` e' un nome IANA; `parte` e' `"ora"`, `"data"` o `"entrambe"` (predefinito) e il modello lo sceglie in base alla domanda. Se lo chiede, il grafo lo esegue e rimanda il risultato al modello.
- Raggiunto `MAX_STEPS`, quella domanda si chiude con un messaggio di limite; la sessione
  continua e puoi scrivere la domanda successiva.
- Con `LOG_GRAFO = True` ogni chiamata agli strumenti (nome, argomenti, risultato) e' scritta
  nel terminale dal logger `app.graph` (livello INFO, su stderr).

## Test

I test si lanciano da `assistente-laboratorio/`:

```powershell
cd assistente-laboratorio
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

Le prove reali verificano che il modello risponda e che chiami `tooltime` con `{"fuso": "Asia/Tokyo"}`
(richiedono il template di prompt corretto, vedi [DIAGNOSI](assistente-laboratorio/docs/DIAGNOSI.md)).

## Docker

Prerequisiti: Docker Desktop avviato; LM Studio avviato sull'host con il modello caricato e il
server attivo. `Dockerfile`, `compose.yaml` e `.dockerignore` stanno in questa cartella:
tutti i comandi si lanciano da qui. La configurazione predefinita punta a
`http://host.docker.internal:1234/v1` con `google/gemma-4-e2b`. `LM_MODEL` e `MAX_STEPS` si
cambiano con variabili d'ambiente o con `.env`; l'URL con `DOCKER_LM_BASE_URL`.

```powershell
docker compose config                 # 1. validazione (nessun container)
docker compose build                  # 2. costruisce l'immagine assistente-laboratorio-app (python:3.14-slim, utente non root)
docker compose run --rm app           # 3. sessione interattiva (serve un terminale)
```

Prova rapida con input da pipe (`-T` perche' la pipe non ha un terminale):

```powershell
"Che ore sono a Tokyo?`nexit" | docker compose run --rm -T app
```

Dopo ogni modifica al codice o a `assistente-laboratorio/app/llm.py` (`STREAM`, `LOG_GRAFO`,
`LOG_HTTP`, `SYSTEM_PROMPT`) rifai `docker compose build`: l'immagine contiene una copia di `app/`.

Pulizia: `docker compose down` ferma e rimuove container e rete del progetto;
`docker rmi assistente-laboratorio-app` rimuove l'immagine.

Problemi con LM Studio o col modello: [DIAGNOSI](assistente-laboratorio/docs/DIAGNOSI.md).
