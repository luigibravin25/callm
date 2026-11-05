"""Server MCP di prova per i test dell'adattatore: un tool con schema valido e uno con anyOf."""
from fastmcp import FastMCP

mcp = FastMCP("prova")


@mcp.tool
def buono(x: str) -> str:
    """Restituisce x."""
    return x


@mcp.tool
def cattivo(x: int | None = None) -> str:
    """Schema con anyOf: va scartato dall'adattatore."""
    return str(x)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
