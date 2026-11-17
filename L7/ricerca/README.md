# Ricerca semantica sul ricettario di Artusi (lezione 7)

Indice vettoriale **ripetibile** in Qdrant costruito da «La scienza in cucina e l'arte di mangiar bene» di
Pellegrino Artusi, e ricerca dei passaggi pertinenti a una domanda **con la loro fonte** (ricetta, capitolo,
posizione del chunk). Il retrieval è isolato: nessun modello generativo, nessun collegamento all'agente.

```
Ricettario.txt → corpus.py (790 ricette) → chunking.py → embedding.py (LM Studio) → indice.py (Qdrant)
                                                          domanda → embedding → Qdrant (top-k, filtro) → risultati
```

## 1. Corpus (fuori da Git)
Il file non è nella repository. Scaricarlo da Project Gutenberg, **eBook n. 59047**, formato «Plain Text
UTF-8», e salvarlo come:

```
L7/Ricettario/Ricettario.txt
```

La cartella `Ricettario/` è esclusa da Git. Il file si legge direttamente come testo: intestazione e licenza
Gutenberg, introduzioni dei capitoli, appendice e segnaposto delle illustrazioni vengono scartati; restano
790 ricette (numero, titolo, capitolo) in 23 capitoli.

## 2. Qdrant con Docker Compose
Da `L7\`, con Docker Desktop acceso:

```powershell
docker compose up -d qdrant
```

Compose legge tutto `compose.yaml`: anche per avviare solo Qdrant serve il `.env` (copiato da `.env.example`)
con le `POSTGRES_*`. Qdrant ascolta su `http://127.0.0.1:6333`; i dati restano nel volume `dati-qdrant`
(`docker compose down -v` li cancella).

## 3. LM Studio
Caricare il modello di embedding `bge-m3` (es. `gpustack/bge-m3-GGUF`, file `bge-m3-Q8_0.gguf`) e leggere il
suo id con `GET http://127.0.0.1:1234/v1/models`. Lo stesso modello serve per l'ingestion e per le domande.

## 4. Configurazione
Python **non legge `.env`**: in locale le variabili si impostano in ogni sessione di PowerShell, per esempio

```powershell
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"   # l'id letto da /v1/models
```

| Variabile | Predefinito | Note |
|---|---|---|
| `EMBEDDING_MODEL` | — | **obbligatoria** |
| `LM_BASE_URL` | `http://127.0.0.1:1234/v1` | LM Studio |
| `QDRANT_URL` | `http://127.0.0.1:6333` | |
| `QDRANT_COLLEZIONE` | `ricettario` | |
| `CORPUS_FILE` | `Ricettario/Ricettario.txt` | relativo a `L7/` |
| `CHUNK_STRATEGIA` | `paragrafi` | `paragrafi` o `caratteri` |
| `CHUNK_DIMENSIONE` | `1000` | caratteri |
| `CHUNK_OVERLAP` | `150` | caratteri, minore della dimensione |
| `TOP_K` | `5` | il codice ne restituisce al massimo 20 |

**Blocco del modello.** La collezione registra nel suo `metadata` il modello e la dimensione degli embedding.
Se `EMBEDDING_MODEL` è diversa, ingestion e ricerca si fermano prima di calcolare embedding: usare un'altra
collezione (`QDRANT_COLLEZIONE`) o cancellare quella esistente. A ogni ingestion completa il `metadata` registra
anche il chunking (es. `paragrafi 1000/150`) e la forma del testo indicizzato: `valuta.py` li stampa
nell'intestazione, così ogni tabella dice come era costruito l'indice.

**Overlap.** È «al massimo» `CHUNK_OVERLAP`: se il pezzo seguente è lungo quasi quanto la dimensione, la coda
ripresa dal chunk precedente si accorcia fino a sparire (nel corpus, con 1000/150: 3 confini, ricette 256, 423, 641).

**Testo indicizzato.** All'embedder ogni chunk arriva preceduto da titolo e capitolo della ricetta:

```
Ricetta: Pollo alla cacciatora
Capitolo: Fritti

<testo del chunk>
```

Nel payload e nei risultati resta il testo originale del chunk; la domanda va all'embedder così com'è.

**Dosi.** Ogni punto ha il campo `contiene_dosi`: vero se il chunk contiene per intero almeno una riga di
ingrediente della sua ricetta (nel file, le righe rientrate di 2 spazi). Indice `bool` su `contiene_dosi` e
`keyword` su `capitolo`. Per una collezione costruita prima del campo, `aggiorna_dosi.py` lo aggiunge a tutti i
punti senza ricalcolare gli embedding (legge il testo salvato nel payload).

## 5. Comandi (da `L7\ricerca`)

```powershell
# ingestion completa (ripetibile: stessi ID, nessun duplicato, orfani cancellati)
& ..\venv\Scripts\python.exe ingestion.py

# ricerca: top-k, filtro facoltativo per capitolo (maiuscole/minuscole indifferenti)
& ..\venv\Scripts\python.exe cerca.py "Che vino si usa nel pollo alla cacciatora?" -k 5
& ..\venv\Scripts\python.exe cerca.py "gnocchi di patate" --capitolo "minestre asciutte e di magro"
# solo tra i chunk con un elenco di ingredienti (combinabile con --capitolo)
& ..\venv\Scripts\python.exe cerca.py "dosi per gli gnocchi" --solo-dosi

# campo contiene_dosi sui punti esistenti, senza embedding (ripetibile)
& ..\venv\Scripts\python.exe aggiorna_dosi.py

# valutazione sulle domande di valutazione/domande.toml: tabella Markdown per docs/retrieval.md
& ..\venv\Scripts\python.exe valuta.py
& ..\venv\Scripts\python.exe valuta.py --solo-dosi

# test (senza LM Studio né Qdrant: embedder finto e Qdrant in memoria)
& ..\venv\Scripts\python.exe -m pytest -q
```

Ogni risultato di `cerca.py` mostra la fonte: `#1 · score 0.8123 · n. 89 «Gnocchi di patate» ·
MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 3 · con dosi`, poi il testo del chunk (`· con dosi` solo se il chunk
ha l'elenco degli ingredienti). `--help` funziona anche senza variabili d'ambiente. Gli errori previsti (variabile mancante,
corpus assente, LM Studio o Qdrant spenti, modello diverso) escono con un messaggio e codice 1.

## Struttura
- `app/config.py` variabili d'ambiente · `app/corpus.py` pulizia e 790 ricette · `app/chunking.py` strategie
  · `app/embedding.py` LM Studio · `app/indice.py` Qdrant (ID, metadata, orfani, ricerca) ·
  `app/valutazione.py` tabella · `app/avvio.py` log ed errori degli script.
- Scelte e motivazioni: specifiche degli esercizi 1 e 2 (fuori da Git); risultati in `docs/retrieval.md`.
