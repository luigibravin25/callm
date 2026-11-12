# Back-end · API e salvataggio delle chat (step 7)

Servizio FastAPI che gestisce le chat, le salva in PostgreSQL e inoltra le domande all'agente
HTTP (`assistente-laboratorio`, step 6). È l'unico punto di contatto del front-end: il
front-end non conosce l'agente. L'agente è senza stato: a ogni domanda il back-end gli passa la
cronologia e il riassunto restituiti al turno precedente e salva quelli nuovi.

```
Front-end ──HTTP──> Back-end (porta 8001) ──POST /chat──> Agente (porta 8000) ──> LM Studio
                        │
                        └── SQLAlchemy/psycopg ──> PostgreSQL (container l6-postgres, porta 5433)
```

## Dati

- Tabella `chat`: `id`, `titolo`, `creata_il`, `ultimo_messaggio_il`, `riassunto` e
  `cronologia_agente` (JSONB: l'ultima cronologia nel formato OpenAI restituita dall'agente).
  `riassunto` e `cronologia_agente` restano interni: l'API non li mostra.
- Tabella `messaggi`: la storia visibile completa (`ruolo` `utente`/`assistente`, `testo`,
  `strumenti` usati nel turno, `creato_il`). Non si accorcia quando l'agente riassume.
  Eliminando una chat si eliminano i suoi messaggi (`ON DELETE CASCADE`).
- Titolo: «Nuova chat» alla creazione, poi la prima domanda accorciata a 50 caratteri sul
  confine di parola con «…».
- Le tabelle si creano all'avvio (`create_all`), senza migrazioni: **se lo schema cambia si
  ricrea il database** (vedi sotto).

## Database di sviluppo (Docker, una volta sola)

PowerShell, scegliendo una password locale (mai in Git):

```powershell
docker run -d --name l6-postgres --restart unless-stopped `
  -e POSTGRES_USER=assistente -e POSTGRES_PASSWORD=<password> -e POSTGRES_DB=assistente `
  -p 127.0.0.1:5433:5432 -v l6-pgdata:/var/lib/postgresql postgres:18
docker exec l6-postgres pg_isready -U assistente      # "accepting connections"
docker exec l6-postgres createdb -U assistente assistente_test   # database dei test
```

Con l'immagine 18 il volume va su `/var/lib/postgresql` (non su `.../data`). I dati restano nel
volume `l6-pgdata` anche con `docker restart` o `docker rm`. Ricreare il database da zero
(cancella tutte le chat): `docker rm -f l6-postgres; docker volume rm l6-pgdata`, poi di nuovo
`docker run` e `createdb`.

## Configurazione (variabili d'ambiente)

| Variabile | Predefinito | Note |
|---|---|---|
| `DATABASE_URL` | obbligatoria | `postgresql+psycopg://assistente:<password>@127.0.0.1:5433/assistente` |
| `AGENTE_URL` | `http://127.0.0.1:8000` | stessa variabile della CLI |
| `AGENTE_TIMEOUT` | `300` | secondi di attesa massima per un turno dell'agente |
| `BACKEND_HOST` | `127.0.0.1` | |
| `BACKEND_PORTA` | `8001` | |
| `TEST_DATABASE_URL` | — | solo per i test; il nome del database deve finire con `_test` |

La password non compare mai nei log né negli errori (`***`).

## Avvio (tre terminali PowerShell)

```powershell
# 1. agente (da L6\assistente-laboratorio), con LM Studio acceso
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"; $env:LM_MODEL = "google/gemma-4-e2b"
& ..\venv\Scripts\python.exe -m app.api

# 2. back-end (da L6\backend)
$env:DATABASE_URL = "postgresql+psycopg://assistente:<password>@127.0.0.1:5433/assistente"
& ..\venv\Scripts\python.exe -m app.api        # ascolta su 127.0.0.1:8001, documentazione /docs

# 3. prove
$c = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/chat
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/chat/$($c.id)/messaggi" `
  -ContentType "application/json; charset=utf-8" -Body '{"testo": "Che ore sono a Tokyo?"}'
Invoke-RestMethod http://127.0.0.1:8001/chat
```

Per vedere il corpo degli errori da PowerShell 5.1: `curl.exe -s -w "%{http_code}" ...`.
Se il database non risponde all'avvio il servizio esce entro pochi secondi (timeout di connessione
5 s) con «Database non raggiungibile su ...: <motivo del driver>. È avviato il container
l6-postgres? DATABASE_URL è giusta?». Durante l'uso lo stesso motivo compare nel log `[backend]`.

## Endpoint

| Metodo e percorso | Corpo | Risposta |
|---|---|---|
| `POST /chat` | — | 201 `{id, titolo, creata_il}` |
| `GET /chat` | — | 200 `[{id, titolo, ultimo_messaggio_il}]`, le più recenti prima (`null` se senza messaggi) |
| `GET /chat/{id}` | — | 200 `{id, titolo, creata_il, ultimo_messaggio_il, messaggi: [{id, ruolo, testo, strumenti, creato_il}]}` |
| `POST /chat/{id}/messaggi` | `{"testo": "..."}` | 200 `{domanda, risposta}` (due messaggi) |
| `DELETE /chat/{id}` | — | 204 |

Date in ISO 8601 UTC. `id` è un intero tra 1 e 2147483647.

## Errori

Corpo sempre `{"errore": "<codice>", "messaggio": "<frase in italiano>"}`.

| Status | `errore` | Quando |
|---|---|---|
| 404 | `chat_non_trovata` | id inesistente (o chat eliminata mentre l'agente rispondeva) |
| 404 / 405 | `percorso_non_trovato` / `metodo_non_ammesso` | percorso o metodo sbagliato |
| 422 | `richiesta_non_valida` | testo vuoto o con il carattere NUL, campo mancante o in più, JSON non valido, id non valido |
| 400 | `richiesta_non_valida` | corpo che non è UTF-8 |
| 503 | `agente_non_raggiungibile` | l'agente non risponde su `AGENTE_URL` |
| 504 | `agente_in_timeout` | l'agente non risponde entro `AGENTE_TIMEOUT` |
| 502 | `risposta_agente_non_valida` | risposta illeggibile o inattesa (es. `AGENTE_URL` sbagliato) |
| 503 | `database_non_disponibile` | PostgreSQL non raggiungibile durante l'uso |
| 500 | `errore_interno` | errore imprevisto (dettagli nel log) |

Inoltrati dall'agente con lo stesso status e corpo (solo per l'invio di un messaggio): 422
`richiesta_non_valida`, 502 `errore_del_modello`, 503 `modello_non_raggiungibile` e
`mcp_non_disponibile`, 504 `modello_in_timeout`, 500 `errore_interno`.

**Agente non raggiungibile o in errore (o salvataggio della risposta fallito):** il turno è tutto o niente. La domanda si salva, poi si
chiama l'agente; se fallisce la domanda si cancella e arriva l'errore. La chat resta com'era e si
può riprovare con lo stesso testo (il front-end lo conserva).

## Log

Righe `[backend]` nel terminale del servizio: avvio (database e agente), `chat N creata`,
`domanda salvata, chiamo l'agente (cronologia N messaggi, riassunto sì/no)`, `risposta salvata
(strumenti: ...)`, WARNING `agente in errore (..., domanda N cancellata)`, `chat N eliminata`.
Le richieste verso l'agente compaiono come `[httpx]` (costante `LOG_HTTP` in `app/log.py`).

## Test

Da `L6\backend` (mai da `L6\`: le cartelle `app` dell'agente e del back-end andrebbero in
conflitto), con il container acceso:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://assistente:<password>@127.0.0.1:5433/assistente_test"
& ..\venv\Scripts\python.exe -m pytest -q
```

L'agente è sempre simulato (`httpx.MockTransport`). Senza `TEST_DATABASE_URL` i test del database
sono saltati con il motivo. Ogni test ricrea le tabelle del database `_test`.

## Limiti noti

- Un turno dell'agente fa più chiamate a LM Studio (router, modello, revisore, riassunto) e può
  superare `AGENTE_TIMEOUT`: il back-end risponde 504 e cancella la domanda mentre l'agente finisce
  il turno, il cui risultato si perde. Rimedio: alzare `AGENTE_TIMEOUT`.
- Due messaggi in parallelo sulla stessa chat non sono bloccati: leggono la stessa cronologia e
  l'ultimo a finire vince.
- Se il processo del back-end cade mentre aspetta l'agente, la domanda resta salvata senza
  risposta.
- Il database dei test e quello di sviluppo stanno nello stesso container.
