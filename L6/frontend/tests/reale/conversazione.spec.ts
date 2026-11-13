// prova reale dal browser: conversazione con uso di uno strumento, chat ancora presente dopo il ricaricamento
import { expect, test } from "@playwright/test";

test.skip(process.env.RUN_E2E !== "1",
  'imposta $env:RUN_E2E = "1" e avvia database, agente, back-end e npm run dev');

test("conversazione con tooltime dal browser", async ({ page }, info) => {
  await page.goto("/");
  await page.click("#nuova-chat");
  await expect(page.locator("#elenco-chat li.aperta .titolo")).toHaveText("Nuova chat");
  const id = await page.locator("#elenco-chat li.aperta").getAttribute("data-id");
  await page.fill("#campo", "Che ore sono a Tokyo?");
  await page.press("#campo", "Enter");
  await expect(page.locator(".attesa")).toContainText("Assistente:");
  // risposta vera dell'agente (LM Studio): fino a 5 minuti
  const risposta = page.locator("#messaggi .msg.assistente:not(.attesa)").last();
  await expect(risposta).toBeVisible({ timeout: 300_000 });
  await expect(risposta.locator(".strumenti")).toContainText("tooltime");
  await page.screenshot({ path: info.outputPath("conversazione.png"), fullPage: true });
  // titolo dalla prima domanda e chat ancora presente dopo il ricaricamento della pagina
  await page.reload();
  const voce = page.locator(`#elenco-chat li[data-id='${id}']`);
  await expect(voce.locator(".titolo")).toHaveText("Che ore sono a Tokyo?");
  await voce.locator(".apri").click();
  await expect(page.locator("#messaggi .strumenti").last()).toContainText("tooltime");
});
