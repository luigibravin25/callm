# Lezione 6 · Chat con agente LangGraph

Applicazione di chat con agente basata su LangGraph, costruita per step. Stato attuale: **step 1**
(router). L'agente risponde da terminale; un nodo router decide prima se la domanda rientra
nell'ambito dichiarato in configurazione.

```
START → router ─(conversazione)→ modello ⇄ strumenti → END
                └─(fuori_ambito)→ rifiuto → END
```

- `router`: stesso modello, nessuno strumento, output strutturato `motivo` + `categoria`
  (`conversazione` o `fuori_ambito`). Non sceglie gli strumenti: lo fa l'agente.
- `rifiuto`: frase fissa letta da `config/ambito.toml`, nessuna chiamata al modello.
- `modello` / `strumenti` / `limite`: l'agente come nella lezione 5, con lo strumento `tooltime`.
- Se il router restituisce un output non valido, la domanda passa all'agente (avviso nei log).

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
[router] categoria=conversazione motivo="..." → agente
[agente] nodo modello
[agente] chiamata strumento tooltime con argomenti {'fuso': 'Asia/Tokyo', 'parte': 'ora'}
[router] categoria=fuori_ambito motivo="..." → rifiuto
[rifiuto] risposta fissa inviata
```

Nel percorso fuori ambito non compare `[agente] nodo modello`. I log si accendono e spengono con
`LOG_HTTP` e `LOG_GRAFO` in `app/llm.py`.

## Test (da `L6\assistente-laboratorio`)

```powershell
& ..\venv\Scripts\python.exe -m pytest -q
```

I test usano modelli simulati e non richiedono LM Studio (2 prove reali saltate). Prova reale con
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
- Con gemma e2b il router può sbagliare su domande al confine dell'ambito (per esempio «Che
  differenza di orario c'è tra Roma e Londra?» viene rifiutata).
