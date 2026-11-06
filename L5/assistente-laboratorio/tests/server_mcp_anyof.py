"""Server MCP di prova per i test dell'adattatore: un tool con schema valido e uno con anyOf."""
# FastMCP: la libreria che crea un server MCP con pochi decoratori
from fastmcp import FastMCP

# server MCP minimo chiamato "prova": lo avvia il test dell'adattatore come processo a parte
mcp = FastMCP("prova")


# tool con schema valido: l'argomento ha un solo "type" (stringa), l'adattatore deve tenerlo
@mcp.tool
def buono(x: str) -> str:
    """Restituisce x."""
    return x  # restituisce l'argomento cosi' com'e'


# tool con schema da scartare: "int | None" diventa "anyOf" nello schema JSON,
# che il template di gemma in LM Studio non accetta (risponde HTTP 400)
@mcp.tool
def cattivo(x: int | None = None) -> str:
    """Schema con anyOf: va scartato dall'adattatore."""
    return str(x)  # restituisce l'argomento come testo


# avvio diretto: il server parla con il client su stdin/stdout, senza il banner iniziale
if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
