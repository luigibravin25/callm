// test della lettura dello stream SSE del back-end: blocchi spezzati, accenti, ping, fine ed errori
import { describe, expect, test, vi } from "vitest";
import { creaApi } from "../../src/api/client";
import { inviaInFlusso, leggiEventi, type EventoFlusso } from "../../src/api/flusso";
import { MSG_FLUSSO_INTERROTTO } from "../../src/formato";

const codifica = new TextEncoder();

// blocchi di byte come arrivano da fetch
async function* blocchi(...parti: (string | Uint8Array)[]) {
  for (const p of parti) yield typeof p === "string" ? codifica.encode(p) : p;
}

async function tutti(sorgente: AsyncIterable<EventoFlusso>) {
  const eventi: EventoFlusso[] = [];
  for await (const e of sorgente) eventi.push(e);
  return eventi;
}

const sse = (tipo: string, dati: unknown) => `event: ${tipo}\ndata: ${JSON.stringify(dati)}\n\n`;

const TURNO = {
  domanda: { id: 1, ruolo: "utente", testo: "Che ore sono?", strumenti: null, creato_il: "2026-11-13T08:00:00Z" },
  risposta: { id: 2, ruolo: "assistente", testo: "Sono le 9.", strumenti: [{ nome: "tooltime", argomenti: {} }],
    creato_il: "2026-11-13T08:00:01Z" },
};

describe("leggiEventi", () => {
  test("più eventi in una lettura", async () => {
    const eventi = await tutti(leggiEventi(blocchi(sse("fase", { fase: "pensa" }) + sse("bozza", {}))));
    expect(eventi).toEqual([{ tipo: "fase", dati: { fase: "pensa" } }, { tipo: "bozza", dati: {} }]);
  });

  test("evento spezzato tra due letture", async () => {
    const testo = sse("testo", { testo: "Sono le 9." });
    const eventi = await tutti(leggiEventi(blocchi(testo.slice(0, 11), testo.slice(11))));
    expect(eventi).toEqual([{ tipo: "testo", dati: { testo: "Sono le 9." } }]);
  });

  test("accento spezzato tra due letture", async () => {
    const byte = codifica.encode(sse("testo", { testo: "è" }));
    // «è» sono due byte: si taglia in mezzo
    const taglio = byte.indexOf(0xc3) + 1;
    const eventi = await tutti(leggiEventi(blocchi(byte.slice(0, taglio), byte.slice(taglio))));
    expect(eventi).toEqual([{ tipo: "testo", dati: { testo: "è" } }]);
  });

  test("ping ignorato", async () => {
    const eventi = await tutti(leggiEventi(blocchi(": ping\n\n", sse("bozza", {}))));
    expect(eventi).toEqual([{ tipo: "bozza", dati: {} }]);
  });
});

// client con fetch finto che risponde con un corpo SSE (o un errore JSON)
function conFetch(risposta: Response) {
  const fetchFinto = vi.fn(async (_url: string, _opzioni?: RequestInit) => risposta);
  return { fetchFinto, opzioni: { fetch: fetchFinto as unknown as typeof fetch, baseUrl: "http://test/api" } };
}

describe("inviaInFlusso", () => {
  test("fine restituisce il turno", async () => {
    const corpo = sse("fase", { fase: "pensa" }) + sse("testo", { testo: "Sono " }) + sse("fine", TURNO);
    const { fetchFinto, opzioni } = conFetch(new Response(corpo, { headers: { "Content-Type": "text/event-stream" } }));
    const visti: string[] = [];
    const esito = await inviaInFlusso(7, "Che ore sono?", (e) => visti.push(e.tipo), opzioni);
    expect(esito).toEqual({ ok: true, dati: TURNO });
    expect(visti).toEqual(["fase", "testo", "fine"]);
    expect(fetchFinto.mock.calls[0][0]).toBe("http://test/api/chat/7/messaggi/stream");
    expect(JSON.parse(String(fetchFinto.mock.calls[0][1]!.body))).toEqual({ testo: "Che ore sono?" });
  });

  test("errore restituisce l'esito d'errore", async () => {
    const corpo = sse("fase", { fase: "pensa" }) + sse("errore", { errore: "modello_non_raggiungibile", messaggio: "LM Studio giù" });
    const { opzioni } = conFetch(new Response(corpo));
    expect(await inviaInFlusso(1, "x", () => {}, opzioni)).toEqual(
      { ok: false, errore: { codice: "modello_non_raggiungibile", messaggio: "LM Studio giù" } });
  });

  test("fine mancante → flusso interrotto", async () => {
    const { opzioni } = conFetch(new Response(sse("testo", { testo: "A met" })));
    expect(await inviaInFlusso(1, "x", () => {}, opzioni)).toEqual(
      { ok: false, errore: { codice: "flusso_interrotto", messaggio: MSG_FLUSSO_INTERROTTO } });
  });

  test("status 409 → messaggio del back-end", async () => {
    const { opzioni } = conFetch(new Response(JSON.stringify({ errore: "streaming_disattivato", messaggio: "Spento." }),
      { status: 409, headers: { "Content-Type": "application/json" } }));
    const esito = await inviaInFlusso(1, "x", () => {}, opzioni);
    expect(esito.ok).toBe(false);
    if (!esito.ok) expect(esito.errore).toMatchObject({ codice: "streaming_disattivato", messaggio: "Spento." });
  });
});

test("impostazioni", async () => {
  const fetchFinto = vi.fn(async (_r: Request) => new Response(JSON.stringify({ streaming: true }),
    { headers: { "Content-Type": "application/json" } }));
  const api = creaApi({ baseUrl: "http://test/api", fetch: fetchFinto as unknown as typeof fetch });
  expect(await api.impostazioni()).toEqual({ ok: true, dati: { streaming: true } });
  expect((fetchFinto.mock.calls[0][0] as Request).url).toBe("http://test/api/impostazioni");
});
