// lettura dello stream SSE del back-end (step 10): POST /chat/{chat_id}/messaggi/stream.
// openapi-fetch non legge gli stream: qui si usa fetch, con percorso e tipi presi dall'OpenAPI.
import { MSG_FLUSSO_INTERROTTO, MSG_RETE } from "../formato";
import { traduciErrore, type Esito, type Turno } from "./client";
import type { components, paths } from "./schema";

type Schemi = components["schemas"];

// un evento dello stream, con i dati tipizzati dagli schemi del back-end
export type EventoFlusso =
  | { tipo: "fase"; dati: Schemi["EventoFase"] }
  | { tipo: "bozza"; dati: Record<string, never> }
  | { tipo: "testo"; dati: Schemi["EventoTesto"] }
  | { tipo: "strumento"; dati: Schemi["EventoStrumento"] }
  | { tipo: "revisione"; dati: Schemi["EventoRevisione"] }
  | { tipo: "fine"; dati: Turno }
  | { tipo: "errore"; dati: Schemi["Errore"] };

// percorso dell'OpenAPI (un nome sbagliato è un errore di compilazione)
const PERCORSO: keyof paths = "/chat/{chat_id}/messaggi/stream";

// un blocco SSE ("event: ...", "data: ...") → evento; commenti (": ping") e blocchi vuoti → null
function evento(blocco: string): EventoFlusso | null {
  let tipo = "";
  const dati: string[] = [];
  for (const riga of blocco.split("\n")) {
    const r = riga.replace(/\r$/, "");
    if (r.startsWith(":")) continue;
    if (r.startsWith("event:")) tipo = r.slice(6).trim();
    else if (r.startsWith("data:")) dati.push(r.slice(5).trimStart());
  }
  if (!tipo) return null;
  return { tipo, dati: JSON.parse(dati.join("\n") || "{}") } as EventoFlusso;
}

// eventi da blocchi di byte: il decoder in modalità stream ricompone i caratteri spezzati, il
// buffer gli eventi spezzati tra due letture (separatore: riga vuota)
export async function* leggiEventi(blocchi: AsyncIterable<Uint8Array>): AsyncIterable<EventoFlusso> {
  const decoder = new TextDecoder();
  let buffer = "";
  for await (const b of blocchi) {
    buffer += decoder.decode(b, { stream: true }).replace(/\r\n/g, "\n");
    let fine = buffer.indexOf("\n\n");
    while (fine >= 0) {
      const e = evento(buffer.slice(0, fine));
      if (e) yield e;
      buffer = buffer.slice(fine + 2);
      fine = buffer.indexOf("\n\n");
    }
  }
  buffer += decoder.decode();
  const ultimo = evento(buffer);
  if (ultimo) yield ultimo;
}

// corpo della risposta come sequenza di blocchi di byte
async function* blocchiDi(corpo: ReadableStream<Uint8Array>): AsyncIterable<Uint8Array> {
  const lettore = corpo.getReader();
  try {
    for (;;) {
      const { done, value } = await lettore.read();
      if (done) return;
      if (value) yield value;
    }
  } finally {
    lettore.releaseLock();
  }
}

// invia una domanda e legge lo stream: suEvento riceve ogni evento appena arriva; l'esito è il
// Turno salvato (evento fine) oppure l'errore (HTTP, evento errore, stream interrotto, rete)
export async function inviaInFlusso(
  id: number,
  testo: string,
  suEvento: (e: EventoFlusso) => void,
  opzioni: { fetch?: typeof fetch; baseUrl?: string; segnale?: AbortSignal } = {},
): Promise<Esito<Turno>> {
  const url = (opzioni.baseUrl ?? "/api") + PERCORSO.replace("{chat_id}", String(id));
  const f = opzioni.fetch ?? fetch;
  let risposta: Response;
  try {
    risposta = await f(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ testo }),
      signal: opzioni.segnale,
    });
  } catch {
    return { ok: false, errore: { codice: "rete", messaggio: MSG_RETE } };
  }
  if (!risposta.ok || !risposta.body) {
    let corpo: unknown = null;
    try {
      corpo = await risposta.json();
    } catch {
      // corpo non JSON (proxy con back-end spento): messaggio fisso
    }
    return { ok: false, errore: traduciErrore(risposta.status, corpo) };
  }
  try {
    for await (const e of leggiEventi(blocchiDi(risposta.body))) {
      suEvento(e);
      if (e.tipo === "fine") return { ok: true, dati: e.dati };
      if (e.tipo === "errore") return { ok: false, errore: { codice: e.dati.errore, messaggio: e.dati.messaggio } };
    }
  } catch {
    // connessione caduta a metà: come uno stream finito senza fine
  }
  return { ok: false, errore: { codice: "flusso_interrotto", messaggio: MSG_FLUSSO_INTERROTTO } };
}
