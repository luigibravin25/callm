# Lezione 6 · Chat con agente LangGraph

Applicazione di chat con agente basata su LangGraph, costruita per step. Stato attuale: **step 5**
(prompt MCP con i comandi della CLI, preferenze via resource MCP, riassunto, router e revisore). L'agente risponde da terminale; un nodo router decide prima se la domanda
rientra nell'ambito dichiarato in configurazione; un nodo revisore controlla poi che la risposta
risponda a tutta la domanda.

```
START → riassunto → router ─(conversazione)→ modello ⇄ strumenti
                │                   ├→ revisore ─(coerente)→ pulizia → END
                │                   │      └─(non coerente)→ modello  (al massimo MAX_REVISIONI volte)
                │                   └→ limite / risposta vuota → pulizia → END
                └─(fuori_ambito)→ rifiuto → END
```

- `riassunto`: oltre `SOGLIA_RIASSUNTO` messaggi sostituisce i più vecchi con un riassunto (campo
  dello stato aggiornato, non accumulato) e lascia interi gli ultimi turni (almeno
  `MESSAGGI_RECENTI` messaggi; il taglio cade sempre all'inizio di un turno). Il riassunto va in
  fondo al prompt di sistema dell'agente. Sotto la soglia non chiama il modello; se il riassunto
  fallisce i messaggi restano.
- `router`: stesso modello, nessuno strumento, output strutturato `motivo` + `argomento`, scelto
  dall'elenco `[[argomenti]]` di `config/ambito.toml` oppure `altro`. Il codice ricava la
  categoria: `altro` = `fuori_ambito`, ogni altro argomento = `conversazione` (dallo step 5: con
  l'ambito più largo gemma e2b decideva male con la sola scelta conversazione/fuori ambito). Non
  sceglie gli strumenti: lo fa l'agente.
- `rifiuto`: frase fissa letta da `config/ambito.toml`, nessuna chiamata al modello.
- `modello` / `strumenti` / `limite`: l'agente come nella lezione 5, con lo strumento `tooltime` del
  server MCP `mcp_assistente`. Se il modello chiama `tooltime` senza fuso, il nodo `strumenti` lo
  completa con il fuso delle preferenze prima della chiamata.
- Se il router restituisce un output non valido, la domanda passa all'agente (avviso nei log).
- `revisore`: stesso modello, nessuno strumento, output `motivo` + `coerente`; vede solo domanda e
  risposta. Se la risposta non copre tutte le parti, torna all'agente con un messaggio `[Revisore]`
  (al massimo `MAX_REVISIONI` volte, poi si consegna l'ultima risposta con un avviso). Output non
  valido del revisore: la risposta si approva.
- `pulizia`: a fine turno toglie dalla cronologia i messaggi `[Revisore]` e le bozze rifiutate; il
  motivo resta solo nei log, l'utente vede solo la risposta finale.
  Se dopo una revisione l'agente finisce i token o i passaggi con gli strumenti, l'utente riceve
  l'ultima bozza (che risponde almeno in parte) invece del messaggio fisso, con un avviso nei log.

## Server MCP e preferenze (step 4)

`assistente-laboratorio/mcp_assistente/server.py` (FastMCP, trasporto stdio) parte da solo come
sottoprocesso della CLI e pubblica:

- il tool `tooltime` (lo chiama il modello: `tools/call`);
- la resource `utente://preferenze` (la legge l'host una volta all'avvio: `resources/read`), che
  restituisce il testo del file `PREFERENZE_FILE` (predefinito `config/preferenze.json`):

```json
{"lingua": "italiano", "fuso": "Europe/Rome", "stile": "sintetico"}
```

`lingua` è testo libero, `fuso` un nome IANA, `stile` `sintetico` o `dettagliato`. L'host valida
campo per campo: un campo mancante o non valido prende il predefinito (italiano, `FUSO_PREDEFINITO`
o Europe/Rome, sintetico) con un avviso che lo nomina; file mancante o JSON illeggibile: tutti i
predefiniti. Le preferenze vanno in cima al prompt di sistema dell'agente e valgono per tutta la
sessione: un file modificato vale dal prossimo avvio. Router, revisore e riassunto non le ricevono.
Se il server MCP non parte, la chat funziona lo stesso senza strumenti e con i predefiniti.

Per provare preferenze diverse senza modificare il file versionato:

```powershell
'{"lingua": "inglese", "fuso": "America/New_York", "stile": "dettagliato"}' | Set-Content -Encoding utf8 $env:TEMP\prefs.json
$env:PREFERENZE_FILE = "$env:TEMP\prefs.json"
```

## Prompt e comandi della CLI (step 5)

Lo stesso server pubblica due prompt MCP, modelli di istruzioni che richiama l'utente:

- `spiega(argomento, livello)`: `livello` = `base`, `intermedio` o `avanzato` (predefinito `base`);
- `riassumi_conversazione(stile)`: `stile` = `sintetico` o `dettagliato` (predefinito `sintetico`);
  riassume la sessione corrente (la cronologia la vede già l'agente: il server non la riceve).

Comandi (ogni riga che inizia con `/` è un comando):

```
/prompts
/prompt spiega argomento="Model Context Protocol" livello=base
/prompt riassumi_conversazione stile=dettagliato
```

Gli argomenti si scrivono `chiave=valore`; un valore con spazi va tra virgolette doppie
(`argomento="l'agente e l'LLM"`); l'apostrofo è un carattere normale (`argomento=dell'MCP`).
L'host controlla gli argomenti rispetto a `prompts/list` (obbligatori mancanti, sconosciuti,
virgolette non chiuse) e il server controlla i valori (`livello`, `stile`): in caso di errore la
CLI mostra un messaggio e non chiama il modello. I messaggi ottenuti dal server entrano nella
cronologia e passano dal grafo come una domanda: riassunto, router, agente, strumenti, revisore.
Per questo l'ambito comprende anche i concetti della lezione e la conversazione in corso.

| Primitiva | Chi la attiva | Quando | Log |
|---|---|---|---|
| Tool (`tooltime`) | il modello | durante il ciclo agente ⇄ strumenti | `[mcp] tools/call ...` |
| Resource (`utente://preferenze`) | l'host | una volta all'avvio | `[mcp] resources/read ...` |
| Prompt (`spiega`, `riassumi_conversazione`) | l'utente | quando scrive `/prompt` | `[mcp] prompts/get ...` |

## Requisiti

- Python 3.14 e LM Studio sull'host con `google/gemma-4-e2b` caricato (Context Length almeno 16384).

## Installazione (PowerShell, da `L6\`)

```powershell
C:\Python314\python.exe -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configurazione

L'app legge solo variabili d'ambiente (elenco e valori di esempio in `.env.example`):

| Variabile | Obbligatoria | Predefinito |
|---|---|---|
| `LM_BASE_URL` | sì | — |
| `LM_MODEL` | sì | — |
| `MAX_STEPS` | no | `5` |
| `FUSO_PREDEFINITO` | no | `Europe/Rome` (riserva se le preferenze non hanno un fuso valido) |
| `AMBITO_FILE` | no | `config/ambito.toml` (relativo a `assistente-laboratorio/`) |
| `MAX_REVISIONI` | no | `2` (0 = il revisore valuta ma non rimanda) |
| `SOGLIA_RIASSUNTO` | no | `16` messaggi |
| `MESSAGGI_RECENTI` | no | `6` (≥ 1 e minore della soglia) |
| `PREFERENZE_FILE` | no | `config/preferenze.json` (relativo a `assistente-laboratorio/`) |

L'ambito dell'agente sta in `assistente-laboratorio/config/ambito.toml`: `descrizione`,
`esempi_in_ambito`, `esempi_fuori_ambito` (facoltativi), `rifiuto` e, in fondo al file, uno o più
`[[argomenti]]` con `nome` e `descrizione` (il nome `altro` è riservato al fuori ambito). Si modifica senza toccare il
codice; un file mancante o non valido ferma l'avvio con un messaggio chiaro.

## Avvio (da `L6\assistente-laboratorio`)

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
& ..\venv\Scripts\python.exe -m app.cli
```

`esci` (o `exit`) chiude la chat; `/prompts` elenca i prompt. La cronologia resta solo in memoria
per la sessione.

Log attesi:

```
[mcp] tools/list: tooltime
[mcp] resources/read utente://preferenze
[mcp] prompts/list: spiega, riassumi_conversazione
[mcp] prompts/get spiega {'argomento': 'Model Context Protocol', 'livello': 'base'}
[mcp] prompts/get spiega: 1 messaggio: human: Spiegami Model Context Protocol. Livello base: ...
[preferenze] in uso: lingua=italiano fuso=America/New_York stile=sintetico
[riassunto] 3 messaggi, soglia 16: nessun riassunto
[riassunto] messaggi prima 17, dopo 7 (riassunti 10)
[riassunto] nuovo riassunto: "L'utente si chiama Luigi. ..."
[router] categoria=conversazione motivo="..." → agente (argomento ora_data_fusi)
[agente] nodo modello
[agente] tooltime senza fuso: uso America/New_York (preferenze)
[agente] chiamata strumento tooltime con argomenti {'fuso': 'America/New_York', 'parte': 'ora'}
[mcp] tools/call tooltime {'fuso': 'America/New_York', 'parte': 'ora'}
[router] categoria=fuori_ambito motivo="..." → rifiuto (argomento altro)
[rifiuto] risposta fissa inviata
[revisore] coerente motivo="ore a Tokyo: coperta" → fine
[revisore] non coerente motivo="...: mancante" → agente (revisione 1 di 2)
[revisore] pulizia: tolti 2 messaggi (indicazioni del revisore e bozze rifiutate)
```

Nel percorso fuori ambito non compare `[agente] nodo modello`. I log si accendono e spengono con
`LOG_HTTP` e `LOG_GRAFO` in `app/llm.py`.

## Test (da `L6\assistente-laboratorio`)

```powershell
& ..\venv\Scripts\python.exe -m pytest -q
```

I test usano modelli simulati e non richiedono LM Studio; il server MCP gira in memoria o come
sottoprocesso (10 prove reali saltate: router in e fuori ambito, revisore su risposta parziale e
completa, riassunto che conserva il nome, fuso delle preferenze, risposta in inglese, prompt `spiega`
in ambito e fuori ambito, prompt `riassumi_conversazione`). Prova reale con
LM Studio avviato:

```powershell
$env:RUN_LM_STUDIO = "1"
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
& ..\venv\Scripts\python.exe -m pytest tests\test_prova_reale.py -v
```

## Diagnosi

- «Impossibile raggiungere LM Studio»: server non avviato o `LM_BASE_URL` sbagliato; la chat
  resta aperta e la domanda non entra nella cronologia.
- `[router] output non valido (...)`: il modello non ha prodotto la decisione (per esempio token
  finiti nel ragionamento); la domanda passa comunque all'agente.
- `[mcp] server MCP non disponibile (...): nessuno strumento`: il server non parte (dipendenze
  non installate?); la chat risponde senza orologio.
- `[preferenze] campo 'fuso' non valido (...)`: correggere il file delle preferenze; nel frattempo
  vale il predefinito.
- «Il server non ha restituito il prompt: livello non valido ...»: valore non ammesso; i valori
  ammessi sono nella descrizione del prompt (`/prompts`).
- Con la pipe di PowerShell l'input si legge in UTF-8 e i BOM iniziali vengono tolti: `esci` e
  `/prompts` funzionano anche così, con o senza `PYTHONIOENCODING`.
- Per vedere il riassunto in pochi turni: `$env:SOGLIA_RIASSUNTO = "6"`, `$env:MESSAGGI_RECENTI = "2"`.
- Con gemma e2b il router può sbagliare su domande al confine dell'ambito (per esempio «Che
  differenza di orario c'è tra Roma e Londra?» viene rifiutata).
