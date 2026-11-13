// stato in memoria dell'interfaccia: elenco delle chat, chat aperta, dati di ogni chat (niente localStorage)
import type { ChatInElenco, Messaggio } from "./api/client";

// dati di una chat
export interface StatoChat {
  messaggi: Messaggio[];        // confermati dal back-end
  provvisoria: string | null;   // domanda in attesa (mostrata subito); null = nessuna attesa
  errore: string | null;        // riquadro d'errore della chat
  bozza: string;                // testo nel campo di questa chat
  caricata: boolean;            // messaggi letti dal back-end almeno una volta
  daRivelare: number | null;    // id della risposta appena arrivata, da mostrare parola per parola
}

// errore della barra laterale; riprova = pulsante «Riprova» (solo per il caricamento dell'elenco)
export interface ErroreBarra {
  messaggio: string;
  riprova: boolean;
}

// stato di tutta l'interfaccia
export interface Stato {
  chat: ChatInElenco[];
  aperta: number | null;
  perChat: Map<number, StatoChat>;
  erroreBarra: ErroreBarra | null;
  erroreApertura: string | null; // errore di GET /chat/{id} diverso da 404 (con «Riprova»)
}

export function statoIniziale(): Stato {
  return { chat: [], aperta: null, perChat: new Map(), erroreBarra: null, erroreApertura: null };
}

// dati della chat id, creati vuoti alla prima richiesta
export function datiChat(s: Stato, id: number): StatoChat {
  let dati = s.perChat.get(id);
  if (!dati) {
    dati = { messaggi: [], provvisoria: null, errore: null, bozza: "", caricata: false, daRivelare: null };
    s.perChat.set(id, dati);
  }
  return dati;
}

// la chat id aspetta una risposta dell'agente
export function inAttesa(s: Stato, id: number): boolean {
  return s.perChat.get(id)?.provvisoria != null;
}
