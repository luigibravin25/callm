// test del client dell'API: percorsi generati dall'OpenAPI e traduzione degli errori
import { describe, expect, test, vi } from "vitest";
import { creaApi, traduciErrore } from "../../src/api/client";
import { MSG_BACKEND_GIU, MSG_RETE } from "../../src/formato";

// risposta JSON finta del back-end
function json(status: number, corpo: unknown): Response {
  return new Response(JSON.stringify(corpo), {
    status, headers: { "Content-Type": "application/json" },
  });
}

// client con fetch simulato; restituisce anche la funzione per leggere le richieste fatte
function conFetch(risposta: () => Response | Promise<Response>) {
  const fetchFinto = vi.fn(async (_richiesta: Request) => risposta());
  const api = creaApi({ baseUrl: "http://test/api", fetch: fetchFinto as unknown as typeof fetch });
  return { api, richiesta: () => fetchFinto.mock.calls[0][0] as Request };
}

describe("chiamate", () => {
  test("elenca: GET /api/chat con i dati", async () => {
    const { api, richiesta } = conFetch(() =>
      json(200, [{ id: 1, titolo: "T", ultimo_messaggio_il: null }]));
    const esito = await api.elenca();
    expect(esito).toEqual({ ok: true, dati: [{ id: 1, titolo: "T", ultimo_messaggio_il: null }] });
    expect(richiesta().url).toBe("http://test/api/chat");
    expect(richiesta().method).toBe("GET");
  });

  test("invia: POST /api/chat/3/messaggi con il testo", async () => {
    const { api, richiesta } = conFetch(() => json(200, { domanda: {}, risposta: {} }));
    const esito = await api.invia(3, "ciao");
    expect(esito.ok).toBe(true);
    expect(richiesta().url).toBe("http://test/api/chat/3/messaggi");
    expect(richiesta().method).toBe("POST");
    expect(await richiesta().text()).toBe('{"testo":"ciao"}');
  });

  test("elimina: 204 senza corpo", async () => {
    const { api, richiesta } = conFetch(() => new Response(null, { status: 204 }));
    expect(await api.elimina(3)).toEqual({ ok: true, dati: null });
    expect(richiesta().method).toBe("DELETE");
    expect(richiesta().url).toBe("http://test/api/chat/3");
  });

  test("crea e leggi", async () => {
    const creata = { id: 7, titolo: "Nuova chat", creata_il: "2026-11-13T08:00:00Z" };
    expect(await conFetch(() => json(201, creata)).api.crea()).toEqual({ ok: true, dati: creata });
    const { api, richiesta } = conFetch(() => json(200, { ...creata, messaggi: [] }));
    expect((await api.leggi(7)).ok).toBe(true);
    expect(richiesta().url).toBe("http://test/api/chat/7");
  });
});

describe("errori", () => {
  test("corpo {errore, messaggio}: messaggio del back-end così com'è", async () => {
    const { api } = conFetch(() => json(503,
      { errore: "agente_non_raggiungibile", messaggio: "Agente non raggiungibile" }));
    expect(await api.invia(1, "x")).toEqual({ ok: false, errore: {
      codice: "agente_non_raggiungibile", messaggio: "Agente non raggiungibile", status: 503 } });
  });

  test("502 con corpo vuoto: back-end non raggiungibile", async () => {
    const { api } = conFetch(() => new Response("", { status: 502 }));
    const esito = await api.elenca();
    expect(esito).toEqual({ ok: false, errore: {
      codice: "backend_non_raggiungibile", messaggio: MSG_BACKEND_GIU(502), status: 502 } });
  });

  test("500 con testo semplice: back-end non raggiungibile", async () => {
    const { api } = conFetch(() =>
      new Response("Internal Server Error", { status: 500, headers: { "Content-Type": "text/plain" } }));
    const esito = await api.crea();
    expect(esito.ok).toBe(false);
    if (!esito.ok) expect(esito.errore.messaggio).toBe(MSG_BACKEND_GIU(500));
  });

  test("fetch che lancia: rete", async () => {
    const { api } = conFetch(() => { throw new TypeError("Failed to fetch"); });
    expect(await api.leggi(1)).toEqual({ ok: false, errore: { codice: "rete", messaggio: MSG_RETE } });
  });

  test("traduciErrore ignora corpi con campi non testuali", () => {
    expect(traduciErrore(500, { errore: 1, messaggio: "x" }).codice).toBe("backend_non_raggiungibile");
  });
});
