# RAG come strumento dell'agente · risultati della lezione 8

Risultati, tracce e confronti degli esercizi della lezione 8, aggiunti a ogni esercizio concluso.
Servizi delle prove reali: Qdrant `l8-qdrant-1` (collezione `ricettario`, 1326 punti, bge-m3 1024 coseno) e
LM Studio sull'host (embedding `text-embedding-bge-m3`).

## Esercizio 1 · server MCP di ricerca

Il server FastMCP `ricerca` (`ricerca/mcp_ricerca/server.py`) espone la ricerca semantica della lezione 7 come
tool MCP. Si avvia in stdio (`python -m mcp_ricerca.server` da `L8\ricerca`); legge la configurazione della ricerca
(`EMBEDDING_MODEL`, `LM_BASE_URL`, `QDRANT_URL`, `QDRANT_COLLEZIONE`) a ogni chiamata.

### Contratto

- **Tool** `search_documents(query: str, top_k: int = 5, capitolo: str = "")`: `top_k` oltre 10 è ridotto a 10
  con una nota nel risultato; `capitolo` vuoto = nessun filtro, altrimenti uno dei nomi della resource (senza
  distinzione di maiuscole).
- **Resource** `ricettario://capitoli` (`application/json`): i 23 capitoli del libro, i valori ammessi dal filtro.
- **Risultato**: `modalita` (`base`), `query`, `top_k` usato, `capitolo`, `nota`, `passaggi`. Ogni passaggio ha
  `id` citabile `R<ricetta>-<chunk da 1>` (es. `R89-1`, da citare come `[R89-1]`), `ricetta`, `titolo`, `capitolo`,
  `posizione` (`chunk 1 di 2`), `score` (4 decimali), `testo` (al massimo 800 caratteri, tagliato a fine parola) e
  `troncato`.
- **Errori**: ogni errore previsto (domanda vuota, `top_k` < 1, capitolo sconosciuto, collezione assente, modello
  diverso da quello della collezione, LM Studio, Qdrant non raggiungibile, configurazione non valida) torna al
  modello come errore del tool con un messaggio comprensibile. Un errore non previsto arriva solo come
  «Error calling tool 'search_documents'», senza dettagli interni.
- **Log**: una riga per chiamata su stderr (logger `mcp_ricerca`), senza traceback; stdout resta il canale MCP.

### Discovery reale

`prova_mcp.py --discovery` avvia il server in stdio con un client FastMCP. Schema di ingresso del tool:

```json
{
  "additionalProperties": false,
  "properties": {
    "query": {"type": "string"},
    "top_k": {"default": 5, "type": "integer"},
    "capitolo": {"default": "", "type": "string"}
  },
  "required": ["query"],
  "type": "object"
}
```

Lo schema non usa `anyOf` (il template di gemma in LM Studio non lo accetta). La resource
`ricettario://capitoli (application/json)` restituisce i 23 nomi, da `BRODI, GELATINA E SUGHI` a `COSE DIVERSE`.

### Chiamate reali (2026-11-18)

| Domanda | Fonte attesa | Passaggi restituiti (id e score) |
|---|---|---|
| Che vino si usa nel pollo alla cacciatora? | `R208-1` | **R208-1 0.6136**, R43-2 0.5257, R211-1 0.5247, R541-1 0.5135, R43-1 0.5121 |
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | un passaggio della ricetta 89 | **R89-1 0.7173**, **R89-2 0.6692**, R231-1 0.6101, R90-1 0.6042, R705-1 0.5985 |

In entrambe le domande la fonte attesa è al primo posto. Righe di log del server (stderr):

```
[mcp_ricerca] query="Che vino si usa nel pollo alla cacciatora?" top_k=5 capitolo=- → 5 passaggi (R208-1 0.6136, R43-2 0.5257, R211-1 0.5247, R541-1 0.5135, R43-1 0.5121) in 0.60s
[mcp_ricerca] query="Quanta farina serve per fare gli gnocchi con 400 g di patate?" top_k=5 capitolo=- → 5 passaggi (R89-1 0.7173, R89-2 0.6692, R231-1 0.6101, R90-1 0.6042, R705-1 0.5985) in 0.63s
```

Primo passaggio della seconda chiamata (testo abbreviato qui):

```json
{"id": "R89-1", "ricetta": 89, "titolo": "Gnocchi di patate", "capitolo": "MINESTRE ASCIUTTE E DI MAGRO",
 "posizione": "chunk 1 di 2", "score": 0.7173, "testo": "La famiglia de' gnocchi è numerosa. …", "troncato": true}
```

### Errore reale

`prova_mcp.py "brodo" --capitolo "DOLCI"`: il client riceve un errore del tool, il log ha una sola riga e nessuna
traceback.

```
errore del tool: capitolo 'DOLCI' sconosciuto; capitoli validi: BRODI, GELATINA E SUGHI, …, COSE DIVERSE
[mcp_ricerca] query="brodo" top_k=5 capitolo=DOLCI → errore: capitolo 'DOLCI' sconosciuto; capitoli validi: …
```

### Come ripetere le prove

Da `L8\ricerca`, con Qdrant e LM Studio accesi:

```powershell
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
& ..\venv\Scripts\python.exe prova_mcp.py --discovery
& ..\venv\Scripts\python.exe prova_mcp.py "Che vino si usa nel pollo alla cacciatora?"
& ..\venv\Scripts\python.exe prova_mcp.py "Quanta farina serve per fare gli gnocchi con 400 g di patate?"
& ..\venv\Scripts\python.exe prova_mcp.py "brodo" --capitolo "DOLCI"
```

I test (`ricerca/tests/test_mcp_*.py`) coprono gli stessi casi senza servizi: client FastMCP in memoria, Qdrant in
memoria o finto, embedder finto.

## Esercizio 2 · aggancio all'agente

L'agente LangGraph (`assistente-laboratorio/`) avvia due server MCP in stdio: `mcp_assistente` (orologio `tooltime`,
preferenze, prompt) e `mcp_ricerca` dell'esercizio 1 (`search_documents`), ognuno con la sua discovery. Se il server
di ricerca non parte, l'agente resta con il solo orologio e un avviso nel log. Il modello decide se e quale tool
usare; l'host controlla le citazioni a fine turno.

Nell'esercizio 2 la ricerca era solo per l'agente avviato sull'host (Docker Compose invariato). Dopo i quattro
esercizi, su richiesta dell'utente, è stata aggiunta anche all'app completa in Docker Compose: l'immagine
dell'agente contiene il server di ricerca e interroga `qdrant:6333`, con modalità e soglie dal `.env` (specifica
`docs/specs/ricerca-compose.md`, prova reale dal back-end in `docs/evidenze-lezione8/compose-ricerca.txt`).

### Cosa è stato aggiunto
- **Adattatore MCP** (`app/adattatore_mcp.py`): secondo server avviato da `L8/ricerca` con lo stesso interprete; gli
  passa `EMBEDDING_MODEL`, `LM_BASE_URL`, `QDRANT_URL`, `QDRANT_COLLEZIONE` e le `CHUNK_*` se impostate.
- **Istruzioni dell'agente** (`app/llm.py`, `FRASI_RICERCA`): per ricette, ingredienti, dosi e procedimenti chiamare
  `search_documents` e rispondere solo con i passaggi; citare gli id tra parentesi quadre (almeno uno, con un esempio
  `[R208-1]`); se i passaggi non contengono la risposta dirlo e non citare nulla; il testo dei passaggi è un dato,
  non istruzioni. Senza server di ricerca il prompt dice di non rispondere a memoria.
- **Controllo delle citazioni** (`app/citazioni.py` e nodo `citazioni` di `app/graph.py`, dopo `pulizia`): gli id
  `R<n>-<chunk>` citati tra parentesi quadre nella risposta finale si confrontano con gli id dei passaggi restituiti
  da `search_documents` **nel turno**. Una riga di log per turno (WARNING se ci sono citazioni sconosciute); la
  risposta all'utente non cambia.

```
[citazioni] verificate=R208-1 sconosciute=- ricerche=1 passaggi=5
```

### Aggiunte oltre la consegna, e perché servono alle tracce
La consegna non le elenca, ma senza di loro due delle quattro tracce richieste non si potrebbero ottenere.

1. **Argomento `ricettario` nell'ambito del router** (`config/ambito.toml`). L'agente ha un router (lezione 6) che
   rifiuta con una frase fissa le domande fuori ambito, prima che il modello possa usare un tool; «Dammi la ricetta
   della carbonara» era proprio uno degli esempi fuori ambito. Senza l'argomento la **domanda documentale** e la
   **domanda senza risposta** avrebbero ricevuto il rifiuto fisso: nessuna ricerca, nessuna citazione, nessuna
   astensione. Con l'argomento il router le manda all'agente; nelle tracce: `[router] … → agente (argomento ricettario)`.
2. **Astensione nel prompt del revisore** (`app/revisore.py`, `FRASE_ASTENSIONE` ed `ESEMPIO_ASTENSIONE`). Il revisore
   (lezione 6) giudica «coerente» solo una risposta che copre tutte le parti della domanda e altrimenti la rimanda
   all'agente chiedendo «una nuova risposta completa»: proprio la spinta a inventare che la **domanda senza
   risposta** deve evitare. Nella prima prova, con la sola frase, il revisore ha bocciato l'astensione due volte
   (`motivo="Come si prepara la carbonara: mancante"`) e l'astensione è arrivata all'utente solo per il limite di
   revisioni; con l'esempio dell'output (stesso rimedio già usato per il revisore nella lezione 6) la giudica subito
   coerente: `[revisore] coerente motivo="come si prepara la carbonara: astensione dichiarata, coperta" → fine`.

Il terzo ritocco dopo la prima prova riguarda le istruzioni, quindi la consegna stessa: la **domanda documentale**
aveva la risposta giusta ma senza citazioni (`verificate=-`); con la frase «Ogni risposta presa dai passaggi deve
contenere almeno un id, per esempio: «Si usa vino rosso [R208-1].»» la risposta cita `[R208-1]`.

### Le quattro tracce (2026-11-18, `google/gemma-4-e2b`, Qdrant `l8-qdrant-1`)

| Caso | Domanda | Tool | Riga `[citazioni]` | Durata |
|---|---|---|---|---|
| documentale | Che vino si usa nel pollo alla cacciatora? | `search_documents` (`query="vino pollo alla cacciatora"`) | `verificate=R208-1 sconosciute=- ricerche=1 passaggi=5` | 104 s |
| ora | Che ore sono? | `tooltime` (fuso delle preferenze) | `verificate=- sconosciute=- ricerche=0 passaggi=0` | 37 s |
| generica | Cos'è il Model Context Protocol? | nessuno | `verificate=- sconosciute=- ricerche=0 passaggi=0` | 43 s |
| senza risposta | Come si prepara la carbonara? | `search_documents` (`query="carbonara"`) | `verificate=- sconosciute=- ricerche=1 passaggi=5` | 93 s |

**Documentale.** Risposta: «Si usa mezzo bicchiere di San Giovese o altro vino rosso del migliore per condire il
pollo alla cacciatora insieme al sugo di pomodoro [R208-1].» Il passaggio `R208-1` («Pollo alla cacciatora») è il
primo restituito (score 0.6549) e contiene proprio il San Giovese: la citazione è verificata dall'host.

```
[router] categoria=conversazione motivo="La domanda riguarda una ricetta specifica dal ricettario di Pellegrino Artusi." → agente (argomento ricettario)
[mcp] tools/call search_documents {'query': 'vino pollo alla cacciatora'}
[mcp_ricerca] query="vino pollo alla cacciatora" top_k=5 capitolo=- → 5 passaggi (R208-1 0.6549, R43-2 0.5574, R43-1 0.5529, R211-1 0.5435, R541-1 0.5390) in 2.74s
[revisore] coerente motivo="vino usato per il pollo alla cacciatora: coperta" → fine
[citazioni] verificate=R208-1 sconosciute=- ricerche=1 passaggi=5
```

**Ora.** `tooltime` con il fuso delle preferenze (`Europe/Rome`), nessuna ricerca: «Sono le ore 17 e 27 minuti a Roma.»

**Generica.** Nessun tool: il modello risponde da sé. La risposta è vaga e in parte imprecisa sul protocollo (è un
limite del modello piccolo sulle sue conoscenze, non della ricerca): la consegna chiede qui solo che non venga
chiamato nessun tool.

**Senza risposta.** Artusi non ha la carbonara: i cinque passaggi hanno score bassi (0.43-0.44, «Crescente» e
altri) e il modello si astiene senza citare: «Nel ricettario di Pellegrino Artusi non ho trovato informazioni su come
preparare la carbonara.»

```
[mcp_ricerca] query="carbonara" top_k=5 capitolo=- → 5 passaggi (R194-2 0.4368, …)
[revisore] coerente motivo="come si prepara la carbonara: astensione dichiarata, coperta" → fine
[citazioni] verificate=- sconosciute=- ricerche=1 passaggi=5
```

Le durate (37-104 s) vengono soprattutto dalle chiamate a gemma (router, agente due volte, revisore); la ricerca
pesa circa 3 s, compreso l'avvio del processo del server a ogni chiamata.

### Come ripetere le tracce
Da `L8\assistente-laboratorio`, con Qdrant e LM Studio accesi:

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
& ..\venv\Scripts\python.exe -m app.api        # log con tools/list, [mcp_ricerca] e [citazioni]
# in un'altra finestra, stesse variabili:
& ..\venv\Scripts\python.exe -m app.cli        # poi le quattro domande
```

I test senza servizi (`tests/test_citazioni.py`, `tests/test_grafo.py`, `tests/test_flusso.py`,
`tests/test_adattatore_mcp.py`) coprono la chiamata al tool, la citazione valida, quella sconosciuta, l'assenza di
citazioni, gli id di un turno precedente, le chiamate non eseguite e lo streaming.

## Esercizio 3 · riscrittura, scomposizione e reranking a confronto

Specifica: `docs/specs/esercizio-3-riscrittura-reranking.md`. Il server di ricerca ha una modalità avanzata scelta
dalla **configurazione del server** (`RICERCA_MODALITA`), non dal modello: lo schema di `search_documents` è
identico in tutte le modalità (discovery reale in `base` ed `entrambe`: uscite identiche), e il risultato dice quale
modalità è stata usata, con quali query e con quali ripieghi.

### Come funziona
Il modulo `ricerca/app/recupero.py` (usato dal server e dallo script di confronto):

| Modalità | Query | Ordine | Chiamate a gemma |
|---|---|---|---|
| `base` (predefinita) | la sola domanda: ricerca vettoriale semplice dell'esercizio 1 (embedding bge-m3, Qdrant restituisce i chunk più simili) | vettoriale (score coseno) | 0 |
| `riscrittura` | la domanda + al massimo 2 query riscritte o scomposte | fusione RRF (1/(60 + rango)) | 1 |
| `reranking` | la domanda | gemma riordina i primi `RERANK_TETTO` candidati e può escluderli | 1 |
| `entrambe` | come `riscrittura` | RRF, poi reranking sulla domanda originale | 2 |

Ogni query chiede a Qdrant gli stessi `RICERCA_CANDIDATI` (10) chunk in tutte le modalità: tra una configurazione e
l'altra cambia un solo fattore. Gemma risponde con lo structured output di LM Studio (schemi `{"query": [...]}` e
`{"id": [...]}`), a temperatura 0. Il testo di ogni candidato mandato al reranking è troncato a 400 caratteri.

Prompt approvati (testo esatto in `app/recupero.py`, `PROMPT_RISCRITTURA` e `PROMPT_RERANKING`):
- riscrittura: trasformare la domanda in query di ricerca, scomporla se chiede più cose, al massimo 2 query, non
  rispondere;
- reranking: restituire gli id utili «anche solo a una sua parte» della domanda, dal più utile, omettere gli altri,
  lista vuota se nessuno è utile, solo id ricevuti.

### Ripieghi (mai un errore verso l'agente)
| Fase | Caso | Effetto | Nel risultato e nel log |
|---|---|---|---|
| riscrittura | LM Studio non risponde, risposta vuota, JSON non valido o di forma sbagliata, lista vuota, nessuna query nuova (solo vuote o copie della domanda) | si cerca con la sola domanda | `riscrittura: <motivo> → sola domanda` |
| reranking | LM Studio non risponde, risposta vuota, JSON non valido o di forma sbagliata | ordine vettoriale (`reranking`) o RRF (`entrambe`) | `reranking: <motivo> → ordine vettoriale` / `ordine RRF` |
| reranking | solo id inventati o doppioni | come sopra | `reranking: id inventati → ordine …` |
| reranking | id validi misti a inventati o doppioni | si tengono i validi | `scartati=n` nella riga di log |
| reranking | id con spazi, parentesi quadre, in minuscolo o senza «R» (` [r89-1] `, `89-1`) | riconosciuti come `R89-1` se è un candidato | — |
| reranking | lista vuota | nessun passaggio (astensione, non ripiego) | `"passaggi": []` |

Gli errori dell'indice (domanda vuota, capitolo sconosciuto, Qdrant o embedding irraggiungibili) e una
configurazione non valida restano errori del tool, come nell'esercizio 1.

### Prova reale (2026-11-20, `RICERCA_MODALITA=entrambe`)
`prova_mcp.py` sulla prima domanda composta (evidenza in `docs/evidenze-lezione8/esercizio3-prova-entrambe.txt`):

```text
"modalita": "entrambe",
"query_usate": ["Quanti tuorli servono per la salsa maionese e quante uova per gli gnocchi alla romana?",
                "tuorli salsa maionese", "uova gnocchi alla romana"],
"ripieghi": [],
[mcp_ricerca] query="Quanti tuorli servono per la salsa maionese e quante uova per gli gnocchi alla r…" top_k=5
capitolo=- modalita=entrambe query=3 llm=2 → 2 passaggi (R126-1 0.6377, R231-2 0.6413) in 26.63s
```

Durate: 60 s alla prima chiamata della giornata (LM Studio caricava gemma), poi 21-27 s. L'agente aspettava ogni
tool al massimo 30 s (`TIMEOUT_S` in `assistente-laboratorio/app/adattatore_mcp.py`): con `entrambe` il margine era
troppo stretto (a cui si somma l'avvio del processo del server), quindi su decisione dell'utente il limite è ora 60 s.

### Confronto delle quattro configurazioni (2026-11-20)
Domande: le 6 della lezione 7 e 4 nuove (2 composte, 2 senza risposta), con fonti decise prima e controllate sul
testo (`ricerca/valutazione/domande.toml`). Comando, da `L8\ricerca` con Qdrant e LM Studio accesi (circa 9 minuti):

```powershell
$env:EMBEDDING_MODEL = "text-embedding-bge-m3"
$env:LM_MODEL = "google/gemma-4-e2b"
$env:PYTHONUTF8 = "1"
& ..\venv\Scripts\python.exe confronta.py > confronto.md
```

- modello di embedding: text-embedding-bge-m3
- modello di chat: google/gemma-4-e2b
- collezione: ricettario (1326 punti)
- k: 5 · candidati per query: 10 · tetto del reranking: 10 · temperatura: 0

| metrica | base | riscrittura | reranking | entrambe |
|---|---|---|---|---|
| fonte nei primi k | 7/7 | 7/7 | 7/7 | 7/7 |
| MRR | 0.929 | 0.929 | 1.000 | 1.000 |
| copertura delle composte | 4/4 | 4/4 | 4/4 | 4/4 |
| astensioni corrette | 0/3 | 0/3 | 0/3 | 0/3 |
| astensioni errate | 0/7 | 0/7 | 0/7 | 0/7 |
| chiamate LLM (media/max) | 0.0/0 | 1.0/1 | 1.0/1 | 2.0/2 |
| latenza s (media/max) | 0.35/2.22 | 8.90/10.19 | 19.35/22.52 | 21.87/24.55 |
| ripieghi | 0 | 0 | 0 | 0 |

| domanda | base | riscrittura | reranking | entrambe |
|---|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | 1 | 1 | 1 | 1 |
| Quanti cappelletti bastano a chi mangia con moderazione? | 1 | 1 | 1 | 1 |
| Che vino si usa nel pollo alla cacciatora? | 1 | 1 | 1 | 1 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | 1 | 1 | 1 | 1 |
| Com'è il cacciucco sulle coste dell'Adriatico? | 2 | 2 | 1 migliorata | 1 migliorata |
| Come si prepara il tiramisù? | 5 passaggi | 5 passaggi | 3 passaggi | 1 passaggi |
| Quanti tuorli servono per la salsa maionese e quante uova per gli gnocchi alla romana? | 2/2 (pos. 1) | 2/2 (pos. 1) | 2/2 (pos. 1) | 2/2 (pos. 1) |
| Quanta salvia va sui saltimbocca alla romana e quante uova servono per il pan di Spagna? | 2/2 (pos. 1) | 2/2 (pos. 1) | 2/2 (pos. 1) | 2/2 (pos. 1) |
| Come si prepara il sushi? | 5 passaggi | 5 passaggi | 4 passaggi | 3 passaggi |
| Quanto cioccolato serve per la torta Sacher? | 5 passaggi | 5 passaggi | 2 passaggi | 2 passaggi |

Celle: posizione della fonte; per le composte fonti trovate / attese e posizione della prima; per le domande senza
risposta i passaggi restituiti oppure «astensione». Il dettaglio (passaggi, query riscritte, ripieghi e id scartati per
domanda) è in `docs/evidenze-lezione8/esercizio3-dettaglio.txt`, un'esecuzione separata con gli stessi esiti
(temperatura 0).

**Come ci si è arrivati.** Il confronto è stato eseguito tre volte, a ogni correzione del codice:
1. prima della revisione finale i candidati arrivavano a gemma su più righe (con gli a capo del testo): il reranking
   migliorava il cacciucco ma perdeva una parte delle composte (copertura 3/4 in `reranking`, 2/4 in `entrambe`);
2. con un candidato per riga, come chiede la specifica, le composte sono tornate 4/4, ma 5 ricerche su 40 ripiegavano
   per «id inventati»: gemma scriveva gli id senza la «R» (`["455-1", "455-3", "456-1", "495-1"]`);
3. con gli id senza «R» riconosciuti (solo se corrispondono a un candidato ricevuto) i ripieghi sono 0 e il reranking
   porta la fonte del cacciucco al primo posto (tabelle qui sopra).

La differenza tra le tre esecuzioni mostra quanto il reranking di un modello piccolo dipenda dalla forma del
messaggio e da come si leggono le sue risposte.

### Casi migliorati e peggiorati
- **Cacciucco, reranking ed entrambe: migliorata (2 → 1).** In `base` e `riscrittura` il primo passaggio è «Acciughe
  alla marinara» (R481-1) o «Cacciucco II» (R456-1); gemma mette primo «Cacciucco I» (R455-1), il chunk che contiene
  «brodetto», e scarta le acciughe. È l'unico cambiamento di posizione: MRR da 0.929 a 1.000.
- **Nessuna domanda peggiorata.** Con k=5 tutte le fonti restano tra i primi 5 in tutte le configurazioni.
- **Composte:** la scomposizione funziona in entrambe (query `tuorli salsa maionese` + `uova gnocchi alla romana`;
  `quantità salvia saltimbocca alla romana` + `quantità uova pan di Spagna`) e alza gli score dei chunk giusti
  («Pane di Spagna» da 0.519 a 0.667, «Gnocchi alla romana» da 0.601 a 0.641). Il reranking tiene entrambe le parti;
  in `entrambe` restano esattamente le due fonti.
- **Domande senza risposta: nessuna astensione.** Il reranking riduce i passaggi (tiramisù da 5 a 3 e a 1, sushi da
  5 a 4 e a 3, Sacher da 5 a 2) ma tiene sempre qualcosa di vicino: «Pasticcio a sorpresa» per il tiramisù, piatti di
  riso o di pesce per il sushi, «Dolce di cioccolata» per la Sacher. L'astensione resta affidata alle istruzioni
  dell'agente (esercizio 2): i passaggi rimasti non contengono la risposta.
- **Domande semplici:** la fonte resta prima; il reranking lascia 1-2 passaggi (per esempio solo R89-2 per gli
  gnocchi): meno contesto da leggere per l'agente, senza perdere la fonte.

### Quale configurazione, su quali domande, a quale costo
- `base` trova la fonte tra i primi 5 per tutte le domande (MRR 0.929) in 0.35 s di media: con bge-m3 e questo
  corpus è già molto buona.
- `riscrittura` non cambia la posizione della fonte (k=5) ma scompone bene le composte e alza gli score dei chunk
  giusti; costa una chiamata a gemma, circa 9 s per domanda.
- `reranking` migliora l'unica fonte non prima (cacciucco, MRR 1.000) e accorcia molto l'elenco dei passaggi, ma non
  porta astensioni; circa 19 s per domanda, massimo 23 s.
- `entrambe` ha la stessa qualità di `reranking` sulle fonti e gli elenchi più puliti sulle composte (solo le due
  fonti), al costo più alto: 2 chiamate, circa 22 s, massimo 25 s (sotto il limite di 60 s dell'agente per una
  chiamata MCP).
- Ripieghi osservati nell'esecuzione finale: 0 su 40 ricerche; il reranking ha scartato 2 id non validi (cacciucco e
  tiramisù in `entrambe`, `scartati=1`) tenendo gli altri.

## Esercizio 4 · soglie di confidenza sullo score

Specifica: `docs/specs/esercizio-4-soglie.md`. Il server di ricerca classifica ogni passaggio con due soglie sullo
score coseno di bge-m3, lette dalla configurazione (`SOGLIA_ALTA`, `SOGLIA_BASSA`, predefiniti 0.60 e 0.51):

| Score | Fascia (`affidabilita` nel passaggio) | Inviato al modello |
|---|---|---|
| ≥ 0.60 | `affidabile` | sì |
| ≥ 0.51 e < 0.60 | `media` | sì |
| < 0.51 | escluso | no |

Il confronto usa lo score a 4 decimali, lo stesso mostrato nel risultato (`ricerca/app/soglie.py`: Qdrant calcola in
float32, quindi 0.51 arriverebbe come 0.50999999); le soglie valgono in ogni modalità. Se non resta
nessun passaggio, la `nota` del risultato lo dichiara: `nessun passaggio rimasto: lista vuota (tutti sotto la soglia
bassa 0.51)` (oppure `(esclusi tutti dal reranking)`). Se almeno un passaggio è di affidabilità media, la `nota` dice
all'agente: `alcuni passaggi hanno affidabilità media: se li usi, termina la risposta con «Da verificare sulla
fonte.»`. La riga di log aggiunge `soglie=0.60/0.51 esclusi=n`.

Istruzioni dell'agente (in coda a `FRASI_RICERCA`): se la risposta usa anche un solo passaggio di affidabilità media,
termina con «Da verificare sulla fonte.» (con l'esempio «Si usa vino rosso [R208-1]. Da verificare sulla fonte.»); con
la lista vuota risponde «Nel ricettario non ho trovato questa informazione» senza citare id.

### Calibrazione (2026-11-20)
Comando, da `L8\ricerca` con Qdrant e LM Studio accesi: `& ..\venv\Scripts\python.exe calibra.py` (modalità `base`,
k = 5, le 10 domande dell'esercizio 3; evidenza in `docs/evidenze-lezione8/esercizio4-calibrazione.txt`).

| domanda | tipo | score delle fonti attese | score dei passaggi |
|---|---|---|---|
| Quanta farina serve per fare gli gnocchi con 400 g di patate? | con risposta | 89: 0.7173 | 0.7173, 0.6692, 0.6101, 0.6042, 0.5985 |
| Quanti cappelletti bastano a chi mangia con moderazione? | con risposta | 7: 0.5569 | 0.5569, 0.5484, 0.5409, 0.5409, 0.4965 |
| Che vino si usa nel pollo alla cacciatora? | con risposta | 208: 0.6136 | 0.6136, 0.5257, 0.5247, 0.5135, 0.5121 |
| Perché gli gnocchi si disfano quando li butto nell'acqua? | con risposta | 89: 0.6162 | 0.6162, 0.5495, 0.5307, 0.5070, 0.5019 |
| Com'è il cacciucco sulle coste dell'Adriatico? | con risposta | 455: 0.5344 | 0.5549, 0.5344, 0.5224, 0.5220, 0.4937 |
| Come si prepara il tiramisù? | senza risposta | — | 0.5447, 0.5371, 0.5365, 0.5340, 0.5337 |
| Quanti tuorli servono per la salsa maionese e quante uova per gli gnocchi alla romana? | composta | 126: 0.6377, 231: 0.6007 | 0.6377, 0.6007, 0.5751, 0.5698, 0.5465 |
| Quanta salvia va sui saltimbocca alla romana e quante uova servono per il pan di Spagna? | composta | 222: 0.5429, 599: 0.5190 | 0.5429, 0.5207, 0.5200, 0.5190, 0.5154 |
| Come si prepara il sushi? | senza risposta | — | 0.5255, 0.5136, 0.5094, 0.5082, 0.5080 |
| Quanto cioccolato serve per la torta Sacher? | senza risposta | — | 0.5907, 0.5838, 0.5619, 0.5606, 0.5602 |

- score minimo di una fonte attesa (`min_fonti`, chunk migliore della fonte): **0.5190** (Pane di Spagna);
- score massimo di un passaggio delle domande senza risposta (`max_senza`): **0.5907** (Sacher, «Dolce tedesco»);
- le due fasce si sovrappongono: 4 fonti vere su 9 (cappelletti 0.5569, saltimbocca 0.5429, cacciucco 0.5344, pan di
  Spagna 0.5190) hanno uno score più basso del primo passaggio della Sacher.

**Perché 0.60 e 0.51.** Gli score non sono probabilità: sono similarità coseno di bge-m3, tutte strette tra 0.49 e
0.72 su questo corpus, e cambierebbero con un altro modello. Poiché le fasce si sovrappongono, nessuna coppia di
soglie separa le domande con risposta da quelle senza: bisognava scegliere quale errore evitare. Il criterio scelto è
**non perdere risposte vere**:
- `SOGLIA_BASSA` = `min_fonti` arrotondato per difetto = **0.51**: nessuna fonte attesa viene esclusa (una soglia
  bassa a 0.60 escluderebbe cappelletti, cacciucco, saltimbocca e pan di Spagna e svuoterebbe tre liste su domande che
  hanno risposta);
- `SOGLIA_ALTA` = `max_senza` arrotondato per eccesso = **0.60**: i passaggi delle domande senza risposta restano al
  massimo di affidabilità media, quindi l'agente li deve dichiarare da verificare (e, non trovandoci la risposta, si
  astiene).

Il margine è stretto: tra la fonte più debole (0.519) e la soglia bassa ci sono 0.009. L'astensione sulle domande
senza risposta del confronto resta compito dell'agente; la soglia bassa svuota la lista solo per ricerche lontane dal
libro (per esempio «ramen», score massimo 0.4487, o «pad thai», 0.4280: evidenza in
`docs/evidenze-lezione8/esercizio4-score-ramen-pad-thai.txt`).

### Confronto con e senza soglie (2026-11-20)
Comando: `& ..\venv\Scripts\python.exe confronta.py --soglie` (base una volta sola, la seconda colonna filtra gli
stessi risultati con le soglie della configurazione; non serve `LM_MODEL`; evidenza in
`docs/evidenze-lezione8/esercizio4-confronto.txt`).

| metrica | base | base + soglie |
|---|---|---|
| fonte nei primi k | 7/7 | 7/7 |
| astensioni corrette | 0/3 | 0/3 |
| astensioni errate | 0/7 | 0/7 |
| MRR | 0.929 | 0.929 |
| copertura delle composte | 4/4 | 4/4 |

Le metriche coincidono, ed è l'effetto atteso del criterio: la soglia bassa è calcolata proprio per non escludere
nessuna fonte di queste domande (quindi né fonti perse né astensioni errate), e i passaggi delle domande senza
risposta stanno tutti sopra 0.51 (quindi nessuna lista svuotata). Le soglie cambiano però ciò che riceve il modello:
- i passaggi sotto 0.51 sono esclusi (il sushi passa da 5 a 2 passaggi, «Perché gli gnocchi si disfano…» da 5 a 3,
  cappelletti e cacciucco perdono il quinto);
- ogni passaggio porta la sua fascia: con queste domande solo gnocchi, vino e maionese hanno passaggi affidabili, e
  tutti i passaggi delle domande senza risposta sono di affidabilità media, da dichiarare da verificare.

### Le tre tracce (2026-11-20, `google/gemma-4-e2b`, modalità `base`, soglie 0.60/0.51)
Evidenze complete in `docs/evidenze-lezione8/esercizio4-traccia-*.txt` (domanda, risposta, log dell'agente).

**Risposta da passaggi affidabili**: «Che vino si usa nel pollo alla cacciatora?»

```text
[mcp_ricerca] query="vino pollo alla cacciatora" top_k=5 capitolo=- modalita=base query=1 llm=0 soglie=0.60/0.51
esclusi=0 → 5 passaggi (R208-1 0.6549, R43-2 0.5574, R43-1 0.5529, R211-1 0.5435, R541-1 0.5390) in 2.25s
risposta: Si può usare mezzo bicchiere di San Giovese o altro vino rosso del migliore per condire il pollo alla
cacciatora, insieme a sugo di pomodoro [R208-1].
[citazioni] verificate=R208-1 sconosciute=- ricerche=1 passaggi=5
```

R208-1 è l'unico passaggio affidabile ed è l'unico usato: correttamente nessuna dichiarazione di verifica.

**Risposta che dichiara la verifica**: «Com'è il cacciucco sulle coste dell'Adriatico?»

```text
[mcp_ricerca] query="cacciucco sulle coste dell'Adriatico" top_k=5 capitolo=- modalita=base query=1 llm=0
soglie=0.60/0.51 esclusi=0 → 5 passaggi (R481-1 0.5459, R455-2 0.5450, R456-1 0.5340, R455-1 0.5297, R455-3 0.5235)
risposta: Il cacciucco sulle coste dell'Adriatico è un piatto tradizionale dove si utilizzano pesci freschi
disponibili nelle acque locali [R455-1]. […] [R455-3]. Da verificare sulla fonte.
[citazioni] verificate=R455-1,R455-2,R456-1,R455-3 sconosciute=- ricerche=1 passaggi=5
```

Tutti i passaggi sono di affidabilità media e la risposta lo dichiara.

**Domanda senza risposta, lista vuota e astensione**: «Il ramen è nel ricettario dell'Artusi?»

```text
[mcp_ricerca] query="ramen" top_k=5 capitolo=- modalita=base query=1 llm=0 soglie=0.60/0.51 esclusi=5 → 0 passaggi
"nota": "nessun passaggio rimasto: lista vuota (tutti sotto la soglia bassa 0.51)"
risposta: Nel ricettario di Pellegrino Artusi non ho trovato informazioni riguardanti il ramen.
[revisore] coerente motivo="Il ramen è nel ricettario dell'Artusi: astensione dichiarata, coperta" → fine
[citazioni] verificate=- sconosciute=- ricerche=1 passaggi=0
```

### Come ci si è arrivati (tentativi in `docs/evidenze-lezione8/esercizio4-tentativo-*.txt`)
- «Quanti cappelletti bastano a chi mangia con moderazione?» è stata rifiutata dal router come fuori ambito: per la
  traccia «da verificare» si è usato il cacciucco, domanda della lezione 7 con tutti i passaggi di affidabilità media.
- «Come si prepara il ramen giapponese?»: gemma ha cercato «come si prepara il ramen», che somiglia al testo delle
  ricette (5 passaggi tra 0.518 e 0.529): lista non vuota, ma astensione. Con «Il ramen è nel ricettario
  dell'Artusi?» gemma cerca «ramen» e la lista si svuota (lo stesso con «Come si fa il pad thai?»; «Che cos'è il
  kimchi?» è stata rifiutata dal router).
- Con la sola frase nelle istruzioni, e poi con un esempio, gemma usava passaggi di affidabilità media senza
  dichiarare la verifica (due tentativi). L'indicazione nella `nota` del risultato, letta subito prima di rispondere,
  ha fatto comparire «Da verificare sulla fonte.»: è sempre l'agente a dichiararla, il codice non modifica la risposta.
