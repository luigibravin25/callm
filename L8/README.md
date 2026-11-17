# Lezione 7 · Ricerca semantica sul ricettario (su base della lezione 6)

**Lezione 7:** indice vettoriale in Qdrant costruito dal ricettario di Artusi e ricerca dei passaggi
pertinenti a una domanda, con la loro fonte. Tutto in `ricerca/`: istruzioni complete in
[`ricerca/README.md`](ricerca/README.md) (dove scaricare il corpus, configurazione, comandi). La ricerca è
**isolata**: non è collegata all'agente (arriva con la lezione 8) e si prova a parte.

- **Esercizio 1:** pipeline di ingestion (790 ricette, chunking per paragrafi 1000/150, embedding
  `text-embedding-bge-m3` da LM Studio, 1326 punti in Qdrant con ID stabili) e ricerca top-k con filtro per
  capitolo.
- **Esercizio 2:** A, campo `contiene_dosi` con filtro `--solo-dosi` e script `aggiorna_dosi.py` (campo aggiunto
  senza ricalcolare gli embedding); B, titolo e capitolo davanti al chunk nel testo indicizzato.

**Risultati:** [`docs/retrieval.md`](docs/retrieval.md) raccoglie le prove reali: i conteggi delle ingestion
ripetute e la valutazione sulle sei domande con fonte attesa, alla partenza (esercizio 1), dopo A e dopo B
(esercizio 2), con due query commentate.

## Test automatici

Senza LM Studio né Qdrant (embedder finto e Qdrant in memoria), da `L7\ricerca`:

```powershell
& ..\venv\Scripts\python.exe -m pytest -q
```

## Prova con le domande (servizi accesi)

La valutazione cerca le sei domande di [`ricerca/valutazione/domande.toml`](ricerca/valutazione/domande.toml)
(gnocchi con 400 g di patate, cappelletti per un mangiatore moderato, vino del pollo alla cacciatora, gnocchi che
si sciolgono, cacciucco dell'Adriatico, tiramisù) e per ognuna dice in che posizione esce la ricetta attesa, con
quale score e se il chunk trovato contiene davvero l'informazione.

1. Avviare Qdrant, da `L7\` (serve il `.env` con le `POSTGRES_*`, perché Compose legge tutto il file):

   ```powershell
   docker compose up -d qdrant
   ```

2. Avviare LM Studio e caricare il modello di embedding `text-embedding-bge-m3`.
3. Nella stessa finestra di PowerShell in cui si lanciano gli script, impostare il modello (Python non legge
   `.env`):

   ```powershell
   $env:EMBEDDING_MODEL = "text-embedding-bge-m3"
   ```

4. Da `L7\ricerca`: se la collezione non c'è ancora, costruirla (circa 5 minuti), poi valutare:

   ```powershell
   & ..\venv\Scripts\python.exe ingestion.py
   & ..\venv\Scripts\python.exe valuta.py
   & ..\venv\Scripts\python.exe valuta.py --solo-dosi
   ```

   `valuta.py` stampa una tabella Markdown: per ogni domanda la fonte attesa, la posizione della fonte tra i
   primi k (o «assente»), il suo score e se il chunk contiene l'informazione; per il tiramisù, che non è nel
   libro, gli score dei risultati. Le tabelle registrate sono in `docs/retrieval.md`.

5. Una domanda qualsiasi, con la fonte di ogni risultato:

   ```powershell
   & ..\venv\Scripts\python.exe cerca.py "Che vino si usa nel pollo alla cacciatora?"
   & ..\venv\Scripts\python.exe cerca.py "dosi per gli gnocchi" --capitolo "minestre asciutte e di magro" --solo-dosi
   ```

## Base ereditata dalla lezione 6

Questa cartella contiene anche l'applicazione di chat con agente LangGraph della lezione 6
(`assistente-laboratorio/`, `backend/`, `frontend/`, `compose.yaml` con i suoi quattro servizi, `tests_compose/`),
invariata. Descrizione completa, configurazione e comandi in [`../L6/README.md`](../L6/README.md): i comandi che
lì partono da `L6\`, qui si lanciano da `L7\`. Il servizio `qdrant` di `compose.yaml` è della lezione 7.
