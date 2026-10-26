from langchain_core.messages import HumanMessage

from app.graph import build_graph


def main(input_fn=input, output_fn=print) -> None:
    grafo = build_graph()
    cronologia = []  # solo in memoria, mai su disco
    output_fn("Scrivi un messaggio ('exit' per uscire).")
    while True:
        try:
            testo = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if testo.lower() == "exit":
            break
        if not testo:
            continue
        cronologia.append(HumanMessage(testo))
        out = grafo.invoke({"messages": cronologia, "steps": 0})
        cronologia = out["messages"]
        output_fn(cronologia[-1].content)


if __name__ == "__main__":
    main()
