// test dell'orchestrazione: stato per chat, attesa, bozze, errori, eliminazione (API finta, niente rete)
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Api, ChatCompleta, ChatInElenco, Esito, Messaggio, Turno } from "../../src/api/client";
import { creaApplicazione, type Applicazione } from "../../src/app";
import type { EventoFlusso, inviaInFlusso } from "../../src/api/flusso";
import { MSG_CHAT_SPARITA, MSG_ERRORE_PAGINA, testoConferma } from "../../src/formato";
import { inAttesa } from "../../src/stato";

// dati di prova
const ok = <T>(dati: T): Esito<T> => ({ ok: true, dati });
const ko = (status: number, codice: string, messaggio: string): Esito<never> =>
  ({ ok: false, errore: { codice, messaggio, status } });
const chat = (id: number, titolo = `Chat ${id}`): ChatInElenco =>
  ({ id, titolo, ultimo_messaggio_il: null });
const msg = (id: number, ruolo: "utente" | "assistente", testo: string): Messaggio =>
  ({ id, ruolo, testo, strumenti: null, creato_il: "2026-11-13T08:00:00Z" });
const completa = (id: number, messaggi: Messaggio[] = []): ChatCompleta =>
  ({ id, titolo: `Chat ${id}`, creata_il: "2026-11-13T08:00:00Z", ultimo_messaggio_il: null, messaggi });
const turno = (testo: string): Turno =>
  ({ domanda: msg(10, "utente", testo), risposta: msg(11, "assistente", "Sono le 17:50.") });

// promessa risolvibile dal test (risposta dell'agente che arriva più tardi)
function differita<T>() {
  let risolvi!: (v: T) => void;
  const promessa = new Promise<T>((r) => { risolvi = r; });
  return { promessa, risolvi };
}

let api: { [K in keyof Api]: ReturnType<typeof vi.fn> };
let conferma: ReturnType<typeof vi.fn>;
let ridisegna: ReturnType<typeof vi.fn>;
let app: Applicazione;

beforeEach(() => {
  api = {
    elenca: vi.fn(async () => ok([chat(1), chat(2)])),
    crea: vi.fn(async () => ok({ id: 3, titolo: "Nuova chat", creata_il: "2026-11-13T08:00:00Z" })),
    leggi: vi.fn(async (id: number) => ok(completa(id))),
    invia: vi.fn(async (_id: number, testo: string) => ok(turno(testo))),
    elimina: vi.fn(async () => ok(null)),
    // streaming non disponibile: i test di questo file usano l'invio senza stream
    impostazioni: vi.fn(async () => ok({ streaming: false })),
  };
  conferma = vi.fn(() => true);
  ridisegna = vi.fn();
  app = creaApplicazione(api as unknown as Api, conferma as unknown as (t: string) => boolean,
    ridisegna as unknown as () => void);
});

describe("avvio", () => {
  test("avvia apre la chat più recente", async () => {
    await app.avvia();
    expect(app.stato.chat.map((c) => c.id)).toEqual([1, 2]);
    expect(app.stato.aperta).toBe(1);
    expect(api.leggi).toHaveBeenCalledWith(1);
    expect(ridisegna).toHaveBeenCalled();
  });

  test("avvia senza chat lascia aperta null", async () => {
    api.elenca.mockResolvedValue(ok([]));
    await app.avvia();
    expect(app.stato.aperta).toBeNull();
    expect(api.leggi).not.toHaveBeenCalled();
  });

  test("errore dell'elenco nella barra con Riprova", async () => {
    api.elenca.mockResolvedValueOnce(ko(502, "backend_non_raggiungibile", "giù"));
    await app.avvia();
    expect(app.stato.erroreBarra).toEqual({ messaggio: "giù", riprova: true });
    await app.riprovaElenco();
    expect(app.stato.erroreBarra).toBeNull();
    expect(app.stato.aperta).toBe(1);
  });
});

describe("invio", () => {
  beforeEach(async () => { await app.avvia(); });

  test("invio mostra subito la domanda e l'attesa", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    const invio = app.invia(1);
    const s = app.stato.perChat.get(1)!;
    expect(s.provvisoria).toBe("Che ore sono a Tokyo?");
    expect(inAttesa(app.stato, 1)).toBe(true);
    expect(s.bozza).toBe("");
    d.risolvi(ok(turno("Che ore sono a Tokyo?")));
    await invio;
    expect(inAttesa(app.stato, 1)).toBe(false);
  });

  test("invio riuscito aggiunge domanda e risposta e rilegge l'elenco", async () => {
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    await app.invia(1);
    const s = app.stato.perChat.get(1)!;
    expect(s.messaggi.map((m) => m.testo)).toEqual(["Che ore sono a Tokyo?", "Sono le 17:50."]);
    expect(s.provvisoria).toBeNull();
    expect(api.elenca).toHaveBeenCalledTimes(2);
  });

  test("la risposta appena arrivata è da rivelare parola per parola", async () => {
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    await app.invia(1);
    expect(app.stato.perChat.get(1)!.daRivelare).toBe(11);
  });

  test("i messaggi letti all'apertura non sono da rivelare", async () => {
    expect(app.stato.perChat.get(1)!.daRivelare).toBeNull();
  });

  test("invio fallito rimette la domanda nella bozza", async () => {
    api.invia.mockResolvedValueOnce(ko(503, "agente_non_raggiungibile", "Agente non raggiungibile"));
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    await app.invia(1);
    const s = app.stato.perChat.get(1)!;
    expect(s.errore).toBe("Agente non raggiungibile");
    expect(s.bozza).toBe("Che ore sono a Tokyo?");
    expect(s.provvisoria).toBeNull();
    expect(s.messaggi).toEqual([]);
  });

  test("invio concluso dopo cambio di chat", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    const invio = app.invia(1);
    await app.apri(2);
    d.risolvi(ok(turno("Che ore sono a Tokyo?")));
    await invio;
    expect(app.stato.aperta).toBe(2);
    expect(app.stato.perChat.get(1)!.messaggi).toHaveLength(2);
    expect(app.stato.perChat.get(2)!.messaggi).toEqual([]);
  });

  test("invio concluso dopo eliminazione di un'altra chat", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    const invio = app.invia(1);
    api.elenca.mockResolvedValue(ok([chat(1)]));
    await app.elimina(2);
    d.risolvi(ok(turno("Che ore sono a Tokyo?")));
    await invio;
    expect(app.stato.perChat.get(1)!.messaggi).toHaveLength(2);
    expect(app.stato.perChat.has(2)).toBe(false);
  });

  test("invio concluso dopo creazione di una nuova chat", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "Che ore sono a Tokyo?");
    const invio = app.invia(1);
    api.elenca.mockResolvedValue(ok([chat(3, "Nuova chat"), chat(1), chat(2)]));
    await app.nuovaChat();
    d.risolvi(ok(turno("Che ore sono a Tokyo?")));
    await invio;
    expect(app.stato.aperta).toBe(3);
    expect(app.stato.perChat.get(1)!.messaggi).toHaveLength(2);
    expect(app.stato.perChat.get(3)!.messaggi).toEqual([]);
  });

  test("riaprire la chat in attesa non la rilegge e mostra ancora l'attesa", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "x");
    const invio = app.invia(1);
    await app.apri(2);
    await app.apri(1);
    expect(api.leggi).toHaveBeenCalledTimes(2); // avvio (1) e apertura di 2
    expect(inAttesa(app.stato, 1)).toBe(true);
    d.risolvi(ok(turno("x")));
    await invio;
  });

  test("secondo invio ignorato durante attesa", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "uno");
    const invio = app.invia(1);
    app.aggiornaBozza(1, "due");
    await app.invia(1);
    expect(api.invia).toHaveBeenCalledTimes(1);
    d.risolvi(ok(turno("uno")));
    await invio;
  });

  test("bozza per chat", async () => {
    app.aggiornaBozza(1, "a");
    await app.apri(2);
    app.aggiornaBozza(2, "b");
    await app.apri(1);
    expect(app.stato.perChat.get(1)!.bozza).toBe("a");
    expect(app.stato.perChat.get(2)!.bozza).toBe("b");
  });

  test("testo di soli spazi non inviato", async () => {
    app.aggiornaBozza(1, "   \n ");
    await app.invia(1);
    expect(api.invia).not.toHaveBeenCalled();
  });

  test("chiudiErrore azzera errore", async () => {
    api.invia.mockResolvedValueOnce(ko(503, "agente_non_raggiungibile", "Agente non raggiungibile"));
    app.aggiornaBozza(1, "x");
    await app.invia(1);
    app.chiudiErrore(1);
    expect(app.stato.perChat.get(1)!.errore).toBeNull();
  });

  test("il prossimo invio toglie l'errore", async () => {
    api.invia.mockResolvedValueOnce(ko(503, "agente_non_raggiungibile", "Agente non raggiungibile"));
    app.aggiornaBozza(1, "x");
    await app.invia(1);
    await app.invia(1);
    expect(app.stato.perChat.get(1)!.errore).toBeNull();
    expect(app.stato.perChat.get(1)!.messaggi).toHaveLength(2);
  });
});

describe("eliminazione", () => {
  beforeEach(async () => { await app.avvia(); });

  test("elimina annullata non chiama il back-end", async () => {
    conferma.mockReturnValueOnce(false);
    await app.elimina(2);
    expect(conferma).toHaveBeenCalledWith(testoConferma("Chat 2"));
    expect(api.elimina).not.toHaveBeenCalled();
  });

  test("elimina confermata rilegge l'elenco e apre la prima rimasta", async () => {
    api.elenca.mockResolvedValue(ok([chat(2)]));
    await app.elimina(1);
    expect(api.elimina).toHaveBeenCalledWith(1);
    expect(app.stato.aperta).toBe(2);
    expect(app.stato.perChat.has(1)).toBe(false);
  });

  test("elimina dell'ultima chat lascia aperta null", async () => {
    api.elenca.mockResolvedValue(ok([]));
    await app.elimina(1);
    expect(app.stato.aperta).toBeNull();
  });

  test("elimina di chat in attesa ignorata", async () => {
    const d = differita<Esito<Turno>>();
    api.invia.mockReturnValueOnce(d.promessa);
    app.aggiornaBozza(1, "x");
    const invio = app.invia(1);
    await app.elimina(1);
    expect(conferma).not.toHaveBeenCalled();
    expect(api.elimina).not.toHaveBeenCalled();
    d.risolvi(ok(turno("x")));
    await invio;
  });

  test("errore dell'eliminazione nella barra senza Riprova", async () => {
    api.elimina.mockResolvedValueOnce(ko(503, "database_non_disponibile", "DB giù"));
    await app.elimina(2);
    expect(app.stato.erroreBarra).toEqual({ messaggio: "DB giù", riprova: false });
  });
});

describe("apertura e creazione", () => {
  beforeEach(async () => { await app.avvia(); });

  test("apertura con 404 rilegge l'elenco e mostra MSG_CHAT_SPARITA", async () => {
    api.leggi.mockResolvedValueOnce(ko(404, "chat_non_trovata", "Chat non trovata"));
    api.elenca.mockResolvedValue(ok([chat(1)]));
    await app.apri(2);
    expect(app.stato.erroreBarra).toEqual({ messaggio: MSG_CHAT_SPARITA, riprova: false });
    expect(app.stato.chat.map((c) => c.id)).toEqual([1]);
    expect(app.stato.aperta).toBe(1);
  });

  test("404 in ritardo di una chat lasciata non cambia la chat scelta", async () => {
    const lenta = differita<Esito<ChatCompleta>>();
    api.leggi.mockReturnValueOnce(lenta.promessa);
    // dopo la rilettura la prima chat dell'elenco (3) è diversa da quella scelta (1)
    api.elenca.mockResolvedValue(ok([chat(3), chat(1)]));
    const primaApertura = app.apri(2);
    await app.apri(1);
    lenta.risolvi(ko(404, "chat_non_trovata", "Chat non trovata"));
    await primaApertura;
    expect(app.stato.aperta).toBe(1);
    expect(app.stato.perChat.has(2)).toBe(false);
    expect(app.stato.chat.map((c) => c.id)).toEqual([3, 1]);
    expect(app.stato.erroreBarra).toBeNull();
  });

  test("apertura con 503 imposta erroreApertura", async () => {
    api.leggi.mockResolvedValueOnce(ko(503, "database_non_disponibile", "DB giù"));
    await app.apri(2);
    expect(app.stato.aperta).toBe(2);
    expect(app.stato.erroreApertura).toBe("DB giù");
    await app.apri(2);
    expect(app.stato.erroreApertura).toBeNull();
  });

  test("nuova chat: crea, rilegge e apre", async () => {
    api.elenca.mockResolvedValue(ok([chat(3, "Nuova chat"), chat(1), chat(2)]));
    await app.nuovaChat();
    expect(app.stato.aperta).toBe(3);
    expect(app.stato.chat[0].id).toBe(3);
  });

  test("errore di nuovaChat in erroreBarra", async () => {
    api.crea.mockResolvedValueOnce(ko(503, "database_non_disponibile", "DB giù"));
    await app.nuovaChat();
    expect(app.stato.erroreBarra).toEqual({ messaggio: "DB giù", riprova: false });
    expect(app.stato.aperta).toBe(1);
  });
});

// ---------- step 10: streaming ----------
describe("streaming", () => {
  // flusso finto: il test manda gli eventi con `manda` e chiude con `chiudi`
  function flussoFinto() {
    let suEvento: (e: EventoFlusso) => void = () => {};
    let chiudi!: (esito: Esito<Turno>) => void;
    const flusso = vi.fn((_id: number, _testo: string, se: (e: EventoFlusso) => void) => {
      suEvento = se;
      return new Promise<Esito<Turno>>((r) => { chiudi = r; });
    });
    return { flusso, manda: (e: EventoFlusso) => suEvento(e), chiudi: (e: Esito<Turno>) => chiudi(e) };
  }

  // archivio finto a chiavi (streaming, log), come localStorage
  function archivioFinto(valori: Record<string, string> = {}) {
    const archivio = {
      valori: { ...valori },
      leggi: vi.fn((chiave: string) => archivio.valori[chiave] ?? null),
      scrivi: vi.fn((chiave: string, v: string) => { archivio.valori[chiave] = v; }),
    };
    return archivio;
  }

  async function conStreaming(archivio = archivioFinto(), msPerParola = 0) {
    api.impostazioni.mockResolvedValue(ok({ streaming: true }));
    const f = flussoFinto();
    const a = creaApplicazione(api as unknown as Api, conferma as unknown as (t: string) => boolean,
      ridisegna as unknown as () => void, f.flusso as unknown as typeof inviaInFlusso, archivio,
      msPerParola);
    await a.avvia();
    return { a, f, archivio };
  }

  test("evento bozza azzera il testo in arrivo, testo accumulato", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    const s = a.stato.perChat.get(1)!;
    expect(s.fase).toBe("pensa");
    f.manda({ tipo: "bozza", dati: {} });
    f.manda({ tipo: "testo", dati: { testo: "Sono " } });
    f.manda({ tipo: "testo", dati: { testo: "le 9." } });
    expect(s.testoInArrivo).toBe("Sono le 9.");
    expect(s.ultimoPezzo).toBeGreaterThan(0);
    f.manda({ tipo: "bozza", dati: {} });
    expect(s.testoInArrivo).toBe("");
    f.chiudi(ok(turno("Che ore sono?")));
    await invio;
  });

  test("strumento imposta la fase e revisione l'avviso", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "x");
    const invio = a.invia(1);
    const s = a.stato.perChat.get(1)!;
    f.manda({ tipo: "strumento", dati: { nome: "tooltime", argomenti: {} } });
    expect([s.fase, s.strumentoInUso]).toEqual(["strumento", "tooltime"]);
    f.manda({ tipo: "fase", dati: { fase: "revisore" } });
    expect(s.fase).toBe("revisore");
    f.manda({ tipo: "revisione", dati: { motivo: "manca Tokyo" } });
    expect(s.avvisoRevisore).toBe("manca Tokyo");
    f.chiudi(ok(turno("x")));
    await invio;
  });

  test("fine sostituisce il testo in arrivo", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.manda({ tipo: "testo", dati: { testo: "bozza vecchia" } });
    f.manda({ tipo: "revisione", dati: { motivo: "m" } });
    f.chiudi(ok(turno("Che ore sono?")));
    await invio;
    const s = a.stato.perChat.get(1)!;
    expect(s.messaggi.map((m) => m.testo)).toEqual(["Che ore sono?", "Sono le 17:50."]);
    // la bozza mostrata era diversa: la risposta definitiva esce parola per parola
    expect(s.daRivelare).toBe(11);
    expect([s.testoInArrivo, s.avvisoRevisore, s.fase, s.provvisoria]).toEqual(["", null, null, null]);
    expect(api.invia).not.toHaveBeenCalled();
  });

  test("errore rimette la domanda", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.manda({ tipo: "testo", dati: { testo: "A met" } });
    f.chiudi({ ok: false, errore: { codice: "flusso_interrotto", messaggio: "Connessione interrotta" } });
    await invio;
    const s = a.stato.perChat.get(1)!;
    expect([s.errore, s.bozza, s.testoInArrivo]).toEqual(["Connessione interrotta", "Che ore sono?", ""]);
    expect(s.messaggi).toEqual([]);
  });

  test("eventi alla chat di partenza", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "x");
    const invio = a.invia(1);
    await a.apri(2);
    f.manda({ tipo: "testo", dati: { testo: "per la chat 1" } });
    expect(a.stato.perChat.get(1)!.testoInArrivo).toBe("per la chat 1");
    expect(a.stato.perChat.get(2)!.testoInArrivo).toBe("");
    f.chiudi(ok(turno("x")));
    await invio;
  });

  test("streaming scelto salvato", async () => {
    const { a, archivio } = await conStreaming();
    expect(a.stato.streamingDisponibile && a.stato.streamingScelto).toBe(true);
    a.impostaStreaming(false);
    expect(a.stato.streamingScelto).toBe(false);
    expect(archivio.scrivi).toHaveBeenCalledWith("streaming", "false");
  });

  test("senza streaming scelto invia come oggi", async () => {
    const { a, f } = await conStreaming(archivioFinto({ streaming: "false" }));
    expect(a.stato.streamingScelto).toBe(false);
    a.aggiornaBozza(1, "x");
    await a.invia(1);
    expect(f.flusso).not.toHaveBeenCalled();
    expect(api.invia).toHaveBeenCalled();
    expect(a.stato.perChat.get(1)!.daRivelare).toBe(11);
  });

  test("streaming spento a pagina aperta: si riprova senza stream e l'interruttore sparisce", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.chiudi({ ok: false, errore: { codice: "streaming_disattivato", messaggio: "Lo streaming è disattivato." } });
    await invio;
    expect(a.stato.streamingDisponibile).toBe(false);
    expect(api.invia).toHaveBeenCalledWith(1, "Che ore sono?");
    const s = a.stato.perChat.get(1)!;
    expect(s.errore).toBeNull();
    expect(s.messaggi.map((m) => m.testo)).toEqual(["Che ore sono?", "Sono le 17:50."]);
  });

  test("errore della pagina durante lo stream: messaggio chiaro, domanda nel campo", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "x");
    f.flusso.mockRejectedValueOnce(new TypeError("bug"));
    await a.invia(1);
    const s = a.stato.perChat.get(1)!;
    expect(s.errore).toBe(MSG_ERRORE_PAGINA);
    expect(s.bozza).toBe("x");
    expect(s.provvisoria).toBeNull();
  });

  test("parole mostrate a ritmo costante anche se arrivano insieme", async () => {
    vi.useFakeTimers();
    try {
      const { a, f } = await conStreaming(archivioFinto(), 150);
      a.aggiornaBozza(1, "Che ore sono?");
      const invio = a.invia(1);
      const s = a.stato.perChat.get(1)!;
      f.manda({ tipo: "testo", dati: { testo: "A " } });
      f.manda({ tipo: "testo", dati: { testo: "Tokyo " } });
      f.manda({ tipo: "testo", dati: { testo: "sono." } });
      expect(s.testoInArrivo).toBe("");
      await vi.advanceTimersByTimeAsync(150);
      expect(s.testoInArrivo).toBe("A ");
      await vi.advanceTimersByTimeAsync(150);
      expect(s.testoInArrivo).toBe("A Tokyo ");
      // la fine arriva prima che le parole siano uscite: la risposta aspetta l'ultima parola
      f.chiudi(ok(turno("Che ore sono?")));
      await vi.advanceTimersByTimeAsync(10);
      expect(s.messaggi).toEqual([]);
      expect(s.provvisoria).toBe("Che ore sono?");
      await vi.advanceTimersByTimeAsync(300);
      await invio;
      expect(s.messaggi.map((m) => m.testo)).toEqual(["Che ore sono?", "Sono le 17:50."]);
    } finally {
      vi.useRealTimers();
    }
  });

  test("una nuova bozza svuota anche le parole in coda", async () => {
    vi.useFakeTimers();
    try {
      const { a, f } = await conStreaming(archivioFinto(), 150);
      a.aggiornaBozza(1, "x");
      const invio = a.invia(1);
      const s = a.stato.perChat.get(1)!;
      f.manda({ tipo: "testo", dati: { testo: "vecchia " } });
      f.manda({ tipo: "testo", dati: { testo: "bozza " } });
      await vi.advanceTimersByTimeAsync(150);
      f.manda({ tipo: "bozza", dati: {} });
      f.manda({ tipo: "testo", dati: { testo: "Nuova." } });
      await vi.advanceTimersByTimeAsync(150);
      expect(s.testoInArrivo).toBe("Nuova.");
      f.chiudi(ok(turno("x")));
      await vi.advanceTimersByTimeAsync(300);
      await invio;
    } finally {
      vi.useRealTimers();
    }
  });

  test("log acceso: anche la risposta definitiva esce parola per parola", async () => {
    const { a, f } = await conStreaming(archivioFinto({ log: "true" }));
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.manda({ tipo: "testo", dati: { testo: "Sono le 17:50." } });
    f.chiudi(ok(turno("Che ore sono?")));
    await invio;
    expect(a.stato.perChat.get(1)!.daRivelare).toBe(11);
  });

  test("log spento: la risposta già arrivata uguale non si ripete", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.manda({ tipo: "testo", dati: { testo: "Sono le 17:50." } });
    f.chiudi(ok(turno("Che ore sono?")));
    await invio;
    expect(a.stato.perChat.get(1)!.daRivelare).toBeNull();
  });

  test("log spento: risposta definitiva diversa dalla bozza esce parola per parola", async () => {
    const { a, f } = await conStreaming();
    a.aggiornaBozza(1, "Che ore sono?");
    const invio = a.invia(1);
    f.manda({ tipo: "testo", dati: { testo: "Bozza incompleta." } });
    f.chiudi(ok(turno("Che ore sono?")));
    await invio;
    expect(a.stato.perChat.get(1)!.daRivelare).toBe(11);
  });

  test("log spento di base, acceso e ricordato", async () => {
    const { a, archivio } = await conStreaming();
    expect(a.stato.logVisibile).toBe(false);
    a.impostaLog(true);
    expect(a.stato.logVisibile).toBe(true);
    expect(archivio.scrivi).toHaveBeenCalledWith("log", "true");
  });

  test("log acceso letto all'avvio", async () => {
    const { a } = await conStreaming(archivioFinto({ log: "true" }));
    expect(a.stato.logVisibile).toBe(true);
  });

  test("streaming non disponibile ignora la scelta salvata", async () => {
    api.impostazioni.mockResolvedValue(ok({ streaming: false }));
    const f = flussoFinto();
    const a = creaApplicazione(api as unknown as Api, conferma as unknown as (t: string) => boolean,
      ridisegna as unknown as () => void, f.flusso as unknown as typeof inviaInFlusso, archivioFinto({ streaming: "true" }));
    await a.avvia();
    expect([a.stato.streamingDisponibile, a.stato.streamingScelto]).toEqual([false, false]);
    a.aggiornaBozza(1, "x");
    await a.invia(1);
    expect(f.flusso).not.toHaveBeenCalled();
  });
});
