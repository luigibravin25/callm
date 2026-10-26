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
- Raggiunto `MAX_STEPS`, quella domanda si chiude con un messaggio di limite; la sessione
  continua e puoi scrivere la domanda successiva.
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

Con il template di prompt corretto in LM Studio (vedi [Diagnosi](#diagnosi)) entrambe le
prove reali passano: il modello chiama `ora_corrente` con `{"fuso": "Asia/Tokyo"}`.

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
  `Il server di LM Studio ha risposto con errore 400: <testo del server> ...` e il ciclo continua.
  Con `google/gemma-4-e2b` e' stato osservato: `Error rendering prompt with jinja template:
  "Cannot call something that is not a function: got UndefinedValue"`. Causa: nel template
  Jinja di Gemma 4 usato da LM Studio mancava la definizione della macro
  `format_type_argument`, richiamata per i parametri degli strumenti (l'app allega lo
  strumento a ogni richiesta). Correzione: aggiungere la macro prima di `format_parameters`
  nel template del modello (My Models > ingranaggio del modello > Prompt > Template Jinja),
  salvare e ricaricare il modello:

  ```jinja
  {%- macro format_type_argument(type_value) -%}
      {%- if type_value is string -%}
          <|"|>{{ type_value | upper }}<|"|>
      {%- else -%}
          [
          {%- for t in type_value -%}
              <|"|>{{ t | upper }}<|"|>
              {%- if not loop.last %},{% endif -%}
          {%- endfor -%}
          ]
      {%- endif -%}
  {%- endmacro -%}
  ```
- **`Unexpected character` nel template**: il template salvato in LM Studio contiene un errore
  di sintassi (per esempio righe troncate dopo una modifica a mano). Ripristina il template
  completo di Gemma 4 e riaggiungi la macro sopra.

## Stato delle verifiche

Eseguito:

- `python -m pytest`: 23 passati, 2 saltati (le prove reali, non attivate).
- Prove reali con `RUN_LM_STUDIO=1` (`-k reale`): 2 passate, con `google/gemma-4-e2b` e il
  template corretto in LM Studio.
- CLI locale: "Che ore sono a Tokyo?" produce nel log `Chiamata strumento ora_corrente con
  argomenti {'fuso': 'Asia/Tokyo'}` e il risultato dello strumento, poi la risposta finale.
- Docker: `docker compose run --rm -T app` con una domanda semplice e con "Che ore sono a
  Tokyo?": risposta ricevuta e chiamata a `ora_corrente` visibile nel log (container che
  raggiunge LM Studio tramite `host.docker.internal`).
- `docker compose config` e `docker compose build`: ok.

Da provare / limiti:

- La sessione interattiva `docker compose run --rm app` non e' stata eseguita (richiede un
  terminale); e' stata provata solo la modalita' con input da pipe.
- La correzione del template e' nella configurazione di LM Studio sul computer, non nel
  repository: chi riproduce il progetto deve applicarla (vedi [Diagnosi](#diagnosi)).
- Il modello non e' deterministico: in una prova di Docker ha risposto all'ora con un
  testo molto breve ("2:01"); la chiamata allo strumento c'e' stata, ma la forma della
  risposta varia.
