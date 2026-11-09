# Lezione 6 · Chat con agente LangGraph

Applicazione di chat con agente basata su LangGraph, costruita per step. Stato attuale: **step 3**
(riassunto, router e revisore). L'agente risponde da terminale; un nodo router decide prima se la domanda
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
- `router`: stesso modello, nessuno strumento, output strutturato `motivo` + `categoria`
  (`conversazione` o `fuori_ambito`). Non sceglie gli strumenti: lo fa l'agente.
- `rifiuto`: frase fissa letta da `config/ambito.toml`, nessuna chiamata al modello.
- `modello` / `strumenti` / `limite`: l'agente come nella lezione 5, con lo strumento `tooltime`.
- Se il router restituisce un output non valido, la domanda passa all'agente (avviso nei log).
- `revisore`: stesso modello, nessuno strumento, output `motivo` + `coerente`; vede solo domanda e
  risposta. Se la risposta non copre tutte le parti, torna all'agente con un messaggio `[Revisore]`
  (al massimo `MAX_REVISIONI` volte, poi si consegna l'ultima risposta con un avviso). Output non
  valido del revisore: la risposta si approva.
- `pulizia`: a fine turno toglie dalla cronologia i messaggi `[Revisore]` e le bozze rifiutate; il
  motivo resta solo nei log, l'utente vede solo la risposta finale.
  Se dopo una revisione l'agente finisce i token o i passaggi con gli strumenti, l'utente riceve
  l'ultima bozza (che risponde almeno in parte) invece del messaggio fisso, con un avviso nei log.

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
| `FUSO_PREDEFINITO` | no | `Europe/Rome` |
| `AMBITO_FILE` | no | `config/ambito.toml` (relativo a `assistente-laboratorio/`) |
| `MAX_REVISIONI` | no | `2` (0 = il revisore valuta ma non rimanda) |
| `SOGLIA_RIASSUNTO` | no | `16` messaggi |
| `MESSAGGI_RECENTI` | no | `6` (≥ 1 e minore della soglia) |

L'ambito dell'agente sta in `assistente-laboratorio/config/ambito.toml`: `descrizione`,
`esempi_in_ambito`, `esempi_fuori_ambito` (facoltativi) e `rifiuto`. Si modifica senza toccare il
codice; un file mancante o non valido ferma l'avvio con un messaggio chiaro.

## Avvio (da `L6\assistente-laboratorio`)

```powershell
$env:LM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:LM_MODEL = "google/gemma-4-e2b"
& ..\venv\Scripts\python.exe -m app.cli
```

`esci` (o `exit`) chiude la chat. La cronologia resta solo in memoria per la sessione.

Log attesi:

```
[riassunto] 3 messaggi, soglia 16: nessun riassunto
[riassunto] messaggi prima 17, dopo 7 (riassunti 10)
[riassunto] nuovo riassunto: "L'utente si chiama Luigi. ..."
[router] categoria=conversazione motivo="..." → agente
[agente] nodo modello
[agente] chiamata strumento tooltime con argomenti {'fuso': 'Asia/Tokyo', 'parte': 'ora'}
[router] categoria=fuori_ambito motivo="..." → rifiuto
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

I test usano modelli simulati e non richiedono LM Studio (5 prove reali saltate: router in e fuori
ambito, revisore su risposta parziale e completa, riassunto che conserva il nome). Prova reale con
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
- Per vedere il riassunto in pochi turni: `$env:SOGLIA_RIASSUNTO = "6"`, `$env:MESSAGGI_RECENTI = "2"`.
- Con gemma e2b il router può sbagliare su domande al confine dell'ambito (per esempio «Che
  differenza di orario c'è tra Roma e Londra?» viene rifiutata).
