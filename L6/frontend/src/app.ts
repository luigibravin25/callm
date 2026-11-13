// orchestrazione: collega le azioni dell'utente alle chiamate al back-end e aggiorna lo stato per chat
import type { Api } from "./api/client";
import { MSG_CHAT_SPARITA, testoConferma } from "./formato";
import { datiChat, inAttesa, statoIniziale, type Stato } from "./stato";

// azioni disponibili alla vista
export interface Applicazione {
  stato: Stato;
  avvia(): Promise<void>;                 // elenca; apre la prima chat (più recente) o nessuna
  nuovaChat(): Promise<void>;             // crea, rilegge l'elenco, apre la nuova
  apri(id: number): Promise<void>;        // leggi; 404 → rilegge elenco + MSG_CHAT_SPARITA
  elimina(id: number): Promise<void>;     // conferma; no → niente chiamate
  invia(id: number): Promise<void>;       // invia la bozza della chat id
  aggiornaBozza(id: number, testo: string): void;
  chiudiErrore(id: number): void;
  riprovaElenco(): Promise<void>;
}

// conferma = window.confirm nel browser; ridisegna = aggiorna la vista dopo ogni cambio
export function creaApplicazione(
  api: Api,
  conferma: (testo: string) => boolean,
  ridisegna: () => void,
): Applicazione {
  const stato = statoIniziale();

  // rilegge l'elenco; errore nella barra (con «Riprova» se richiesto); true se riuscita
  async function rileggiElenco(conRiprova: boolean): Promise<boolean> {
    const esito = await api.elenca();
    if (!esito.ok) {
      stato.erroreBarra = { messaggio: esito.errore.messaggio, riprova: conRiprova };
      ridisegna();
      return false;
    }
    stato.chat = esito.dati;
    // l'errore dell'elenco sparisce quando l'elenco torna leggibile
    if (stato.erroreBarra?.riprova) stato.erroreBarra = null;
    ridisegna();
    return true;
  }

  // apre la prima chat dell'elenco (la più recente) oppure nessuna
  async function apriPrima(): Promise<void> {
    if (stato.chat.length) await apri(stato.chat[0].id, false);
    else { stato.aperta = null; ridisegna(); }
  }

  // ricarica = false evita un secondo giro dopo una chat sparita (404)
  async function apri(id: number, ricarica = true): Promise<void> {
    stato.aperta = id;
    stato.erroreApertura = null;
    const dati = datiChat(stato, id);
    ridisegna();
    // chat in attesa: i messaggi in memoria sono già aggiornati, nessuna lettura
    if (inAttesa(stato, id)) return;
    const esito = await api.leggi(id);
    if (esito.ok) {
      // solo i messaggi: bozza ed errore della chat restano
      dati.messaggi = esito.dati.messaggi;
      dati.caricata = true;
    } else if (esito.errore.status === 404 && stato.aperta !== id) {
      // 404 arrivato dopo che l'utente ha aperto un'altra chat: solo pulizia, la scelta resta
      stato.perChat.delete(id);
      await rileggiElenco(false);
      return;
    } else if (esito.errore.status === 404) {
      // chat eliminata altrove (un'altra scheda): rilettura dell'elenco e prima chat rimasta
      stato.perChat.delete(id);
      stato.erroreBarra = { messaggio: MSG_CHAT_SPARITA, riprova: false };
      stato.aperta = null;
      if (ricarica && await rileggiElenco(false)) {
        if (stato.chat.length) await apri(stato.chat[0].id, false);
        return;
      }
    } else if (stato.aperta === id) {
      stato.erroreApertura = esito.errore.messaggio;
    }
    ridisegna();
  }

  async function avvia(): Promise<void> {
    if (await rileggiElenco(true)) await apriPrima();
  }

  async function nuovaChat(): Promise<void> {
    const esito = await api.crea();
    if (!esito.ok) {
      stato.erroreBarra = { messaggio: esito.errore.messaggio, riprova: false };
      ridisegna();
      return;
    }
    await rileggiElenco(true);
    await apri(esito.dati.id);
  }

  async function elimina(id: number): Promise<void> {
    // chat in attesa: la risposta finirebbe in una chat cancellata
    if (inAttesa(stato, id)) return;
    const titolo = stato.chat.find((c) => c.id === id)?.titolo ?? "";
    if (!conferma(testoConferma(titolo))) return;
    const esito = await api.elimina(id);
    if (!esito.ok) {
      stato.erroreBarra = { messaggio: esito.errore.messaggio, riprova: false };
      ridisegna();
      return;
    }
    stato.perChat.delete(id);
    const eraAperta = stato.aperta === id;
    await rileggiElenco(true);
    if (eraAperta) await apriPrima();
  }

  async function invia(id: number): Promise<void> {
    const dati = datiChat(stato, id);
    const testo = dati.bozza;
    // niente testi vuoti e un solo invio alla volta per chat
    if (!testo.trim() || inAttesa(stato, id)) return;
    dati.provvisoria = testo;
    dati.bozza = "";
    dati.errore = null;
    ridisegna();
    const esito = await api.invia(id, testo);
    // l'esito va sempre alla chat di partenza, anche se ora è aperta un'altra
    dati.provvisoria = null;
    if (esito.ok) {
      dati.messaggi.push(esito.dati.domanda, esito.dati.risposta);
      ridisegna();
      // titolo e data aggiornati nell'elenco
      await rileggiElenco(true);
    } else {
      // turno tutto o niente: il back-end non ha salvato la domanda, torna nel campo
      dati.errore = esito.errore.messaggio;
      dati.bozza = testo;
      ridisegna();
    }
  }

  return {
    stato,
    avvia,
    nuovaChat,
    apri: (id) => apri(id),
    elimina,
    invia,
    aggiornaBozza: (id, testo) => { datiChat(stato, id).bozza = testo; },
    chiudiErrore: (id) => { datiChat(stato, id).errore = null; ridisegna(); },
    riprovaElenco: avvia,
  };
}
