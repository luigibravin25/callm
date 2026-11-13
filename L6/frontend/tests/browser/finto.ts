// back-end simulato con page.route: chat e messaggi in memoria, invio ritardabile, errori a richiesta
import type { Page, Route } from "@playwright/test";

export interface MessaggioFinto {
  id: number;
  ruolo: "utente" | "assistente";
  testo: string;
  strumenti: { nome: string; argomenti: Record<string, unknown> }[] | null;
  creato_il: string;
}

export interface ChatFinta {
  id: number;
  titolo: string;
  creata_il: string;
  ultimo_messaggio_il: string | null;
  messaggi: MessaggioFinto[];
}

// risposta d'errore: status e corpo (JSON oppure testo; "" = corpo vuoto)
export interface ErroreFinto { status: number; corpo: unknown }

export interface Finto {
  chat: ChatFinta[];
  // testo e strumenti della risposta dell'assistente
  risposta?: { testo: string; strumenti: MessaggioFinto["strumenti"] };
  // se presente, l'invio aspetta questa promessa prima di rispondere
  attesaInvio?: Promise<void>;
  erroreInvio?: ErroreFinto;
  erroreElenco?: ErroreFinto;
}

const ORA = "2026-11-13T08:00:00Z";

export function chatFinta(id: number, titolo: string, messaggi: MessaggioFinto[] = []): ChatFinta {
  return { id, titolo, creata_il: ORA, ultimo_messaggio_il: messaggi.length ? ORA : null, messaggi };
}

export function messaggio(id: number, ruolo: MessaggioFinto["ruolo"], testo: string,
  strumenti: MessaggioFinto["strumenti"] = null): MessaggioFinto {
  return { id, ruolo, testo, strumenti, creato_il: ORA };
}

// promessa risolvibile dal test (risposta dell'agente che arriva più tardi)
export function differita() {
  let risolvi!: () => void;
  const promessa = new Promise<void>((r) => { risolvi = r; });
  return { promessa, risolvi };
}

// invia un errore: corpo JSON, testo o vuoto
async function rispondiErrore(route: Route, e: ErroreFinto): Promise<void> {
  if (typeof e.corpo === "string") await route.fulfill({ status: e.status, body: e.corpo });
  else await route.fulfill({ status: e.status, json: e.corpo });
}

// riga dell'elenco come la restituisce il back-end (le più recenti prima: ordine dell'array)
const inElenco = (c: ChatFinta) => ({ id: c.id, titolo: c.titolo, ultimo_messaggio_il: c.ultimo_messaggio_il });

export async function simulaBackend(page: Page, finto: Finto): Promise<void> {
  let prossimoId = 100;
  // solo i percorsi che iniziano con /api/: un glob **/api/** prenderebbe anche i moduli
  // di Vite in /src/api/ e la pagina non si caricherebbe
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const richiesta = route.request();
    const percorso = new URL(richiesta.url()).pathname.replace(/^\/api/, "");
    const metodo = richiesta.method();
    const trovata = (id: number) => finto.chat.find((c) => c.id === id);
    const nonTrovata = () => route.fulfill({ status: 404,
      json: { errore: "chat_non_trovata", messaggio: "Chat non trovata." } });

    if (percorso === "/chat" && metodo === "GET") {
      if (finto.erroreElenco) return rispondiErrore(route, finto.erroreElenco);
      return route.fulfill({ json: finto.chat.map(inElenco) });
    }
    if (percorso === "/chat" && metodo === "POST") {
      const nuova = chatFinta(prossimoId++, "Nuova chat");
      finto.chat.unshift(nuova);
      return route.fulfill({ status: 201, json: { id: nuova.id, titolo: nuova.titolo, creata_il: ORA } });
    }
    const invio = percorso.match(/^\/chat\/(\d+)\/messaggi$/);
    if (invio && metodo === "POST") {
      const c = trovata(Number(invio[1]));
      if (!c) return nonTrovata();
      if (finto.attesaInvio) await finto.attesaInvio;
      if (finto.erroreInvio) return rispondiErrore(route, finto.erroreInvio);
      const { testo } = richiesta.postDataJSON() as { testo: string };
      const r = finto.risposta ?? { testo: "Risposta.", strumenti: null };
      const domanda = messaggio(prossimoId++, "utente", testo);
      const risposta = messaggio(prossimoId++, "assistente", r.testo, r.strumenti);
      c.messaggi.push(domanda, risposta);
      c.ultimo_messaggio_il = ORA;
      if (c.titolo === "Nuova chat") c.titolo = testo.slice(0, 50);
      return route.fulfill({ json: { domanda, risposta } });
    }
    const una = percorso.match(/^\/chat\/(\d+)$/);
    if (una) {
      const c = trovata(Number(una[1]));
      if (!c) return nonTrovata();
      if (metodo === "GET") return route.fulfill({ json: c });
      if (metodo === "DELETE") {
        finto.chat = finto.chat.filter((x) => x !== c);
        return route.fulfill({ status: 204, body: "" });
      }
    }
    return route.fulfill({ status: 404,
      json: { errore: "percorso_non_trovato", messaggio: "Percorso non trovato." } });
  });
}
