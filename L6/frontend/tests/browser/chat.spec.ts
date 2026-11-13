// prove nel browser vero (Chrome) con il back-end simulato: elenco, creazione, eliminazione,
// attesa e cambio di chat, agente e back-end spenti, tema scuro
import { expect, test } from "@playwright/test";
import { MSG_INVITO, testoConferma } from "../../src/formato";
import { chatFinta, differita, messaggio, simulaBackend, type Finto } from "./finto";

// due chat: la più recente (Tokyo) con una risposta, poi una vuota
function dueChat(): Finto {
  return {
    chat: [
      chatFinta(1, "Che ore sono a Tokyo?", [
        messaggio(1, "utente", "Che ore sono a Tokyo?"),
        messaggio(2, "assistente", "A Tokyo sono le 17:50.",
          [{ nome: "tooltime", argomenti: { fuso: "Asia/Tokyo" } }]),
      ]),
      chatFinta(2, "Fusi orari in Europa"),
    ],
    risposta: { testo: "A New York sono le 03:50.",
      strumenti: [{ nome: "tooltime", argomenti: { fuso: "America/New_York" } }] },
  };
}

test("apre la chat più recente", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  await expect(page.locator("#elenco-chat .titolo")).toHaveText(["Che ore sono a Tokyo?", "Fusi orari in Europa"]);
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Che ore sono a Tokyo?");
  await expect(page.locator("#messaggi .msg.assistente .testo")).toHaveText("A Tokyo sono le 17:50.");
  await expect(page.locator("#messaggi .strumenti")).toHaveText("🔧 tooltime (fuso: Asia/Tokyo)");
});

test("senza chat mostra l'invito", async ({ page }) => {
  await simulaBackend(page, { chat: [] });
  await page.goto("/");
  await expect(page.locator("#invito")).toHaveText(MSG_INVITO);
});

test("nuova chat", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li")).toHaveCount(3);
  await expect(page.locator("#elenco-chat li").first().locator(".titolo")).toHaveText("Nuova chat");
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Nuova chat");
  await expect(page.locator("#campo")).toBeFocused();
});

test("eliminazione annullata e confermata", async ({ page }) => {
  await simulaBackend(page, dueChat());
  await page.goto("/");
  const cestino = page.getByRole("button", { name: "Elimina chat Fusi orari in Europa" });
  let testoDialogo = "";
  page.once("dialog", (d) => { testoDialogo = d.message(); void d.dismiss(); });
  await cestino.click();
  expect(testoDialogo).toBe(testoConferma("Fusi orari in Europa"));
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  page.once("dialog", (d) => void d.accept());
  await cestino.click();
  await expect(page.locator("#elenco-chat li")).toHaveCount(1);
});

test("attesa e cambio chat", async ({ page }) => {
  const finto = dueChat();
  const d = differita();
  finto.attesaInvio = d.promessa;
  await simulaBackend(page, finto);
  await page.goto("/");
  await page.fill("#campo", "E a New York?");
  await page.press("#campo", "Enter");
  // domanda subito visibile, «Assistente: …», Invia disattivato
  await expect(page.locator("#messaggi .msg.utente .testo").last()).toHaveText("E a New York?");
  await expect(page.locator("#messaggi .msg.utente .chi").last()).toHaveText("Tu");
  await expect(page.locator(".attesa")).toContainText("Assistente:");
  await expect(page.locator("#invia")).toBeDisabled();
  await expect(page.locator("#campo")).toBeDisabled();
  // un'altra chat resta usabile durante l'attesa
  await page.click("#elenco-chat li[data-id='2'] .apri");
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Fusi orari in Europa");
  await expect(page.locator("#campo")).toBeEnabled();
  await expect(page.locator("#elenco-chat li[data-id='1']")).toHaveClass(/in-attesa/);
  // la risposta arriva mentre si guarda l'altra chat; tornando si vede
  d.risolvi();
  await expect(page.locator("#elenco-chat li[data-id='1']")).not.toHaveClass(/in-attesa/);
  await page.click("#elenco-chat li[data-id='1'] .apri");
  await expect(page.locator("#messaggi .msg.assistente .testo").last()).toHaveText("A New York sono le 03:50.");
  await expect(page.locator("#messaggi .strumenti").last()).toHaveText("🔧 tooltime (fuso: America/New_York)");
  await expect(page.locator(".attesa")).toHaveCount(0);
});

test("agente spento", async ({ page }) => {
  const finto = dueChat();
  finto.erroreInvio = { status: 503,
    corpo: { errore: "agente_non_raggiungibile", messaggio: "L'agente non è raggiungibile." } };
  await simulaBackend(page, finto);
  await page.goto("/");
  await page.fill("#campo", "E a New York?");
  await page.click("#invia");
  await expect(page.locator("#errore-chat")).toContainText("L'agente non è raggiungibile.");
  await expect(page.locator("#campo")).toHaveValue("E a New York?");
  await expect(page.locator("#campo")).toBeEnabled();
  await expect(page.locator(".attesa")).toHaveCount(0);
  // l'interfaccia resta usabile
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li")).toHaveCount(3);
  await page.click("#elenco-chat li[data-id='1'] .apri");
  await expect(page.locator("#errore-chat")).toContainText("L'agente non è raggiungibile.");
  await expect(page.locator("#campo")).toHaveValue("E a New York?");
});

test("back-end spento", async ({ page }) => {
  const finto = dueChat();
  finto.erroreElenco = { status: 502, corpo: "" };
  await simulaBackend(page, finto);
  await page.goto("/");
  await expect(page.locator("#errore-barra")).toContainText("Il back-end non risponde (HTTP 502)");
  delete finto.erroreElenco;
  await page.click("#errore-barra .riprova");
  await expect(page.locator("#elenco-chat li")).toHaveCount(2);
  await expect(page.locator("#errore-barra")).toBeHidden();
});

// nessuna simulazione: il proxy vero di Vite punta a una porta chiusa (BACKEND_URL della configurazione)
test("proxy di Vite con back-end spento", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#errore-barra")).toContainText(/Il back-end non risponde \(HTTP \d+\)/);
  await expect(page.locator("#nuova-chat")).toBeEnabled();
});

test.describe("tema", () => {
  test.use({ colorScheme: "light" });

  test("tema scuro anche con sistema chiaro", async ({ page }) => {
    await simulaBackend(page, { chat: [] });
    await page.goto("/");
    const sfondo = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(sfondo).toBe("rgb(15, 17, 21)");
  });
});
