"""Prova reale del server MCP della ricerca: lo avvia in stdio e lo interroga come farà l'agente.

Uso, da L8\\ricerca (Qdrant e LM Studio accesi, $env:EMBEDDING_MODEL impostata):
  & ..\\venv\\Scripts\\python.exe prova_mcp.py --discovery
  & ..\\venv\\Scripts\\python.exe prova_mcp.py "domanda" [--capitolo NOME] [-k N]
Lo stdout mostra discovery e risultati; le righe di log del server arrivano su stderr.
"""
# librerie standard: argomenti, codice asincrono, JSON, variabili d'ambiente, interprete corrente
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# client MCP e trasporto stdio (il server è un processo figlio)
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

# cartella della ricerca: il server si avvia da qui per trovare i pacchetti app e mcp_ricerca
CARTELLA_RICERCA = Path(__file__).resolve().parent


def leggi_argomenti(argv: list[str] | None) -> argparse.Namespace:
    """Discovery oppure domanda con capitolo e top_k facoltativi."""
    parser = argparse.ArgumentParser(description="Prova reale del server MCP della ricerca (stdio)")
    parser.add_argument("domanda", nargs="?", help="la domanda per search_documents, tra virgolette")
    parser.add_argument("--discovery", action="store_true", help="elenca tool e resource del server")
    parser.add_argument("--capitolo", default="", help="filtro per capitolo (vuoto = nessun filtro)")
    parser.add_argument("-k", type=int, default=5, help="top_k passato al tool (predefinito 5)")
    argomenti = parser.parse_args(argv)
    # serve almeno una delle due azioni
    if not argomenti.discovery and argomenti.domanda is None:
        parser.error("indicare una domanda oppure --discovery")
    return argomenti


def trasporto() -> StdioTransport:
    """Processo del server con lo stesso interprete e le variabili d'ambiente correnti."""
    return StdioTransport(command=sys.executable, args=["-m", "mcp_ricerca.server"],
                          env=dict(os.environ), cwd=str(CARTELLA_RICERCA))


async def discovery(client: Client) -> None:
    """Stampa tool (descrizione, schema di ingresso) e resource (con il contenuto)."""
    for tool in await client.list_tools():
        print(f"tool: {tool.name}\ndescrizione: {tool.description}")
        print("schema di ingresso:", json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
    for risorsa in await client.list_resources():
        contenuto = await client.read_resource(str(risorsa.uri))
        print(f"resource: {risorsa.uri} ({risorsa.mimeType})\n{contenuto[0].text}")


async def chiama(client: Client, domanda: str, capitolo: str, k: int) -> None:
    """Chiama search_documents e stampa il risultato strutturato, oppure l'errore del tool."""
    argomenti = {"query": domanda, "top_k": k, "capitolo": capitolo}
    print("chiamata: search_documents", json.dumps(argomenti, ensure_ascii=False))
    try:
        risultato = await client.call_tool("search_documents", argomenti)
    except ToolError as errore:
        # errore previsto del tool: lo vede così anche il modello
        print(f"errore del tool: {errore}")
        return
    print(json.dumps(risultato.structured_content, ensure_ascii=False, indent=2))


async def esegui(argomenti: argparse.Namespace) -> None:
    # una sola connessione: il server vive quanto il blocco async with
    async with Client(trasporto()) as client:
        if argomenti.discovery:
            await discovery(client)
        if argomenti.domanda is not None:
            await chiama(client, argomenti.domanda, argomenti.capitolo, argomenti.k)


def main(argv: list[str] | None = None) -> None:
    # su Windows lo stdout reindirizzato su file usa la codifica locale: le evidenze restano in UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(esegui(leggi_argomenti(argv)))


if __name__ == "__main__":
    main()
