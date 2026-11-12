"""LangChain orchestration core: a ReAct tool-calling agent with token-budgeted session memory,
wrapped by the privacy layer (mask in, de-mask out), citation validation and a PII-free audit log."""
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from openai import APIConnectionError, APITimeoutError, RateLimitError

from . import config
from .knowledge import KnowledgeVault, make_knowledge_tool
from .privacy import PIIVault, detect_pii
from .tools import CALCULATOR_TOOLS

SYSTEM_PROMPT = """You are the AfyaPlus Verification & Routing Assistant. You help members and clinicians with
insurance cover questions, claims and pre-authorisation, clinical routing and simple clinical calculations.

GROUNDING RULES
1. For any question about AfyaPlus plans, limits, percentages, exclusions, claims, pre-authorisation, routing or
   data protection, call search_knowledge_vault first and answer ONLY from what it returns.
2. Cite every policy fact with the exact [source: ...] tag of the excerpt you used.
3. If a policy question gets NO_RELEVANT_CONTEXT, or the excerpts do not contain the answer, say "The AfyaPlus
   knowledge manual does not cover this" and suggest contacting the AfyaPlus care desk. Never answer policy
   questions from general knowledge.
4. Questions about this conversation itself (for example "what did I tell you earlier?" or "which plan am I on?")
   are answered directly from the conversation history. Do not search the knowledge manual for them and do not
   say the manual does not cover them.

TOOL RULES
5. Use the calculator tools for every number you compute. Never do arithmetic yourself.
6. Never choose a medication dose, concentration or maximum. If the clinician has not provided them, ask for them.
7. For claim payouts, look up the plan's coverage percentage in the knowledge manual first, then call
   calculate_claim_payout.

PRIVACY RULES
8. Text such as [PHONE_1], [EMAIL_1], [NATIONAL_ID_1], [KRA_PIN_1] or [MEMBER_ID_1] is the user's protected
   personal data. When you need to refer to it, write the token exactly as it appears, as if it were the real
   value, and never call it a placeholder or token. Never guess, reconstruct or ask for real values.

STYLE
9. If a message describes emergency warning signs, give the routing from the clinical routing protocol first.
10. Be concise: short paragraphs or bullet points, no greetings, no filler."""

SOURCE_TAG = re.compile(r"\[source: [^\]]+\]")

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("o200k_base")      # gpt-4o family tokenizer

    def _count(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:                                   # offline fallback: ~4 characters per token
    def _count(text: str) -> int:
        return max(1, len(text) // 4)


def _text(message) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return content or ""


def count_tokens(messages) -> int:
    total = 0
    for m in messages:
        total += 4 + _count(_text(m))
        for call in getattr(m, "tool_calls", None) or []:
            total += 4 + _count(json.dumps(call.get("args", {})))
    return total


def _create_agent(llm, tools):
    """LangChain 1.x create_agent, with a fallback for older LangGraph prebuilt agents."""
    try:
        from langchain.agents import create_agent
        return create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)
    except ImportError:
        from langgraph.prebuilt import create_react_agent
        try:
            return create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
        except TypeError:
            return create_react_agent(llm, tools, state_modifier=SYSTEM_PROMPT)


@dataclass
class TurnResult:
    final_answer: str        # de-masked, shown to the authorised user only
    masked_input: str        # exactly what the model received
    masked_answer: str       # exactly what the model produced (after citation validation)
    pii_found: dict
    tools_called: list
    sources: list
    invalid_citations: list
    history_tokens: int
    latency_ms: int


class AgentSession:
    """One conversation: its own PII vault, its own message history."""

    def __init__(self, agent, session_id: str):
        self.agent = agent
        self.session_id = session_id
        self.pii = PIIVault()
        self.history = []
        self.turn = 0

    @classmethod
    def create(cls, session_id: str | None = None, vault: KnowledgeVault | None = None) -> "AgentSession":
        vault = vault or KnowledgeVault()
        llm = ChatOpenAI(model=config.CHAT_MODEL, temperature=0, timeout=config.REQUEST_TIMEOUT, max_retries=2)
        agent = _create_agent(llm, [make_knowledge_tool(vault), *CALCULATOR_TOOLS])
        return cls(agent, session_id or uuid.uuid4().hex[:8])

    def reset(self) -> None:
        self.pii, self.history, self.turn = PIIVault(), [], 0

    def ask(self, raw_text: str) -> TurnResult:
        start = time.perf_counter()
        self.turn += 1

        # 1. Privacy-masking middleware (+ defence-in-depth re-check before anything leaves the machine)
        masked_input, pii_found = self.pii.mask(raw_text)
        leftover = detect_pii(masked_input)
        if leftover:
            raise RuntimeError(f"Blocked: PII still present after masking ({leftover})")

        # 2. Token management: keep the most recent history within budget, starting on a human turn
        #    so tool-call / tool-result pairs are never split.
        history = trim_messages(self.history, max_tokens=config.HISTORY_TOKEN_BUDGET, token_counter=count_tokens,
                                strategy="last", start_on="human", include_system=False, allow_partial=False)
        prior = len(history)

        # 3. Orchestration
        try:
            result = self.agent.invoke({"messages": history + [HumanMessage(content=masked_input)]},
                                       config={"recursion_limit": config.RECURSION_LIMIT})
            messages = result["messages"]
            masked_answer = _text(messages[-1])
        except GraphRecursionError:
            masked_answer = ("I could not complete this request safely within the step limit. "
                             "Please rephrase it, or contact the AfyaPlus care desk.")
            messages = history + [HumanMessage(content=masked_input), AIMessage(content=masked_answer)]
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            masked_answer = f"The assistant is temporarily unavailable ({type(exc).__name__}). Please try again shortly."
            messages = history + [HumanMessage(content=masked_input), AIMessage(content=masked_answer)]

        new = messages[prior:]
        tools_called = [c["name"] for m in new if isinstance(m, AIMessage) for c in (m.tool_calls or [])]
        sources = sorted({tag for m in new if isinstance(m, ToolMessage) for tag in SOURCE_TAG.findall(_text(m))})

        # 4. Source-context validation: remove citations the model did not actually retrieve
        cited = SOURCE_TAG.findall(masked_answer)
        invalid = sorted({c for c in cited if c not in sources})
        for tag in invalid:
            masked_answer = masked_answer.replace(tag, "[unverified citation removed]")
        declined = "does not cover" in masked_answer.lower()
        if sources and not declined and not (set(cited) - set(invalid)):
            masked_answer += "\n\nSources consulted: " + ", ".join(sources)

        # 5. Compliance de-masking: originals are re-injected only into the final user-facing text
        final_answer = self.pii.demask(masked_answer)

        self.history = messages
        history_tokens = count_tokens(self.history)
        latency_ms = round((time.perf_counter() - start) * 1000)
        self._audit({"ts": datetime.now(timezone.utc).isoformat(), "session": self.session_id, "turn": self.turn,
                     "masked_input": masked_input, "pii_found": pii_found, "tools_called": tools_called,
                     "sources": sources, "invalid_citations": invalid, "history_tokens": history_tokens,
                     "latency_ms": latency_ms})
        return TurnResult(final_answer, masked_input, masked_answer, pii_found, tools_called, sources, invalid,
                          history_tokens, latency_ms)

    @staticmethod
    def _audit(record: dict) -> None:
        """Audit trail contains masked text only: raw PII is never written to disk."""
        config.LOG_DIR.mkdir(exist_ok=True)
        with open(config.LOG_DIR / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")