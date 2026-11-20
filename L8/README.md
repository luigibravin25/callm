# Lezione 8 · Il retrieval come strumento dell'agente (su base delle lezioni 6 e 7)

Questa cartella contiene il lavoro delle lezioni 6 e 7, ripreso così com'era, e quello della lezione 8, che
collega la ricerca semantica all'agente. Ogni lezione ha la sua cartella (`L6/`, `L7/`, `L8/`): i comandi di
questo file si lanciano da `L8\`.

## Lezione 6 · Chat con agente LangGraph

Applicazione di chat: agente LangGraph (router, revisore, riassunto, strumenti via server MCP
`mcp_assistente`, per esempio l'orologio `get_current_time`) esposto come servizio HTTP; back-end FastAPI con le
chat in PostgreSQL; front-end React; tutto in Docker Compose (`docker compose up -d --build` →
http://127.0.0.1:8080). Cartelle: `assistente-laboratorio/`, `backend/`, `frontend/`, `tests_compose/`.
Descrizione completa, configurazione e comandi: [`../L6/README.md`](../L6/README.md).

## Lezione 7 · Ricerca semantica sul ricettario

Indice vettoriale in Qdrant costruito dal ricettario di Artusi (790 ricette, 1326 chunk) e ricerca top-k con la
fonte di ogni risultato (ricetta, capitolo, posizione del chunk). Esercizio 1: ingestion ripetibile con ID stabili
e filtro per capitolo. Esercizio 2: campo `contiene_dosi` con filtro `--solo-dosi`, titolo e capitolo nel testo
indicizzato. Cartella: `ricerca/`, istruzioni in [`ricerca/README.md`](ricerca/README.md); risultati della
valutazione in [`../L7/docs/retrieval.md`](../L7/docs/retrieval.md).

## Lezione 8 · RAG base e avanzato via MCP

La ricerca della lezione 7 diventa uno **strumento MCP** che l'agente usa quando serve, con risposte che citano
passaggi verificabili. Quattro esercizi, ognuno sul suo ramo:

| Esercizio | Cosa aggiunge | Stato |
|---|---|---|
| 1 · server MCP di ricerca | server FastMCP con il tool `search_documents` (query, `top_k` limitato, filtro), risultato con id citabile, errori del tool, un log per chiamata | fatto |
| 2 · aggancio all'agente | il server si aggiunge ai server MCP dell'agente; istruzioni per citare gli id e astenersi; controllo delle citazioni a fine turno | fatto |
| 3 · riscrittura e reranking | riscrittura/scomposizione della domanda con fusione RRF, reranking listwise, attivabili dalla configurazione; confronto di quattro configurazioni | fatto |
| 4 · soglie sullo score | due soglie dalla configurazione: passaggi affidabili, di affidabilità media, esclusi; calibrazione sugli score di bge-m3 | fatto |

Risultati, tracce e confronti della lezione 8: `docs/rag-agente.md` (si compila a ogni esercizio concluso).

Modelli (LM Studio sull'host, dalla configurazione): chat `google/gemma-4-e2b`; embedding
`text-embedding-bge-m3` (il modello `gpustack/bge-m3-GGUF`, vettori da 1024 valori).

## Avvio dei servizi per le prove reali

1. Qdrant di questa lezione (serve il `.env`, copiato da `.env.example`, con le `POSTGRES_*`):

   ```powershell
   docker compose up -d qdrant
   ```

2. LM Studio con `google/gemma-4-e2b` e `text-embedding-bge-m3` caricati.
3. Nella finestra di PowerShell in cui si lanciano gli script (Python non legge `.env`):

   ```powershell
   $env:EMBEDDING_MODEL = "text-embedding-bge-m3"
   ```

4. Collezione: se manca, da `L8\ricerca` `& ..\venv\Scripts\python.exe ingestion.py` (circa 5 minuti).

## Avvio dell'app completa con Docker Compose

L'app di chat della lezione 6 (front-end, back-end, agente, database) più Qdrant parte con un solo comando da
`L8\`. Percorso di una richiesta:

```text
browser → 127.0.0.1:8080 (frontend: nginx) ── /api → backend:8001 → agente:8000 → LM Studio sull'host
                                                        └→ database:5432
qdrant → 127.0.0.1:6333 (usato dagli script e dall'agente sull'host)
```

1. `.env` in `L8\` (copiato da `.env.example`, escluso da Git) con `POSTGRES_USER`, `POSTGRES_PASSWORD` (solo
   lettere, cifre, `-` e `_`) e `POSTGRES_DB`; gli indirizzi interni dei container li fissa `compose.yaml`.
2. LM Studio acceso sull'host con `google/gemma-4-e2b` caricato (l'agente nel container lo raggiunge con
   `host.docker.internal`).
3. Avvio e uso:

   ```powershell
   docker compose up -d --build        # costruisce le immagini e avvia i cinque servizi
   docker compose ps                   # stato: tutti "healthy" dopo qualche secondo
   start http://127.0.0.1:8080         # interfaccia di chat
   docker compose logs -f agente       # log dell'agente
   ```

4. Arresto:

   ```powershell
   docker compose down                 # ferma e rimuove i container: chat e collezione restano nei volumi
   docker compose down -v              # ATTENZIONE: cancella anche i volumi (tutte le chat e la collezione)
   ```

Solo `127.0.0.1:8080` (interfaccia) e `127.0.0.1:6333` (Qdrant) sono pubblicate, e solo su questo computer.

**La ricerca nel ricettario non è nell'app in Compose** (decisione dell'esercizio 2: solo host). L'agente nel
container ha soltanto l'orologio; le risposte con citazioni dal ricettario, le modalità avanzate e le soglie si
provano con l'agente avviato sull'host (`python -m app.api` + `python -m app.cli`, vedi la sezione «Test» qui sotto).
Configurazione completa dell'app e dettagli dei servizi: [`../L6/README.md`](../L6/README.md).

## Test

I test automatici non hanno bisogno di LM Studio né di Qdrant (embedder, modello e Qdrant finti o in memoria).
Ambiente: `& .\venv\Scripts\python.exe -m pip install -r requirements.txt` (venv di `L8`).

| Suite | Comando (PowerShell) | Esito (aggiornato all'esercizio 4, 2026-11-20) |
|---|---|---|
| Ricerca (lezione 7 e server MCP) | da `L8\ricerca`: `& ..\venv\Scripts\python.exe -m pytest -q` | 285 passati (126 della lezione 7 + 29 del server MCP + 93 dell'esercizio 3 + 37 dell'esercizio 4) |
| Agente (lezioni 5-6 e aggancio alla ricerca) | da `L8\assistente-laboratorio`: `& ..\venv\Scripts\python.exe -m pytest -q` | 381 passati, 12 saltati (345 di prima + 32 dell'esercizio 2 + 2 dell'esercizio 3 + 2 dell'esercizio 4) |
| Configurazione Compose | da `L8\`: `& .\venv\Scripts\python.exe -m pytest tests_compose -q` (serve la CLI `docker`) | 30 passati, 1 saltato (prova reale dello stack, solo con `$env:RUN_COMPOSE = "1"`) |

Prove reali della lezione 7 (servizi accesi), da `L8\ricerca`:

```powershell
& ..\venv\Scripts\python.exe valuta.py                     # sei domande con fonte attesa, tabella Markdown
& ..\venv\Scripts\python.exe valuta.py --solo-dosi
& ..\venv\Scripts\python.exe cerca.py "Che vino si usa nel pollo alla cacciatora?"
```

Prova reale del server MCP di ricerca (esercizio 1), da `L8\ricerca`: `prova_mcp.py` avvia il server in stdio
come farà l'agente; lo stdout mostra discovery e risultati, lo stderr la riga di log del server.

```powershell
& ..\venv\Scripts\python.exe prova_mcp.py --discovery                 # tool con schema e resource dei capitoli
& ..\venv\Scripts\python.exe prova_mcp.py "Che vino si usa nel pollo alla cacciatora?"
& ..\venv\Scripts\python.exe prova_mcp.py "brodo" --capitolo "DOLCI"  # errore del tool, senza traceback
```

Agente con la ricerca (esercizio 2), da `L8\assistente-laboratorio`, servizi accesi: il servizio avvia da solo
i due server MCP (orologio e ricerca); nel suo log compaiono `tools/list ricerca: search_documents`, la riga
`[mcp_ricerca]` di ogni ricerca e a fine turno `[citazioni] verificate=… sconosciute=… ricerche=… passaggi=…`.

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
& ..\venv\Scripts\python.exe -m app.api   # servizio dell'agente (log nel terminale)
& ..\venv\Scripts\python.exe -m app.cli   # in un'altra finestra: «Che vino si usa nel pollo alla cacciatora?»
```

Il router accetta ora anche le domande sul ricettario di Artusi (argomento `ricettario` in `config/ambito.toml`).
L'app completa in Docker Compose non ha la ricerca (il server di ricerca gira solo con l'agente sull'host).
`GET /stato` e i comandi `/prompt` riguardano solo il server dell'assistente (orologio, preferenze, prompt): con
quel server spento e la ricerca accesa `/stato` dice `non_disponibile` ma tra gli strumenti compare
`search_documents`; lo stato della ricerca si legge nel log di avvio (`tools/list ricerca` oppure
`server ricerca non disponibile`).

Modalità avanzata della ricerca (esercizio 3): la sceglie la configurazione del server, non il modello. Variabili
(nella finestra dell'agente vengono passate al server di ricerca):

| Variabile | Valori | Predefinito |
|---|---|---|
| `RICERCA_MODALITA` | `base`, `riscrittura`, `reranking`, `entrambe` | `base` |
| `LM_MODEL` | id del modello di chat di LM Studio (per esempio `google/gemma-4-e2b`) usato da riscrittura e reranking; serve solo se `RICERCA_MODALITA` non è `base` (con l'agente è già impostata e viene passata al server di ricerca) | nessuno |
| `RICERCA_CANDIDATI` | candidati per query, 10-20 | 10 |
| `RERANK_TETTO` | candidati mandati al reranking, 10-20 | 10 |

Riscrittura e reranking non mandano mai un errore all'agente: se gemma non risponde o risponde male, la ricerca
ripiega (sola domanda oppure ordine di partenza) e lo scrive nel campo `ripieghi` del risultato e nella riga di log
`[mcp_ricerca]`. Gli id restituiti dal reranking vengono normalizzati prima del controllo: spazi e parentesi quadre
tolti, maiuscole, «R» iniziale aggiunta se manca (gemma scrive a volte `455-1` invece di `R455-1`). Un id vale solo
se corrisponde a uno dei candidati mandati a gemma: quelli inventati o doppi sono scartati (`scartati=n` nel log) e,
se non ne resta nessuno valido, si ripiega. L'agente aspetta ogni chiamata MCP al massimo 60 s (`TIMEOUT_S`), perché
una ricerca in modalità `entrambe` dura fino a circa 28 s più l'avvio del server.

Confronto delle quattro configurazioni sulle dieci domande di `ricerca/valutazione/domande.toml` (circa 9 minuti
con gemma), da `L8\ricerca`, servizi accesi; tabelle e commento in `docs/rag-agente.md`:

```powershell
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:PYTHONUTF8 = "1"   # lettere accentate corrette anche reindirizzando l'uscita su file
& ..\venv\Scripts\python.exe confronta.py > confronto.md
$env:RICERCA_MODALITA = "entrambe"
& ..\venv\Scripts\python.exe prova_mcp.py "Quanti tuorli servono per la salsa maionese e quante uova per gli gnocchi alla romana?"
```

Soglie sullo score (esercizio 4), dalla configurazione del server: `SOGLIA_ALTA` (predefinito 0.60) e
`SOGLIA_BASSA` (0.51), numeri tra -1 e 1 con bassa ≤ alta. Ogni passaggio ha il campo `affidabilita` (`affidabile` da
0.60 in su, `media` da 0.51 a 0.60); sotto 0.51 è escluso e non arriva al modello. Lista vuota e passaggi di
affidabilità media sono dichiarati nella `nota` del risultato; l'agente dichiara «Da verificare sulla fonte.» o si
astiene. Calibrazione, confronto e tracce in `docs/rag-agente.md`; comandi, da `L8\ricerca` con i servizi accesi:

```powershell
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
$env:PYTHONUTF8 = "1"
& ..\venv\Scripts\python.exe calibra.py                  # score delle fonti e soglie proposte
& ..\venv\Scripts\python.exe confronta.py --soglie       # base con e senza soglie (senza LM_MODEL)
```
