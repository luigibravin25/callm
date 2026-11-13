// test dell'orchestrazione: stato per chat, attesa, bozze, errori, eliminazione (API finta, niente rete)
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Api, ChatCompleta, ChatInElenco, Esito, Messaggio, Turno } from "../../src/api/client";
import { creaApplicazione, type Applicazione } from "../../src/app";
import { MSG_CHAT_SPARITA, testoConferma } from "../../src/formato";
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
