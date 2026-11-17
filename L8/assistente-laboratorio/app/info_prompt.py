"""Tipi dei prompt pubblicati dal server MCP (prompts/list).

Modulo senza dipendenze da MCP o LangChain: lo usano l'adattatore (che li crea), i comandi e la
CLI client (che li ricostruisce dal JSON di GET /prompts senza caricare il client MCP).
"""
# libreria standard: classi di dati immutabili
from dataclasses import dataclass


# argomento di un prompt come lo pubblica prompts/list: nome e se e' obbligatorio
@dataclass(frozen=True)
class InfoArgomento:
    nome: str
    obbligatorio: bool


# prompt pubblicato dal server: la CLI usa questo tipo, non gli oggetti di MCP
@dataclass(frozen=True)
class InfoPrompt:
    nome: str
    descrizione: str
    argomenti: tuple[InfoArgomento, ...]
