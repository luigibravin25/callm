# Front-end · interfaccia di chat (step 8)

Interfaccia di chat nel browser per l'assistente di laboratorio. Parla **solo con il back-end**
(step 7), mai con l'agente:

```
browser ──/api/...──> server di Vite (porta 5173) ──proxy, toglie /api──> back-end (BACKEND_URL)
                                                                           └─> agente ─> LM Studio
```

Vite + TypeScript senza framework. Tipi e chiamate sono generati dall'OpenAPI del back-end
(`openapi.json` → `src/api/schema.d.ts`), nessun endpoint scritto a mano. Solo tema scuro.

## Requisiti
- Node 24 (provato con 24.15.0) e npm 11.
- Google Chrome installato (i test nel browser lo usano: niente download di Chromium).
- Per l'uso vero: database `l6-postgres`, agente e back-end avviati (vedi `../backend/README.md`).

## Installazione (da `L6\frontend`)
```powershell
npm ci
```

## Avvio
```powershell
# back-end e agente già avviati; indirizzo del back-end (predefinito http://127.0.0.1:8001)
$env:BACKEND_URL = "http://127.0.0.1:8001"
npm run dev            # http://127.0.0.1:5173
```
Build di produzione e controllo della build (stesso proxy):
```powershell
npm run build
npm run preview        # http://127.0.0.1:5173
```

## Uso
- **+ Nuova chat** crea una chat; l'elenco mostra titolo e data dell'ultimo messaggio, le più recenti
  in cima. All'apertura si apre la chat più recente.
- 🗑 elimina la chat dopo una conferma (non si può annullare).
- **Invio** invia, **Maiusc+Invio** va a capo. Durante la risposta compare «Assistente: …»: solo
  quella chat è bloccata, le altre restano usabili. Sotto la risposta la riga 🔧 mostra gli
  strumenti usati (per esempio `🔧 tooltime (fuso: Asia/Tokyo)`).
- Errori: riquadro nella chat con il messaggio del back-end (per esempio agente non raggiungibile);
  la domanda torna nel campo di testo per reinviarla (il back-end non l'ha salvata). Con il back-end
  spento: «Il back-end non risponde (HTTP …): controlla che sia avviato.» con **Riprova**.
- Nulla viene salvato nel browser: bozze e attese si perdono ricaricando la pagina; le chat sono nel
  database.

## Contratto con il back-end
Dopo una modifica all'API del back-end:
```powershell
npm run genera-api     # scrive openapi.json (senza database) e src/api/schema.d.ts
```
Il test `backend/tests/test_openapi_frontend.py` fallisce se `openapi.json` non è allineato.

## Test
```powershell
npm run controlla      # controllo dei tipi (tsc)
npm test               # Vitest: formato, client, stato, vista (jsdom)
npm run test:browser   # Playwright in Chrome con il back-end simulato (avvia Vite sulla porta 5174)
```
Prova reale (stack completo con LM Studio; database, agente, back-end e `npm run dev` avviati):
```powershell
$env:RUN_E2E = "1"
npm run test:reale     # nuova chat, «Che ore sono a Tokyo?», riga 🔧 tooltime, chat presente dopo il ricaricamento
Remove-Item Env:RUN_E2E
```
Senza `RUN_E2E` la prova reale viene saltata. Screenshot in `test-results/`.

## Nota per lo step 9 (Docker)
nginx servirà `dist/` e farà lo stesso proxy `/api` → `http://backend:8001`. Il proxy deve
attendere più di `AGENTE_TIMEOUT` (300 s), per esempio con `proxy_read_timeout`.
