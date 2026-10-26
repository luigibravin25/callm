# Assistente di laboratorio - specifica

Data: 2026-10-26. Stato: approvata a voce dall'utente; i punti marcati "scelta mia" non sono ancora confermati.

## Intento
Applicazione Python da terminale che conversa con un modello locale servito da LM Studio. Il flusso e' un grafo LangGraph esplicito. Il modello puo' chiedere uno strumento orologio, che il programma esegue davvero. Il progetto e' la base delle lezioni successive: deve restare semplice e senza funzionalita' anticipate.

## Obiettivi
- Ricevere domande dall'utente nel terminale e rispondere tramite il modello.
- Conservare la conversazione finche' il programma e' aperto; alla chiusura la cronologia si perde (nessuna scrittura su disco).
- Grafo con stato, nodi e instradamento riconoscibili: nodo `modello`, nodo `strumenti`, funzione di instradamento.
- Strumento orologio con fuso orario esplicito, eseguito dal grafo e restituito al modello per la risposta finale.
- Ogni chiamata allo strumento visibile nei log (nome, argomenti, risultato).
- Limite sul numero di passaggi per domanda.
- Funzionamento in Docker, configurato con Docker Compose; LM Studio resta sull'host.
- Test automatici indipendenti dal modello e istruzioni per la verifica reale dell'intera soluzione.

## Non obiettivi
MCP, RAG, interfacce grafiche o web, altri strumenti, persistenza della cronologia, servizi cloud, framework non concordati.

## Anti-obiettivi
- Un test con modello finto non va presentato come prova che `google/gemma-4-e2b` sappia usare lo strumento.
- Nessun segreto, `.env`, ambiente virtuale o cache in Git.

## Vincoli
- Python 3.14.5 sia in locale (venv in `L4/venv`) sia nell'immagine Docker (`python:3.14-slim`).
- Codice sincrono, moduli piccoli: grafo, collegamento al modello, strumenti, interfaccia da terminale.
- Dipendenze con versione fissata in `requirements.txt`: `langgraph==1.2.17`, `langchain-openai==1.7.2`, `tzdata==2026.5`, `pytest==9.1.1`. `tzdata` serve a `zoneinfo` su Windows e nell'immagine slim.
- Modello: `google/gemma-4-e2b`, identificativo restituito da `GET /v1/models` di LM Studio.
- Configurazione solo da variabili d'ambiente: `LM_BASE_URL`, `LM_MODEL`, `MAX_STEPS`. Nel container `LM_BASE_URL` usa `host.docker.internal`.
- File di esempio `.env.example` senza credenziali; `.env` reale fuori da Git.
- Comandi documentati anche per PowerShell.
- Conventional Commits in italiano; push solo su richiesta dell'utente.
- Lavorare solo in `L4/assistente-laboratorio/`.

## Decisioni dell'utente
- Cartella del progetto `L4/assistente-laboratorio/`.
- Modello `google/gemma-4-e2b`, nessuna alternativa.
- `langgraph` con `langchain-openai` (`bind_tools`, `ToolNode`).
- Python 3.14.5 e nient'altro.

## Scelte mie (da confermare)
- `MAX_STEPS` predefinito 5: giri modello->strumento per ogni domanda; oltre il limite il grafo si ferma e mostra un messaggio chiaro.
- Comando di uscita `exit`; escono in modo pulito anche `Ctrl+C` e fine input.
- Immagine Docker con utente non root; Compose con `extra_hosts: host.docker.internal:host-gateway`, `stdin_open` e `tty`.

## Lasciato a chi costruisce
Nomi interni dei moduli e delle funzioni oltre quelli indicati nel piano, formato dei log, testo dei messaggi di errore.

## Verifica
- Test senza modello (modello finto, istante controllato): grafo, cronologia, instradamento, strumento, limite, log, configurazione.
- Prove reali separate e attivate esplicitamente: LM Studio con `RUN_LM_STUDIO=1`; Docker con `docker compose run --rm app`.
- Il resoconto finale dichiara cosa e' stato eseguito, con che esito, e cosa resta da provare.
