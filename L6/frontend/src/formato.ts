// funzioni pure di formato e messaggi fissi dell'interfaccia (testabili senza DOM né rete)

// messaggi fissi mostrati all'utente
export const MSG_RETE =
  "Impossibile contattare il server dell'interfaccia: controlla la connessione e ricarica la pagina.";
export const MSG_CHAT_SPARITA = "La chat non esiste più.";
export const MSG_INVITO = "Nessuna chat: crea la prima con + Nuova chat";
export const MSG_NESSUN_MESSAGGIO = "nessun messaggio";

// back-end spento o risposta senza il corpo {errore, messaggio} (per esempio dal proxy di Vite)
export function MSG_BACKEND_GIU(status: number): string {
  return `Il back-end non risponde (HTTP ${status}): controlla che sia avviato.`;
}

// testo della conferma prima di eliminare una chat
export function testoConferma(titolo: string): string {
  return `Eliminare la chat «${titolo}»? L'operazione non si può annullare.`;
}

// due cifre con lo zero davanti (8 → "08")
function dueCifre(n: number): string {
  return String(n).padStart(2, "0");
}

// data ISO del back-end → "gg/mm hh:mm" nell'ora locale del browser; null → "nessun messaggio"
export function formattaData(iso: string | null | undefined): string {
  if (!iso) return MSG_NESSUN_MESSAGGIO;
  const d = new Date(iso);
  return `${dueCifre(d.getDate())}/${dueCifre(d.getMonth() + 1)} ` +
    `${dueCifre(d.getHours())}:${dueCifre(d.getMinutes())}`;
}

// valore di un argomento: le stringhe così come sono, il resto in JSON (2, true, [..])
function valore(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

// una voce {nome, argomenti} → "nome (k: v, k2: v2)"; voce malformata → null
function descriviStrumento(voce: unknown): string | null {
  if (typeof voce !== "object" || voce === null) return null;
  const { nome, argomenti } = voce as { nome?: unknown; argomenti?: unknown };
  if (typeof nome !== "string" || !nome) return null;
  // argomenti assenti o non oggetto: solo il nome
  if (typeof argomenti !== "object" || argomenti === null || Array.isArray(argomenti)) return nome;
  const coppie = Object.entries(argomenti).map(([k, v]) => `${k}: ${valore(v)}`);
  return coppie.length ? `${nome} (${coppie.join(", ")})` : nome;
}

// strumenti usati nel turno (campo strumenti del back-end) → riga "🔧 ..."; nessuno valido → null
export function rigaStrumenti(strumenti: unknown): string | null {
  if (!Array.isArray(strumenti)) return null;
  const voci = strumenti.map(descriviStrumento).filter((v): v is string => v !== null);
  return voci.length ? `🔧 ${voci.join(" · ")}` : null;
}
