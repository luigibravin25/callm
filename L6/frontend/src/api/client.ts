// client dell'API del back-end: percorsi e tipi generati dall'OpenAPI (schema.d.ts), errori comprensibili
import createClient from "openapi-fetch";
import { MSG_BACKEND_GIU, MSG_RETE } from "../formato";
import type { components, paths } from "./schema";

// tipi del contratto (mai scritti a mano: vengono dall'OpenAPI del back-end)
export type ChatInElenco = components["schemas"]["ChatInElenco"];
export type ChatCreata = components["schemas"]["ChatCreata"];
export type ChatCompleta = components["schemas"]["ChatCompleta"];
export type Messaggio = components["schemas"]["MessaggioChat"];
export type Turno = components["schemas"]["Turno"];

// errore da mostrare: codice stabile, messaggio in italiano, status HTTP se c'è stata una risposta
export type ErroreUI = { codice: string; messaggio: string; status?: number };
// esito di ogni chiamata: dati oppure errore, mai eccezioni
export type Esito<T> = { ok: true; dati: T } | { ok: false; errore: ErroreUI };

// le 5 operazioni del back-end
export interface Api {
  elenca(): Promise<Esito<ChatInElenco[]>>;
  crea(): Promise<Esito<ChatCreata>>;
  leggi(id: number): Promise<Esito<ChatCompleta>>;
  invia(id: number, testo: string): Promise<Esito<Turno>>;
  elimina(id: number): Promise<Esito<null>>;
}

// risposta d'errore → messaggio: il corpo {errore, messaggio} del back-end (o dell'agente inoltrato)
// si mostra così com'è; qualsiasi altro corpo (proxy con back-end spento) → messaggio fisso
export function traduciErrore(status: number, corpo: unknown): ErroreUI {
  if (typeof corpo === "object" && corpo !== null) {
    const { errore, messaggio } = corpo as { errore?: unknown; messaggio?: unknown };
    if (typeof errore === "string" && typeof messaggio === "string") {
      return { codice: errore, messaggio, status };
    }
  }
  return { codice: "backend_non_raggiungibile", messaggio: MSG_BACKEND_GIU(status), status };
}

// risultato di openapi-fetch (data, error, response) → Esito; fetch che lancia → errore di rete
async function esito<T>(
  chiamata: () => Promise<{ data?: unknown; error?: unknown; response: Response }>,
  vuoto = false,
): Promise<Esito<T>> {
  try {
    const { data, error, response } = await chiamata();
    if (!response.ok) return { ok: false, errore: traduciErrore(response.status, error) };
    // 204 senza corpo (eliminazione): dati null
    return { ok: true, dati: (vuoto ? null : data) as T };
  } catch {
    return { ok: false, errore: { codice: "rete", messaggio: MSG_RETE } };
  }
}

// baseUrl predefinito "/api": il proxy (Vite o nginx) inoltra al back-end; fetch sostituibile nei test
export function creaApi(opzioni: { baseUrl?: string; fetch?: typeof fetch } = {}): Api {
  const client = createClient<paths>({
    baseUrl: opzioni.baseUrl ?? "/api",
    ...(opzioni.fetch ? { fetch: opzioni.fetch } : {}),
  });
  // identificativo della chat nel percorso
  const percorso = (id: number) => ({ params: { path: { chat_id: id } } });
  return {
    elenca: () => esito(() => client.GET("/chat")),
    crea: () => esito(() => client.POST("/chat")),
    leggi: (id) => esito(() => client.GET("/chat/{chat_id}", percorso(id))),
    invia: (id, testo) =>
      esito(() => client.POST("/chat/{chat_id}/messaggi", { ...percorso(id), body: { testo } })),
    elimina: (id) => esito(() => client.DELETE("/chat/{chat_id}", percorso(id)), true),
  };
}
