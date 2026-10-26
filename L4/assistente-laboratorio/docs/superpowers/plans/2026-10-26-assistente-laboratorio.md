# Assistente di laboratorio - piano di implementazione

> **Per chi esegue:** usare superpowers:executing-plans (modalita' Native, consigliata) o superpowers:subagent-driven-development. I passi usano checkbox `- [ ]`.

**Obiettivo:** app da terminale con grafo LangGraph che conversa con `google/gemma-4-e2b` in LM Studio, con strumento orologio, in Docker Compose.

**Architettura:** un grafo con stato `{messages, steps}`, nodo `modello` (LLM con strumento associato), nodo `strumenti` (`ToolNode`) e funzione `instrada()`. La cronologia vive nel ciclo del terminale e viene passata al grafo a ogni turno.

**Stack:** Python 3.14.5, `langgraph==1.2.17`, `langchain-openai==1.7.2`, `tzdata==2026.5`, `pytest==9.1.1`, Docker Compose.

**Specifica:** `docs/superpowers/specs/2026-10-26-assistente-laboratorio-design.md`

## Vincoli globali
- Lavorare solo in `L4/assistente-laboratorio/`; eseguire con `L4\venv\Scripts\python.exe` (3.14.5).
- Nessuna dipendenza oltre `requirements.txt` senza accordo.
- Variabili: `LM_BASE_URL`, `LM_MODEL=google/gemma-4-e2b`, `MAX_STEPS=5`.
- Niente MCP, RAG, interfacce web, altri strumenti, persistenza.
- Commit: Conventional Commits in italiano, `git status` e controllo del diff prima, staging selettivo. Niente push senza richiesta.
- Mai versionare `.env`, `venv/`, cache.

## Casi limite da coprire
1. Input vuoto: ignorato (incremento 1).
2. Risposta vuota del modello: messaggio esplicito sui token finiti nel ragionamento (incremento 2).
3. LM Studio spento: messaggio leggibile, senza traceback (incremento 2).
4. Fuso orario non valido: errore leggibile restituito al modello (incremento 3).
5. Strumento sconosciuto richiesto dal modello: errore gestito (incremento 3).
6. `Ctrl+C` e fine input: uscita pulita (incremento 1).

## Struttura dei file
- `app/config.py`: `Settings`, `load_settings()`.
- `app/graph.py`: `State`, `build_graph(llm, max_steps)`, `instrada(state)`.
- `app/llm.py`: `build_llm(settings)`.
- `app/tools.py`: `ora_corrente`.
- `app/cli.py`: `main()`.
- `tests/`, `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example`, `requirements.txt`, `README.md`.

---

### Task 1: grafo con risposta fissa

**File:** crea `app/__init__.py`, `app/graph.py`, `app/cli.py`, `tests/test_graph_fisso.py`; aggiorna `README.md` (creazione, avvio e test).

**Interfacce:**
- Produce: `State(TypedDict)` con `messages: Annotated[list, add_messages]` e `steps: int`; `build_graph(llm=None, max_steps: int = 5)`; `main() -> None` in `app/cli.py`, con uscita su `exit`, `Ctrl+C` e EOF.

- [ ] **Passo 1: scrivere i test che falliscono** in `tests/test_graph_fisso.py`:
  - `test_risposta_fissa`: invocare il grafo con un messaggio utente, l'ultimo messaggio e' la risposta fissa.
  - `test_cronologia_cresce`: dopo 2 turni passando la cronologia, i messaggi sono 4.
  - `test_input_vuoto_ignorato`: il ciclo non invoca il grafo con input vuoto.
  - `test_uscita_pulita`: `exit` ed EOF terminano `main()` senza eccezioni.
- [ ] **Passo 2:** eseguire `python -m pytest tests/test_graph_fisso.py -v`; atteso: FAIL (modulo mancante).
- [ ] **Passo 3:** implementare `State`, `build_graph` con un solo nodo che risponde con testo fisso, e `main()` che accumula i messaggi in una lista.
- [ ] **Passo 4:** rieseguire i test; atteso: PASS. Provare a mano `python -m app.cli`.
- [ ] **Passo 5:** commit `feat(grafo): grafo con risposta fissa e ciclo da terminale`.

### Task 2: LM Studio e cronologia

**File:** crea `app/config.py`, `app/llm.py`, `.env.example`, `tests/test_modello.py`; modifica `app/graph.py`, `app/cli.py`; aggiorna `README.md`.

**Interfacce:**
- Consuma: `build_graph`, `State` dal Task 1.
- Produce: `Settings(base_url: str, model: str, max_steps: int)`; `load_settings() -> Settings` (errore chiaro se manca `LM_BASE_URL` o `LM_MODEL`; `MAX_STEPS` predefinito 5); `build_llm(settings: Settings) -> ChatOpenAI`.

- [ ] **Passo 1: test che falliscono** in `tests/test_modello.py`, con un modello finto:
  - `test_cronologia_passata_al_modello`: la seconda chiamata riceve i messaggi del primo turno.
  - `test_config_mancante`: senza `LM_MODEL` `load_settings()` solleva un errore che nomina la variabile.
  - `test_risposta_vuota`: contenuto vuoto produce il messaggio "i token sono finiti nel ragionamento".
  - `test_server_non_raggiungibile`: un errore di connessione produce un messaggio leggibile.
- [ ] **Passo 2:** eseguire i test; atteso: FAIL.
- [ ] **Passo 3:** sostituire il nodo fisso con il nodo `modello` che chiama `llm.invoke(state["messages"])`; gestire risposta vuota ed errore di connessione nel nodo o nel ciclo.
- [ ] **Passo 4:** test; atteso: PASS.
- [ ] **Passo 5 (prova reale, LM Studio attivo, `RUN_LM_STUDIO=1`):** due domande collegate; la seconda usa il contesto della prima. Annotare l'esito.
- [ ] **Passo 6:** commit `feat(llm): collegamento a LM Studio con cronologia`.

### Task 3: orologio, instradamento, limite e log

**File:** crea `app/tools.py`, `tests/test_strumenti.py`, `tests/test_instradamento.py`; modifica `app/graph.py`, `app/llm.py`; aggiorna `README.md`.

**Interfacce:**
- Consuma: `build_graph`, `build_llm`, `Settings.max_steps`.
- Produce: `ora_corrente(fuso: str) -> str` (strumento `@tool`, orario iniettabile per i test); `instrada(state: State) -> Literal["strumenti", "__end__"]`; contatore `steps` incrementato a ogni passaggio dal nodo `strumenti`.

- [ ] **Passo 1: test che falliscono:**
  - `test_orologio_istante_controllato`: istante fisso e `Europe/Rome` danno l'ora attesa.
  - `test_fuso_non_valido`: stringa di errore leggibile, nessuna eccezione.
  - `test_instrada_a_strumenti`: con `tool_calls` va a `strumenti`, altrimenti termina.
  - `test_risultato_torna_al_modello`: il risultato dello strumento arriva al modello e produce la risposta finale.
  - `test_limite_passaggi`: con il modello che chiede sempre lo strumento, dopo `max_steps` il grafo si ferma con un messaggio.
  - `test_log_chiamata_strumento`: `caplog` contiene nome, argomenti e risultato.
  - `test_strumento_sconosciuto`: errore gestito senza crash.
- [ ] **Passo 2:** eseguire i test; atteso: FAIL.
- [ ] **Passo 3:** implementare lo strumento, associarlo con `bind_tools`, aggiungere `ToolNode`, `instrada` e il limite; registrare ogni chiamata con `logging`.
- [ ] **Passo 4:** test; atteso: PASS.
- [ ] **Passo 5 (prova reale):** chiedere "che ore sono a Tokyo?" con LM Studio attivo; il log deve mostrare la chiamata a `ora_corrente`. Se il modello non la richiede, riportarlo come esito reale.
- [ ] **Passo 6:** commit `feat(strumenti): orologio con instradamento e limite di passaggi`.

### Task 4: Docker Compose e verifica completa

**File:** crea `Dockerfile` (`python:3.14-slim`, utente non root), `compose.yaml`, `.dockerignore`, `tests/test_compose.py`; completa `README.md`.

**Interfacce:**
- Consuma: l'app dei Task 1-3 e `.env`.
- Produce: servizio `app` avviabile con `docker compose run --rm app`.

- [ ] **Passo 1: test che fallisce** `test_compose_valido`: `docker compose config` termina con codice 0.
- [ ] **Passo 2:** eseguire il test; atteso: FAIL.
- [ ] **Passo 3:** scrivere `Dockerfile`, `compose.yaml` (con `env_file`, `extra_hosts: host.docker.internal:host-gateway`, `stdin_open`, `tty`) e `.dockerignore`.
- [ ] **Passo 4:** test; atteso: PASS.
- [ ] **Passo 5 (prova reale, Docker e LM Studio attivi):** `docker compose run --rm app`, una domanda semplice e una sull'ora. Annotare l'esito.
- [ ] **Passo 6:** completare il `README.md` con configurazione, avvio, test, prove reali e diagnosi, solo con comandi verificati e versioni PowerShell.
- [ ] **Passo 7:** commit `build(docker): Compose per l'applicazione` e `docs: README con comandi verificati`.

## Verifica finale
Eseguire `python -m pytest`, poi le prove reali separate. Nel resoconto: cosa e' stato eseguito, con che esito, cosa resta da provare.
