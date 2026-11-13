// funzioni pure di formato e messaggi fissi dell'interfaccia (testabili senza DOM né rete)

// messaggi fissi mostrati all'utente
export const MSG_RETE =
  "Impossibile contattare il server dell'interfaccia: controlla la connessione e ricarica la pagina.";
export const MSG_CHAT_SPARITA = "La chat non esiste più.";
export const MSG_INVITO = "Nessuna chat: crea la prima con + Nuova chat";
export const MSG_NESSUN_MESSAGGIO = "nessun messaggio";
// stream della risposta finito senza l'evento di fine (step 10)
export const MSG_FLUSSO_INTERROTTO = "Connessione interrotta prima della fine della risposta.";

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

// ora di un messaggio "hh:mm" nell'ora locale del browser
export function formattaOra(iso: string): string {
  const d = new Date(iso);
  return `${dueCifre(d.getHours())}:${dueCifre(d.getMinutes())}`;
}

// prime n parole di un testo, con spazi e a capo originali (per la rivelazione parola per parola)
export function primeParole(testo: string, n: number): string {
  const parole = [...testo.matchAll(/\S+/g)];
  if (n >= parole.length) return testo;
  if (n <= 0) return "";
  const ultima = parole[n - 1];
  return testo.slice(0, ultima.index! + ultima[0].length);
}

// numero di parole di un testo
export function contaParole(testo: string): number {
  return (testo.match(/\S+/g) ?? []).length;
}

// gruppo dell'elenco per la data dell'ultimo messaggio (giorni di calendario nell'ora locale);
// chat senza messaggi = appena creata → «Oggi»
export function gruppoData(iso: string | null | undefined, adesso = new Date()): string {
  if (!iso) return "Oggi";
  const giorno = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const giorni = Math.round((giorno(adesso) - giorno(new Date(iso))) / 86_400_000);
  if (giorni <= 0) return "Oggi";
  if (giorni === 1) return "Ieri";
  if (giorni <= 7) return "Ultimi 7 giorni";
  return "Più vecchie";
}

// icona di ogni strumento conosciuto; gli altri hanno la chiave inglese
const ICONE: Record<string, string> = { tooltime: "🕒" };
const ICONA_PREDEFINITA = "🔧";

// nome di una voce {nome, argomenti}; voce malformata → null (gli argomenti non si mostrano)
function nomeStrumento(voce: unknown): string | null {
  if (typeof voce !== "object" || voce === null) return null;
  const { nome } = voce as { nome?: unknown };
  return typeof nome === "string" && nome ? nome : null;
}

// strumenti usati nel turno (campo strumenti del back-end) → "🕒 tooltime · 🔧 altro":
// solo i nomi, ognuno una volta con la sua icona; nessuno valido → null
export function rigaStrumenti(strumenti: unknown): string | null {
  if (!Array.isArray(strumenti)) return null;
  const nomi = [...new Set(strumenti.map(nomeStrumento).filter((n): n is string => n !== null))];
  return nomi.length ? nomi.map((n) => `${ICONE[n] ?? ICONA_PREDEFINITA} ${n}`).join(" · ") : null;
}
