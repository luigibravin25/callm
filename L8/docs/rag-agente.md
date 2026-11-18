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
