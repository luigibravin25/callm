# Assistente del laboratorio

App da terminale basata su un grafo LangGraph che parla con un modello locale in
LM Studio (API compatibile OpenAI). La cronologia resta solo in memoria. Il modello
riceve a ogni richiesta il prompt di sistema `SYSTEM_PROMPT` e dispone dello strumento
`tooltime(fuso, parte)` (data e/o ora attuali per un fuso IANA, es. `Asia/Tokyo`) e dello
strumento `toolconvert(valore, da, a)` (convertitore di unita'), entrambi locali, e dello
strumento `toolcalc(espressione)` (calcolatrice sicura) e dello strumento
`tooldate(operazione, data, da, giorni, tipo)` (giorni e scadenze), che chiamano via HTTP lo
stesso servizio FastAPI separato, e dei tool `search_catalog` e `get_item` del catalogo
prodotti e `add_note`, `list_notes`, `delete_note` delle note persistenti, scoperti all'avvio
da due server MCP (vedi «Catalogo locale (MCP)» e «Note persistenti (MCP)»). La risposta compare
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
| `CALC_BASE_URL` | indirizzo del servizio usato da `toolcalc` e `tooldate`, predefinito `http://127.0.0.1:8001` (in Compose `http://servizio:8001`) |

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
| `SYSTEM_PROMPT` | regola dell'orologio (`tooltime` senza `fuso` se manca il luogo) e regole del catalogo (cerca subito con `search_catalog`, dettagli con `get_item`, `[]` senza inventare, «Mostrati N di M» → richiamare con `max_results=M`) | anteposto a ogni richiesta al modello; non entra nella cronologia |
| `STREAM` | `True` | `True` = token per token, `False` = risposta in blocco |
| `HISTORY` | `True` | `True` = il modello ricorda i messaggi precedenti della sessione, `False` = ogni domanda parte da zero |
| `LOG_GRAFO` | `True` | `True` = mostra nel terminale i log del grafo (`app.graph`: chiamate agli strumenti, risultati, limite) |
| `LOG_HTTP` | `True` | `True` = mostra nel terminale le righe `HTTP Request: POST ...` verso LM Studio e verso il servizio HTTP (`/calcola`, `/giorni`) |

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
"Servizio HTTP non raggiungibile a ..." significa che il servizio non e' avviato o che
`CALC_BASE_URL` e' sbagliata; dopo 5 secondi senza risposta il messaggio e' "non ha risposto
entro 5 secondi"; anche errori HTTP e risposte malformate hanno un messaggio proprio.

## Giorni e scadenze (servizio FastAPI)

Lo strumento `tooldate` chiama l'endpoint `POST /giorni` dello stesso servizio della
calcolatrice (logica in `assistente-laboratorio/servizio/date_lavoro.py`). Come `toolcalc` e'
un wrapper `@tool` scritto a mano, con gli stessi messaggi per servizio spento, timeout ed errori.
Il modello passa le date come le scrive l'utente: le calcola il servizio.
**Risultato non normativo**: ogni risposta termina con "Calcolo indicativo, non ha valore legale."

Operazioni (`operazione`):
- `giorni`: giorni lavorativi e di calendario fino a `data`. Senza `da` (o con `da` = `oggi`)
  conta "quanto manca", oggi escluso; con una partenza scritta conta "dal ... al ...", estremi
  compresi. Esempio: dal 1 al 31 dicembre 2026 = 21 lavorativi, 31 di calendario.
- `scadenza`: data dopo `giorni` giorni `lavorativi` (predefinito) o di `calendario` da `da`
  (predefinita oggi); una scadenza di calendario che cade di sabato, domenica o in una festivita'
  slitta al primo giorno lavorativo.
- `giorno`: giorno della settimana, lavorativo o festivo (con il nome della festivita').

Giorni lavorativi: da lunedi' a venerdi', escluse le festivita'.

Formati di data accettati (uscita sempre ISO `AAAA-MM-GG` con il giorno della settimana):
`2026-12-25`; `25/12/2026`, `25-12-2026`, `25.12.2026` (sempre giorno/mese/anno); `25 dicembre 2026`,
`1° maggio 2027`; `oggi`, `domani`; il nome di una festivita' (`natale`, `pasqua 2027`,
`la liberazione`). Senza anno vale la prossima ricorrenza (da `da`, se indicata, altrimenti da oggi).
Anni ammessi dal 1900 al 2100; anni bisestili con la regola gregoriana (2000 e 2024 si', 1900,
2100 e 2027 no).

Rifiuti con il motivo: date impossibili (`31/02/2026`, `29/02/2027`), anni a 2 cifre (`25/12/26`),
separatori misti, formato sconosciuto, festivita' sconosciuta, data di arrivo gia' passata,
scadenze negative o oltre 3660 giorni.

Festivita' (file `assistente-laboratorio/servizio/festivita.json`, modificabile a mano e letto
all'avvio del servizio; se non e' valido il servizio non parte e il messaggio indica la voce):
Capodanno, Epifania, Pasqua e Lunedi' dell'Angelo (calcolate nel codice), Liberazione, Festa del
Lavoro, Festa della Repubblica, Ferragosto, San Francesco d'Assisi (4 ottobre, dal 2026),
Ognissanti, Immacolata, Natale, Santo Stefano. Le feste patronali non sono comprese.

Prova a mano con il servizio avviato:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/giorni -ContentType 'application/json' -Body '{"operazione":"giorno","data":"pasqua 2027"}'
```

Risposta: `data` `2027-03-28`, `giorno_settimana` `domenica`, `festivita` `["Pasqua"]` e
`avviso`. Una data rifiutata risponde `400` con `errore` (es. `29/02/2027`: "il 2027 non è
bisestile: febbraio ha 28 giorni"); un corpo non valido risponde `422`.

## Catalogo locale (MCP)

Lo stesso agente (`app.cli`) usa anche i tool di un server **MCP** sul catalogo prodotti
`assistente-laboratorio/mcp_catalogo/prodotti.csv` (50 prodotti). Gli altri strumenti restano dove
sono: `tooltime`, `toolconvert` locali, `toolcalc`, `tooldate` via HTTP.

- Server: `mcp_catalogo/server.py` (FastMCP, trasporto `stdio`) pubblica con `tools/list` i tool
  `search_catalog(query, max_results)` e `get_item(code)` e la resource `catalog://prodotti`
  (tutto il catalogo in JSON). La logica sta in `mcp_catalogo/catalogo.py`.
- Adattatore: `app/adattatore_mcp.py` (`langchain-mcp-adapters`) avvia il server come
  sottoprocesso, scopre i tool **una volta all'avvio** e li rende tool LangChain sincroni; poi
  `bind_tools` e il nodo strumenti del grafo come per gli altri strumenti. Un tool con uno schema
  `anyOf` viene scartato con un avviso. Dopo una modifica al server basta riavviare l'agente.
- Agente unico: all'avvio `app.cli` unisce i 4 strumenti di `STRUMENTI` e i tool scoperti
  (`carica_strumenti` in `app/cli.py`) e stampa
  `Strumenti: tooltime, toolconvert, toolcalc, tooldate, search_catalog, get_item`. Se il server MCP
  non parte, l'agente continua con i soli 4 strumenti e scrive su stderr
  `Avviso: catalogo MCP non disponibile (...)`. `max_tokens=8192` (chiamate in sequenza piu' il
  ragionamento). L'avvio e' quello di sempre (`python -m app.cli`): il server MCP parte da solo.

Regole dei tool:
- `search_catalog`: ricerca **esatta per parole intere** su codice, nome, categoria, stato e sede,
  senza maiuscole e accenti (`caffe` trova `Moka Caffè 3 Tazze`; `smartphon` non trova nulla).
  Articoli, preposizioni e congiunzioni sono ignorati (`casa e cucina` trova `Casa & Cucina`), e
  anche le parole generiche della domanda (`prodotto`, `articoli`, `qualcosa`, `qualche`,
  `catalogo`, `avete`…, elenco `PAROLE_GENERICHE`): `prodotto per la casa` trova `Casa & Cucina`.
  Restituisce `Trovati N prodotti: [...]` con solo `codice`, `nome`, `categoria` (la riga di testo
  davanti evita che gemma ripeta il JSON grezzo); nessun risultato = esattamente `[]`. `max_results` intero da
  1 a 20, predefinito 5; fuori intervallo o booleano e' un errore. Query vuota = errore.
  Se i prodotti trovati sono piu' di `max_results`, dopo la lista c'e' la riga
  `Mostrati 5 di 10 risultati: richiama search_catalog con max_results=10 per vederli tutti.`
  (oltre 20: «rendi la query più precisa»); `SYSTEM_PROMPT` dice al modello di richiamare
  il tool con quel `max_results` prima di rispondere.
- `get_item`: dettaglio completo (prezzo, quantita', stato, sede) da un codice come `PRD004`
  (anche `prd004`); un codice inesistente e' un errore che suggerisce `search_catalog`.
- Per «quanto costa lo smartphone?» il modello chiama `search_catalog` e poi `get_item`: con
  `MAX_STEPS=1` la sequenza si ferma al limite, serve almeno 2.

Contesto del modello: LM Studio puo' caricare gemma con un contesto di soli 4096 token (prompt,
schemi dei tool, cronologia, risultati e ragionamento insieme); con piu' chiamate in sequenza e la
cronologia attiva si supera e la chat mostra `Errore da LM Studio: Context size has been
exceeded. ...` (la sessione continua, la domanda fallita non entra nella cronologia). Rimedio:
ricaricare il modello in LM Studio con una «Context Length» piu' alta (es. 16384), oppure `exit`
e ripartire. `max_tokens=8192` non basta se il contesto caricato e' 4096.

Diagnosi: `Avviso: catalogo MCP non disponibile (...)` all'avvio = il server non parte (dipendenze mancanti,
CSV mancante, non UTF-8 o malformato: il motivo e' su stderr, es. `Catalogo non valido: ...`; un
CSV salvato da Excel con il BOM e' accettato); durante la chat un
`ToolMessage` «Server MCP del catalogo non disponibile» non chiude la sessione. Il server
riparte a ogni chiamata e scrive su stderr (lo stesso terminale della chat): l'adattatore lo
avvia con `FASTMCP_LOG_LEVEL=WARNING`, quindi le righe INFO (`Starting MCP server ...`) non
compaiono. Restano le righe `Error calling tool ...`: il log di FastMCP per un errore
restituito al modello (es. codice inesistente).

## Note persistenti (MCP)

Lo stesso agente usa un secondo server **MCP**, `assistente-laboratorio/mcp_note/` (FastMCP,
`stdio`), con un archivio **SQLite** che resta tra una sessione e l'altra. Gli strumenti
diventano 9: `Strumenti: tooltime, toolconvert, toolcalc, tooldate, search_catalog, get_item,
add_note, list_notes, delete_note`.

| Tool | Cosa cambia | Risultato | Annotazione MCP |
|---|---|---|---|
| `add_note(text)` | aggiunge una nota | `Nota 7 creata il 2026-11-05 15:40:12: ...` | crea |
| `list_notes(limit)` | niente (sola lettura) | `Note: [...]` dalla piu' recente, oppure `Nessuna nota salvata.` | `readOnlyHint` |
| `delete_note(note_id)` | elimina una nota | `Nota 3 eliminata: ... (creata il ...).` | `destructiveHint` |

- **Conferma**: prima di ogni tool con `destructiveHint` il programma chiede nel terminale
  `Eliminare la nota 3 "..."? (s/n)`; solo `s`, `si` o `sì` confermano. Altrimenti il modello
  riceve `Eliminazione annullata dall'utente: nessuna nota eliminata.` e nulla viene cancellato.
- **Doppioni**: nella stessa domanda, una seconda `add_note` con lo stesso testo non viene
  eseguita (`Nota già salvata in questa richiesta: ...`).
- **Errori**: testo vuoto o oltre 500 caratteri; `limit` fuori da 1-50; ID inesistente
  (`La nota 99 non esiste: nessuna nota eliminata.`); archivio non accessibile. Gli ID non vengono
  mai riusati.
- **Log** di ogni modifica su stderr: `[note] creata nota 7: ...`, `[note] eliminata nota 3: ...`;
  il grafo scrive anche `Eliminazione confermata/annullata dall'utente per delete_note {...}`.
- **Archivio**: `NOTE_DB`, predefinito `assistente-laboratorio/dati/note.sqlite` (cartella esclusa
  da Git, creata al primo uso). I test usano sempre un archivio temporaneo.

## Verifica dei server MCP (senza l'assistente)

Un processo acceso non dimostra che il server MCP funzioni: lo script `tests/mcp_verifica.py` e' un
client MCP che usa il protocollo vero (`tools/list`, `tools/call`), senza modello ne' grafo. Da
`assistente-laboratorio/`:

```powershell
& ..\venv\Scripts\python.exe -m tests.mcp_verifica catalogo
& ..\venv\Scripts\python.exe -m tests.mcp_verifica note     # archivio temporaneo: le note vere non si toccano
```

Ogni passo stampa `OK` o `ERRORE`; il codice d'uscita e' 0 solo se tutto e' OK.

MCP Inspector (serve Node.js, scarica il pacchetto alla prima esecuzione) mostra elenco dei tool,
annotazioni e chiamate fatte a mano. Da `assistente-laboratorio/`:

```powershell
$env:NOTE_DB = "$env:TEMP\note-inspector\note.sqlite"   # per non toccare le note vere
npx -y @modelcontextprotocol/inspector ..\venv\Scripts\python.exe -m mcp_note.server
npx -y @modelcontextprotocol/inspector --cli ..\venv\Scripts\python.exe -m mcp_note.server --method tools/list
```

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

Compose ha due servizi con la stessa immagine: `app` (la chat) e `servizio` (il servizio
FastAPI con `/calcola` e `/giorni`, comando `uvicorn`; fino all'esercizio 4 si chiamava
`calcolatrice`). `docker compose run --rm app` avvia prima `servizio` (container `l5-servizio-1`)
e aspetta che risponda a `/salute` (healthcheck); l'app lo raggiunge a `http://servizio:8001`
sulla rete interna. La porta 8001 non e' pubblicata sull'host.

Nella chat, con `LOG_HTTP = True`, ogni calcolo mostra la riga
`[httpx] HTTP Request: POST http://servizio:8001/calcola`. Il log del servizio (righe di
uvicorn come `"POST /calcola HTTP/1.1" 200`) sta nel container `servizio`: si vede da un
secondo terminale, sempre da questa cartella, con

```powershell
docker compose logs -f servizio
```

Prova rapida con input da pipe (`-T` perche' la pipe non ha un terminale):

```powershell
"Che ore sono a Tokyo?`nexit" | docker compose run --rm -T app
"quanto fa (3+4)^2 / 7?" | docker compose run --rm -T app
"quanti giorni lavorativi ci sono dal 1 dicembre 2026 al 31 dicembre 2026?" | docker compose run --rm -T app
```

Catalogo MCP: il server MCP gira nello stesso container dell'app (sottoprocesso `stdio`), non
serve un servizio Compose in piu'. Stesso comando di sempre:

```powershell
"quanto costa lo smartphone?`nexit" | docker compose run --rm -T app
```

Note persistenti: l'archivio sta nel volume con nome `note-dati` (montato su `/app/dati`,
`NOTE_DB=/app/dati/note.sqlite`), quindi le note restano tra un `docker compose run --rm app` e
il successivo. Verifica del server MCP delle note dentro il container:

```powershell
docker compose run --rm --no-deps app python -m tests.mcp_verifica note
```

Dopo ogni modifica al codice o a `assistente-laboratorio/app/llm.py` (`STREAM`, `LOG_GRAFO`,
`LOG_HTTP`, `SYSTEM_PROMPT`) rifai `docker compose build`: l'immagine contiene una copia di
`app/`, `servizio/`, `mcp_catalogo/`, `mcp_note/` e `tests/mcp_verifica.py`.

Pulizia: `docker compose down` ferma e rimuove container (anche `servizio`, che resta
attivo dopo `run`) e rete del progetto, ma **non** il volume delle note.
**Attenzione:** `docker compose down -v` cancella anche il volume `note-dati`, cioe' tutte le note;
`docker rmi assistente-laboratorio-l5` rimuove l'immagine.

