# Retrieval sul ricettario di Artusi · resoconto

Lezione 7. Indice e ricerca in `ricerca/` (istruzioni in `ricerca/README.md`).

## Esercizio 1 · situazione di partenza (2026-11-17)

Configurazione: modello di embedding `text-embedding-bge-m3` (LM Studio, dimensione 1024, coseno),
Qdrant `qdrant/qdrant:v1.20.2` in Docker Compose, collezione `ricettario`, chunking `paragrafi` 1000/150
caratteri, k = 5. Corpus: 790 ricette in 23 capitoli.

### Conteggi delle due ingestion

| ingestion | ricette | chunk | punti scritti | orfani cancellati | punti nella collezione | durata |
|---|---|---|---|---|---|---|
| 1 (collezione nuova) | 790 | 1326 | 1326 | 0 | 1326 | 264.9 s |
| 2 (ripetuta) | 790 | 1326 | 1326 | 0 | 1326 | 261.1 s |

Stesso numero di punti: gli ID dipendono dalla posizione del chunk (UUID v5 di `"<numero>-<indice>"`), quindi
la seconda ingestion aggiorna gli stessi punti senza duplicarli. Nella collezione: indice `keyword` su
`capitolo` e `metadata` `{"modello_embedding": "text-embedding-bge-m3", "dimensione": 1024}`; con un altro
modello in `EMBEDDING_MODEL` ingestion e ricerca si fermano con un errore, prima di calcolare embedding.

### Valutazione di partenza

Domande in `ricerca/valutazione/domande.toml`; fonte attesa decisa prima. «Il chunk contiene
l'informazione» = l'indizio della domanda compare nel primo chunk della fonte tra i primi k.

| domanda | fonte attesa | posizione della fonte | score della fonte | il chunk contiene l'informazione | primo risultato |
|---|---|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | 89 | 1 | 0.6659 | sì | n. 89 «Gnocchi di patate» 0.6659 |
| Quanti cappelletti bastano a chi mangia con moderazione? | 7 | 1 | 0.6097 | sì | n. 7 «Cappelletti all'uso di Romagna» 0.6097 |
| Che vino si usa nel pollo alla cacciatora? | 208 | assente | — | — | n. 268 «Pollo alla Marengo» 0.5125 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | 89 | 1 | 0.6285 | sì | n. 89 «Gnocchi di patate» 0.6285 |
| Com'è il cacciucco sulle coste dell'Adriatico? | 455 | 2 | 0.5648 | no | n. 481 «Acciughe alla marinara» 0.5793 |
| Come si prepara il tiramisù? | nessuna | — | 0.5961, 0.5907, 0.5885, 0.5852, 0.5837 | — | n. 344 «Sformato di pasta lievita» 0.5961 |

Riproducibilità: `valuta.py` eseguito dopo ciascuna delle due ingestion ha dato due tabelle **identiche**
(stesse posizioni, fonti, sì/no e score).

Osservazioni:
- 4 domande su 5 con fonte trovano la ricetta attesa tra i primi 5; 3 su 5 la trovano al primo posto con il
  chunk che contiene l'informazione.
- Pollo alla cacciatora (208): assente anche tra i primi 20; il primo risultato è un altro pollo
  (n. 268 «Pollo alla Marengo»). Il titolo della ricetta non è nel testo indicizzato.
- Cacciucco (455): fonte al 2° posto, ma con il chunk 2 di 3, che non contiene «brodetto» (è nel chunk 1).
- Tiramisù (non è nel libro): gli score dei risultati (0.58-0.60) sono simili a quelli delle risposte giuste
  (0.56-0.67): lo score da solo non basta a dire «non c'è».
