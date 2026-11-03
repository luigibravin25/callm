# Assistente del laboratorio

App da terminale basata su un grafo LangGraph che parla con un modello locale in
LM Studio (API compatibile OpenAI). La cronologia resta solo in memoria. Il modello
riceve a ogni richiesta il prompt di sistema `SYSTEM_PROMPT` e dispone dello strumento
`tooltime(fuso, parte)` (data e/o ora attuali per un fuso IANA, es. `Asia/Tokyo`) e dello
strumento `toolconvert(valore, da, a)` (convertitore di unita'), entrambi locali, e dello
strumento `toolcalc(espressione)` (calcolatrice sicura), che chiama via HTTP un servizio
FastAPI separato. La risposta compare
token per token (`STREAM = True`) oppure in blocco (`STREAM = False`). LM Studio resta
sul computer host e non e' containerizzato.

## Requisiti

Python 3.14 (provato in locale con 3.14.5; l'immagine Docker usa `python:3.14-slim`) e le librerie
di `requirements.txt`, con versioni fissate. Python non si puo' fissare in `requirements.txt`: la
versione e' indicata nel commento in testa al file e nel `Dockerfile`.

## Configurazione

L'app legge solo variabili d'ambiente, non il file `.env`. `assistente-laboratorio/.env.example`
e' un promemoria dei valori. Con Docker Compose il file `.env` di questa cartella (ignorato da
Git) fornisce `LM_MODEL`, `MAX_STEPS` e `FUSO_PREDEFINITO`.

| Variabile | Significato |
|---|---|
| `LM_BASE_URL` | URL base di LM Studio, finisce con `/v1` (non `/chat/completions`) |
| `LM_MODEL` | identificativo del modello (da `GET /v1/models`) |
| `MAX_STEPS` | massimo di passaggi per strumenti a ogni domanda, predefinito 5 |
| `FUSO_PREDEFINITO` | fuso IANA usato da `tooltime` quando l'utente non indica un luogo, predefinito `Europe/Rome` |
| `CALC_BASE_URL` | indirizzo del servizio calcolatrice usato da `toolcalc`, predefinito `http://127.0.0.1:8001` (in Compose `http://calcolatrice:8001`) |

Senza `LM_BASE_URL` o `LM_MODEL`, o con un `FUSO_PREDEFINITO` non valido, l'app si ferma con un
errore che nomina la variabile.
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
$env:FUSO_PREDEFINITO = "Europe/Rome"   # facoltativa
& ..\venv\Scripts\python.exe -m app.cli
```

Il terminale mostra la chat con `Tu:` per i tuoi messaggi e `Assistente:` per le risposte.
`exit`, Ctrl+C o Ctrl+Z (EOF) per uscire.

## Costanti in `assistente-laboratorio/app/llm.py`

| Costante | Valore | Effetto |
|---|---|---|
| `SYSTEM_PROMPT` | `"Sei un assistente utile. Se l'utente chiede l'ora o la data senza indicare un luogo, chiama tooltime senza l'argomento fuso."` | anteposto a ogni richiesta al modello; non entra nella cronologia |
| `STREAM` | `True` | `True` = token per token, `False` = risposta in blocco |
| `HISTORY` | `True` | `True` = il modello ricorda i messaggi precedenti della sessione, `False` = ogni domanda parte da zero |
| `LOG_GRAFO` | `True` | `True` = mostra nel terminale i log del grafo (`app.graph`: chiamate agli strumenti, risultati, limite) |
| `LOG_HTTP` | `True` | `True` = mostra nel terminale le righe `HTTP Request: POST ...` verso LM Studio e verso il servizio calcolatrice (`/calcola`) |

## Strumenti e limite

- Il modello richiama lo strumento con il nome `tooltime`. L'argomento `fuso` e' un nome IANA, facoltativo: se manca si usa `FUSO_PREDEFINITO` (domande come "che ore sono?" senza luogo); `parte` e' `"ora"`, `"data"` o `"entrambe"` (predefinito) e il modello lo sceglie in base alla domanda. Se lo chiede, il grafo lo esegue e rimanda il risultato al modello.
- Raggiunto `MAX_STEPS`, quella domanda si chiude con un messaggio di limite; la sessione
  continua e puoi scrivere la domanda successiva.
- Con `LOG_GRAFO = True` ogni chiamata agli strumenti (nome, argomenti, risultato) e' scritta
  nel terminale dal logger `app.graph` (livello INFO, su stderr).

## Convertitore di unita'

Lo strumento `toolconvert` converte un valore tra due unita' della stessa grandezza
(codice in `assistente-laboratorio/app/conversioni.py`). Il modello lo richiama come
`tooltime`, con lo stesso limite `MAX_STEPS`. Esempi di domanda: "quanti chilometri sono
10 miglia?", "converti 100 gradi Celsius in Fahrenheit".

- Argomenti: `valore` (numero finito), `da` e `a` (unita' di partenza e di arrivo).
- Grandezze (elenco chiuso): lunghezza, massa, tempo, temperatura, area, volume, velocita',
  accelerazione, forza, pressione, energia, potenza, frequenza, angolo, densita', portata,
  dati digitali.
- I simboli vanno scritti esatti, maiuscole comprese (`mbar` e' il millibar, `MB` il megabyte,
  `Gal` il galileo); i nomi in parole sono liberi (`chilometri`, `GRADI CELSIUS`, `metri quadrati`).
  Sono accettate anche varianti ASCII come `m/s^2`, `m2`, `um`, `degC`.
- Risultato in italiano: `10 miglia = 16,0934 chilometri` (virgola decimale, 6 cifre
  significative, notazione `1,5 × 10^-9` per valori molto grandi o molto piccoli).
- Errori restituiti al modello come testo: unita' non ammessa (`parsec`), conversione
  incompatibile (`km` in `kg`), unita' ambigua (`gallone`: va indicato `gal US` o `gal UK`),
  valore impossibile (temperatura sotto lo zero assoluto, valore non finito). Argomenti di
  tipo sbagliato (es. `valore` non numerico) sono respinti dallo schema e il grafo continua.

## Calcolatrice sicura (servizio FastAPI)

La logica della calcolatrice sta in un servizio HTTP separato
(`assistente-laboratorio/servizio/`: `calcolatrice.py` per il calcolo, `main.py` per FastAPI).
Nell'agente, lo strumento `toolcalc` in `app/tools.py` e' un wrapper `@tool` che chiama
l'endpoint con `httpx`; nome, descrizione e schema sono scritti a mano (nessuna discovery):
se l'endpoint cambia, il wrapper va aggiornato. Il grafo lo tratta come gli altri strumenti.
Esempio di domanda: "quanto fa (3+4)^2 / 7?".

- Ammessi: numeri con il punto decimale (`2.5`), `+ - * /`, potenza con `^` o `**`
  (associativa a destra: `2^3^2 = 512`), segno unario (`-2^2 = -4`), parentesi.
  Nessun uso di `eval`: l'espressione e' letta da un analizzatore scritto a mano.
- Rifiutati con il motivo: espressione vuota o oltre 200 caratteri, caratteri non ammessi
  (lettere, funzioni come `sqrt`, `%`, `=`, la virgola decimale `2,5`, `×`), `//`,
  sintassi non valida (`2+`, `2(3)`, parentesi non bilanciate), numeri malformati (`.5`),
  oltre 50 livelli di annidamento, divisione per zero, base negativa con esponente non
  intero, risultati oltre `1e100` in valore assoluto (`9^9^9`).
- Risultato in italiano come per `toolconvert`: `2^0.5 = 1,41421`.

Avvio del servizio in un secondo terminale, da `assistente-laboratorio/`:

```powershell
cd assistente-laboratorio
& ..\venv\Scripts\python.exe -m uvicorn servizio.main:app --port 8001
```

Endpoint:

| Richiesta | Risposta |
|---|---|
| `POST /calcola` con `{"espressione": "2^10"}` | `200` `{"espressione": "2^10", "risultato": 1024.0}` |
| `POST /calcola` con un'espressione rifiutata (`"2+x"`) | `400` `{"errore": "carattere non ammesso 'x' in posizione 3"}` |
| `POST /calcola` con un corpo non valido | `422` (FastAPI) |
| `GET /salute` | `200` `{"stato": "ok"}` |

Prova a mano con il servizio avviato:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/calcola -ContentType 'application/json' -Body '{"espressione":"2^10"}'
```

Diagnosi: il wrapper non fa mai cadere l'app e restituisce al modello un testo chiaro.
"Servizio calcolatrice non raggiungibile a ..." significa che il servizio non e' avviato o che
`CALC_BASE_URL` e' sbagliata; dopo 5 secondi senza risposta il messaggio e' "non ha risposto
entro 5 secondi"; anche errori HTTP e risposte malformate hanno un messaggio proprio.

## Docker

Prerequisiti: Docker Desktop avviato; LM Studio avviato sull'host con il modello caricato e il
server attivo. `Dockerfile`, `compose.yaml` e `.dockerignore` stanno in questa cartella:
tutti i comandi si lanciano da qui. La configurazione predefinita punta a
`http://host.docker.internal:1234/v1` con `google/gemma-4-e2b`. `LM_MODEL` e `MAX_STEPS` e
`FUSO_PREDEFINITO` si cambiano con variabili d'ambiente o con `.env`; l'URL con `DOCKER_LM_BASE_URL`.

```powershell
docker compose config                 # 1. validazione (nessun container)
docker compose build                  # 2. costruisce l'immagine assistente-laboratorio-l5 (python:3.14-slim, utente non root)
docker compose run --rm app           # 3. sessione interattiva (serve un terminale)
```

Compose ha due servizi con la stessa immagine: `app` (la chat) e `calcolatrice` (il servizio
FastAPI, comando `uvicorn`). `docker compose run --rm app` avvia prima `calcolatrice` e aspetta
che risponda a `/salute` (healthcheck); l'app lo raggiunge a `http://calcolatrice:8001` sulla
rete interna. La porta 8001 non e' pubblicata sull'host.

Prova rapida con input da pipe (`-T` perche' la pipe non ha un terminale):

```powershell
"Che ore sono a Tokyo?`nexit" | docker compose run --rm -T app
"quanto fa (3+4)^2 / 7?" | docker compose run --rm -T app
```

Dopo ogni modifica al codice o a `assistente-laboratorio/app/llm.py` (`STREAM`, `LOG_GRAFO`,
`LOG_HTTP`, `SYSTEM_PROMPT`) rifai `docker compose build`: l'immagine contiene una copia di
`app/` e di `servizio/`.

Pulizia: `docker compose down` ferma e rimuove container (anche `calcolatrice`, che resta
attivo dopo `run`) e rete del progetto;
`docker rmi assistente-laboratorio-l5` rimuove l'immagine.

