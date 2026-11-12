"""AfyaPlus RAG agent entry point.

  python main.py --build-index        rebuild the knowledge index and print chunk statistics
  python main.py --search "query"     show raw retrieval scores (useful for tuning the cut-off)
  python main.py --demo               scripted 5-turn demo, saved to sample_outputs/demo_transcript.md
  python main.py                      interactive chat (add --show-masked to see what the model receives)
"""
import argparse

from openai import AuthenticationError

from afyaplus import config
from afyaplus.agent import AgentSession
from afyaplus.knowledge import KnowledgeVault, build_index, source_tag

DEMO_TURNS = [
    "Hello, I'm Wanjiku, a Silver plan member. You can reach me on 0712 345 678 or wanjiku.m@example.co.ke. "
    "Do I need pre-authorisation before an MRI scan?",
    "The MRI bill came to KES 48,000 and I have KES 60,000 left on my outpatient limit. "
    "How much will AfyaPlus pay and how much do I pay?",
    "Different question: my father weighs 70 kg. His doctor prescribed 10 mg/kg of a liquid medicine that comes as "
    "50 mg per mL, with a maximum single dose of 600 mg. What volume is one dose?",
    "Who is the CEO of AfyaPlus?",
    "Which phone number and email did I give you at the start?",
]


def print_turn(i, raw, r, show_masked=True):
    print(f"\n{'=' * 78}\nTurn {i}")
    print(f"USER          : {raw}")
    if show_masked:
        print(f"SENT TO MODEL : {r.masked_input}")
    print(f"PII masked    : {r.pii_found or 'none'}")
    print(f"Tools called  : {', '.join(r.tools_called) or 'none'}")
    print(f"Sources       : {', '.join(r.sources) or 'none'}")
    print(f"History       : {r.history_tokens} tokens | latency {r.latency_ms} ms")
    print(f"\nASSISTANT:\n{r.final_answer}")


def run_demo():
    session = AgentSession.create(session_id="demo")
    lines = ["# Demo transcript (fictional test data)", "",
             f"Model: `{config.CHAT_MODEL}` | Embeddings: `{config.EMBED_MODEL}` | "
             f"Chunks: {session.agent and 'see storage/manifest.json'}", ""]
    for i, raw in enumerate(DEMO_TURNS, 1):
        r = session.ask(raw)
        print_turn(i, raw, r)
        lines += [f"## Turn {i}", "", f"**User (raw):** {raw}", "",
                  f"**Sent to model (masked):** {r.masked_input}", "",
                  f"**PII masked:** {r.pii_found or 'none'}  ", f"**Tools called:** {', '.join(r.tools_called) or 'none'}  ",
                  f"**Sources retrieved:** {', '.join(r.sources) or 'none'}  ",
                  f"**Invalid citations removed:** {', '.join(r.invalid_citations) or 'none'}  ",
                  f"**History tokens:** {r.history_tokens} | **Latency:** {r.latency_ms} ms", "",
                  "**Model output (still masked):**", "", "```", r.masked_answer, "```", "",
                  "**Final answer shown to user (de-masked):**", "", r.final_answer, ""]
    config.SAMPLE_DIR.mkdir(exist_ok=True)
    (config.SAMPLE_DIR / "demo_transcript.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved {config.SAMPLE_DIR / 'demo_transcript.md'}")


def run_chat(show_masked: bool):
    session = AgentSession.create()
    print("AfyaPlus assistant ready. Type 'exit' to quit or '/reset' to start a new conversation.")
    turn = 0
    while True:
        try:
            raw = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if raw.lower() in {"exit", "quit"}:
            break
        if raw == "/reset":
            session.reset()
            turn = 0
            print("Conversation cleared.")
            continue
        if raw:
            turn += 1
            print_turn(turn, raw, session.ask(raw), show_masked)


def main():
    parser = argparse.ArgumentParser(description="AfyaPlus enterprise RAG agent")
    parser.add_argument("--build-index", action="store_true", help="force a rebuild of the vector index")
    parser.add_argument("--search", metavar="QUERY", help="show raw retrieval scores for a query")
    parser.add_argument("--demo", action="store_true", help="run the scripted multi-turn demo")
    parser.add_argument("--show-masked", action="store_true", help="in chat, show the masked text sent to the model")
    args = parser.parse_args()
    try:
        if args.build_index:
            _, manifest = build_index(force=True)
            print("Index rebuilt:", manifest)
        elif args.search:
            vault = KnowledgeVault()
            kept, results = vault.search(args.search)
            for r in results:
                flag = "KEPT" if r in kept else "below cut-off"
                print(f"{r.score:.3f}  {flag:<14} {source_tag(r)}  {r.node.get_content()[:90]!r}")
        elif args.demo:
            run_demo()
        else:
            run_chat(args.show_masked)
    except AuthenticationError:
        print("OpenAI rejected the API key. Check OPENAI_API_KEY in your .env file.")


if __name__ == "__main__":
    main()