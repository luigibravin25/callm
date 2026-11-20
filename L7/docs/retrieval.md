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

## Esercizio 2 · A: campo `contiene_dosi` e filtro (2026-11-17)

`contiene_dosi` è vero se il chunk contiene per intero almeno una riga di ingrediente della sua ricetta (righe
rientrate di 2 spazi nel file). I punti dell'esercizio 1 hanno ricevuto il campo con `aggiorna_dosi.py`, che
legge il testo salvato nel payload e non calcola embedding:

| esecuzione | punti aggiornati | con dosi | senza dosi | embedding ricalcolati | durata |
|---|---|---|---|---|---|
| 1 | 1326 | 417 | 909 | 0 | 0.3 s |
| 2 (ripetuta) | 1326 | 417 | 909 | 0 | 0.2 s |

Il vettore del punto «n. 89, chunk 1» letto prima e dopo è identico. Nella collezione: indice `bool` su
`contiene_dosi` accanto a quello `keyword` su `capitolo`.

### Valutazione dopo A

Senza filtro la tabella è **identica** a quella di partenza (stesse righe): A non cambia nulla per chi non
usa il filtro. L'intestazione dice `chunking: non registrato` perché la collezione è quella dell'esercizio 1,
costruita prima che il `metadata` registrasse il chunking.

Con `--solo-dosi` (stesso k = 5):

| domanda | fonte attesa | posizione della fonte | score della fonte | il chunk contiene l'informazione | primo risultato |
|---|---|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | 89 | 1 | 0.6659 | sì | n. 89 «Gnocchi di patate» 0.6659 |
| Quanti cappelletti bastano a chi mangia con moderazione? | 7 | 4 | 0.5108 | no | n. 55 «Tortelli» 0.5892 |
| Che vino si usa nel pollo alla cacciatora? | 208 | assente | — | — | n. 730 «Claret cup (bibita inglese)» 0.4558 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | 89 | 1 | 0.5992 | sì | n. 89 «Gnocchi di patate» 0.5992 |
| Com'è il cacciucco sulle coste dell'Adriatico? | 455 | assente | — | — | n. 688 «Crema alla francese» 0.4265 |
| Come si prepara il tiramisù? | nessuna | — | 0.5907, 0.5816, 0.5788, 0.5729, 0.5706 | — | n. 351 «Sformato di riso colle rigaglie» 0.5907 |

Confronto con la partenza:
- Gnocchi 400 g: invariato (1° posto, «sì»): il chunk con l'indizio è quello con l'elenco.
- Gnocchi che si sciolgono: resta 1° con l'indizio (il chunk della 89 con l'elenco contiene anch'esso «si
  liquefecero»); score da 0.6285 a 0.5992.
- Cappelletti: dal 1° al 4° posto, e il chunk trovato (con l'elenco) non contiene «mangiatore discreto»,
  che sta in un chunk senza dosi.
- Pollo alla cacciatora e cacciucco: le ricette 208 e 455 non hanno elenco, quindi il filtro le esclude.
- Tiramisù: score simili (0.57-0.59).

Il filtro aiuta quando la domanda chiede proprio le dosi; nasconde la fonte quando l'informazione è nella
prosa o la ricetta non ha elenco.

### Query commentata 1: filtri combinati

`cerca.py "dosi per gli gnocchi di patate" --capitolo "minestre asciutte e di magro" --solo-dosi`

```
#1 · score 0.5488 · n. 89 «Gnocchi di patate» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 2 · con dosi
#2 · score 0.4924 · n. 103 «Spaghetti da quaresima» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 1 · con dosi
#3 · score 0.4552 · n. 106 «Spaghetti con la balsamella» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 1 · con dosi
#4 · score 0.4442 · n. 55 «Tortelli» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 1 · con dosi
#5 · score 0.4386 · n. 101 «Spaghetti coi naselli» · MINESTRE ASCIUTTE E DI MAGRO · chunk 1 di 1 · con dosi
```

Tutti i risultati sono del capitolo richiesto e hanno l'elenco degli ingredienti: i due filtri si applicano
insieme durante la ricerca in Qdrant. Al primo posto il chunk della ricetta 89 con «Patate grosse e gialle,
grammi 400» e «Farina di grano, grammi 150»; seguono altre minestre asciutte con dosi, nessuna senza elenco.

## Esercizio 2 · B: titolo e capitolo nel testo indicizzato (2026-11-17)

All'embedder ogni chunk arriva come `Ricetta: <titolo>\nCapitolo: <Capitolo>\n\n<testo>`; nel payload e nei
risultati resta il testo originale. Ingestion sulla collezione esistente (non ricreata):

| ingestion | ricette | chunk | punti scritti | orfani cancellati | punti nella collezione | durata |
|---|---|---|---|---|---|---|
| B | 790 | 1326 | 1326 | 0 | 1326 | 280.2 s |

Punti prima 1326, dopo 1326; nessuna riga «creata la collezione» nel log. Il `metadata` registra ora
`chunking: paragrafi 1000/150` e `testo_indicizzato: titolo e capitolo + testo`; i campi `contiene_dosi` e gli
indici sono rimasti.

### Valutazione dopo B

Senza filtro:

| domanda | fonte attesa | posizione della fonte | score della fonte | il chunk contiene l'informazione | primo risultato |
|---|---|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | 89 | 1 | 0.7173 | sì | n. 89 «Gnocchi di patate» 0.7173 |
| Quanti cappelletti bastano a chi mangia con moderazione? | 7 | 1 | 0.5569 | sì | n. 7 «Cappelletti all'uso di Romagna» 0.5569 |
| Che vino si usa nel pollo alla cacciatora? | 208 | 1 | 0.6136 | sì | n. 208 «Pollo alla cacciatora» 0.6136 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | 89 | 1 | 0.6162 | sì | n. 89 «Gnocchi di patate» 0.6162 |
| Com'è il cacciucco sulle coste dell'Adriatico? | 455 | 2 | 0.5344 | sì | n. 481 «Acciughe alla marinara» 0.5549 |
| Come si prepara il tiramisù? | nessuna | — | 0.5447, 0.5371, 0.5365, 0.5340, 0.5337 | — | n. 649 «Dolce Torino» 0.5447 |

Con `--solo-dosi`:

| domanda | fonte attesa | posizione della fonte | score della fonte | il chunk contiene l'informazione | primo risultato |
|---|---|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | 89 | 1 | 0.7173 | sì | n. 89 «Gnocchi di patate» 0.7173 |
| Quanti cappelletti bastano a chi mangia con moderazione? | 7 | 1 | 0.5409 | no | n. 7 «Cappelletti all'uso di Romagna» 0.5409 |
| Che vino si usa nel pollo alla cacciatora? | 208 | assente | — | — | n. 365 «Pollo in salsa tonnata» 0.4498 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | 89 | 1 | 0.5495 | sì | n. 89 «Gnocchi di patate» 0.5495 |
| Com'è il cacciucco sulle coste dell'Adriatico? | 455 | assente | — | — | n. 708 «Albicocche in composta» 0.3735 |
| Come si prepara il tiramisù? | nessuna | — | 0.5371, 0.5340, 0.5335, 0.5289, 0.5274 | — | n. 713 «Pasticcio a sorpresa» 0.5371 |

Confronto con A (senza filtro; dopo A = partenza):

| domanda | dopo A | dopo B |
|---|---|---|
| gnocchi 400 g (89) | 1° · 0.6659 · sì | 1° · 0.7173 · sì |
| cappelletti (7) | 1° · 0.6097 · sì | 1° · 0.5569 · sì |
| pollo alla cacciatora (208) | assente | **1° · 0.6136 · sì** |
| gnocchi che si sciolgono (89) | 1° · 0.6285 · sì | 1° · 0.6162 · sì |
| cacciucco (455) | 2° · 0.5648 · no | 2° · 0.5344 · **sì** |
| tiramisù (nessuna) | 0.58-0.60 | 0.53-0.54 |

- Con il titolo nel testo indicizzato tutte e cinque le fonti sono tra i primi due risultati e in tutte il chunk
  contiene l'informazione (prima: 3 su 5). Il caso più netto è il pollo alla cacciatora: il testo della ricetta
  non nomina il piatto, il titolo sì.
- Il tiramisù, che non è nel libro, scende a 0.53-0.54, sotto tutte le risposte giuste tranne il cacciucco:
  lo score separa meglio, ma non abbastanza per una soglia sicura.
- Con `--solo-dosi` restano escluse le fonti senza elenco (208, 455); per i cappelletti il chunk con l'elenco è
  ora al 1° posto, ma l'indizio è nella prosa di un altro chunk.

### Query commentata 2: effetto del titolo

`cerca.py "Che vino si usa nel pollo alla cacciatora?"` prima di B:

```
#1 · score 0.5125 · n. 268 «Pollo alla Marengo» · UMIDI · chunk 2 di 2
#2 · score 0.4767 · n. 541 «Pollo al diavolo» · ARROSTI · chunk 1 di 1
#3 · score 0.4645 · n. 338 «Braciuole di castrato e filetto di vitella alla finanziera» · UMIDI · chunk 1 di 2
#4 · score 0.4634 · n. 160 «Ripieno pei polli» · RIPIENI · chunk 2 di 3
#5 · score 0.4619 · n. 316 «Polpettone di carne cruda alla fiorentina» · UMIDI · chunk 1 di 2
```

dopo B:

```
#1 · score 0.6136 · n. 208 «Pollo alla cacciatora» · FRITTI · chunk 1 di 1
#2 · score 0.5257 · n. 43 «Riso alla cacciatora» · MINESTRE IN BRODO · chunk 2 di 2
#3 · score 0.5247 · n. 211 «Fegato alla cacciatora» · FRITTI · chunk 1 di 1
#4 · score 0.5135 · n. 541 «Pollo al diavolo» · ARROSTI · chunk 1 di 1
#5 · score 0.5121 · n. 43 «Riso alla cacciatora» · MINESTRE IN BRODO · chunk 1 di 2
```

Prima di B la ricetta 208 non compariva nemmeno tra i primi 20: il suo testo parla di pollo, olio, vino e
pomodoro, ma non dice «cacciatora», e il primo risultato era un altro pollo. Dopo B è al primo posto con il
chunk che contiene «vino rosso», seguita da altre ricette «alla cacciatora»: il titolo indicizzato porta nel
vettore il nome del piatto, che è proprio ciò che la domanda nomina.
