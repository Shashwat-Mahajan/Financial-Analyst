"""
guardrails.py — NeMo Guardrails integration for Financial Analyst RAG
Phase 3: Input + Output rails

Input rail  — blocks off-topic queries (non-financial)
Output rail — flags responses that may contain hallucinated financial data

Fix: Uses engine=langchain with explicit ChatGroq LLM passed to LLMRails,
     and registers Python functions as Colang actions so rails.co flows
     actually execute through NeMo's runtime.
"""

import os
import re
from pathlib import Path
from typing import Optional

# ── Financial topic keywords ──────────────────────────────────────────────────
FINANCIAL_KEYWORDS = {
    # Companies and markets
    "revenue", "earnings", "profit", "loss", "stock", "share", "market",
    "company", "companies", "corporate", "business", "enterprise",
    "nasdaq", "nyse", "s&p", "dow", "index", "portfolio",

    # Financial metrics
    "ebitda", "eps", "pe ratio", "market cap", "valuation", "dividend",
    "yield", "return", "roi", "roe", "debt", "equity", "asset", "liability",
    "cash flow", "balance sheet", "income statement", "quarterly", "annual",
    "fiscal", "q1", "q2", "q3", "q4", "guidance", "forecast", "outlook",

    # Actions and analysis
    "invest", "investment", "analyst", "analysis", "financial", "finance",
    "acquisition", "merger", "ipo", "buyback", "growth",
    "decline", "increase", "decrease", "report", "results", "performance",

    # Common company names
    "apple", "microsoft", "google", "alphabet", "amazon", "meta", "tesla",
    "nvidia", "netflix", "samsung", "jpmorgan", "goldman", "berkshire",
}

BLOCKED_TOPICS = {
    "poem", "poetry", "song", "lyrics", "recipe", "cook", "sport",
    "football", "cricket", "movie", "film", "actor", "actress",
    "celebrity", "music", "weather", "travel", "country capital",
    "joke", "story", "fiction", "history", "geography",
}

_REJECTION_MESSAGE = (
    "I'm a financial analyst AI and can only answer questions about "
    "companies, stocks, earnings, revenue, financial metrics, and "
    "market analysis. Please ask a finance-related question."
)

_HALLUCINATION_PATTERNS = [
    r'\$[\d,]+(?:\.\d+)?(?:\s*(?:billion|million|trillion))?',  # dollar amounts
    r'\d+(?:\.\d+)?%',                                           # percentages
    r'(?:Q[1-4]|FY)\s*\d{4}',                                   # fiscal periods
    r'\d+(?:\.\d+)?\s*(?:billion|million|trillion)',             # large numbers
]


# ── Input Rail — Python logic ─────────────────────────────────────────────────
def check_financial_topic(query: str) -> bool:
    """
    Colang action: checks if a query is financial.
    Returns True (allow) or False (block).

    NOTE: Returns bool so Colang 'if not $is_financial' works directly.
    The rejection message is handled by the 'bot refuse off topic' definition
    in rails.co — NeMo sends that string automatically when the flow stops.
    """
    query_lower = query.lower()

    # Block explicit non-financial topics first
    for blocked in BLOCKED_TOPICS:
        if blocked in query_lower:
            return False

    # Allow if any financial keyword matches
    for keyword in FINANCIAL_KEYWORDS:
        if keyword in query_lower:
            return True

    # Fallback: LLM classification for edge cases
    return _llm_classify_topic(query)


def _llm_classify_topic(query: str) -> bool:
    """
    Uses Groq LLM as fallback classifier when keyword match is inconclusive.
    Returns True (financial) or False (off-topic).
    Fails open — allows query if the classifier itself errors.
    """
    try:
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0,
            max_tokens=10,
            api_key=os.getenv("GROQ_API_KEY"),
        )
        response = llm.invoke(
            "Is this question about financial analysis, companies, stocks, "
            "or business metrics? Answer only YES or NO.\n\n"
            f"Question: {query}"
        )
        return "YES" in response.content.upper()
    except Exception as e:
        print(f"[Guardrails] LLM classification failed: {e} — allowing query")
        return True  # fail open


# ── Output Rail — Python logic ────────────────────────────────────────────────
def check_citation(response: str) -> bool:
    """
    Colang action: checks if the bot response contains ungrounded financial claims.
    Returns True (citation OK / no risky claims) or False (flag it).

    Colang flow does: if not $has_citation → bot add citation warning
    So False here triggers the warning in rails.co.
    """
    if not response or response.strip() == "I don't know":
        return True  # nothing to flag

    has_specific_claims = any(
        re.search(pattern, response, re.IGNORECASE)
        for pattern in _HALLUCINATION_PATTERNS
    )

    # Flag if specific financial figures present — conservative check
    return not has_specific_claims


def check_output_citation(answer: str, sources: list[str]) -> tuple[str, bool]:
    """
    Pure-Python output rail used in fallback mode (when NeMo is unavailable).
    Appends a warning string directly to the answer.

    Returns:
        (final_answer, was_flagged)
    """
    if not answer or answer.strip() == "I don't know":
        return answer, False

    if not sources:
        warning = (
            "\n\n⚠️ **Verification Notice:** This response was generated "
            "without retrieved source documents. Please verify this information "
            "independently before making any financial decisions."
        )
        return answer + warning, True

    has_specific_claims = any(
        re.search(pattern, answer, re.IGNORECASE)
        for pattern in _HALLUCINATION_PATTERNS
    )

    if has_specific_claims and len(sources) < 1:
        warning = (
            "\n\n⚠️ **Verification Notice:** This response contains specific "
            "financial figures. Please cross-reference with the cited sources "
            "before making any financial decisions."
        )
        return answer + warning, True

    return answer, False


# ── NeMo Guardrails wrapper ───────────────────────────────────────────────────
class FinancialGuardrails:
    """
    Main guardrails class that wraps the RAG pipeline.

    Initialization order:
    1. Build ChatGroq LLM explicitly (NeMo needs this passed in — 'engine: groq'
       is not a valid NeMo engine; only 'openai', 'nemollm', 'langchain' are).
    2. Load RailsConfig from config/ (reads config.yml + rails.co).
    3. Pass llm= to LLMRails so NeMo uses it for Colang flow execution.
    4. Register check_financial_topic and check_citation as named actions
       so rails.co 'execute' calls resolve to these Python functions.

    Falls back to pure-Python rails if NeMo init fails for any reason.
    """

    def __init__(self):
        self.config_path = Path(__file__).parent / "config"
        self._rails = None
        self._init_nemo()

    def _init_nemo(self):
        try:
            from nemoguardrails import RailsConfig, LLMRails
            from langchain_groq import ChatGroq

            print("[Guardrails] Import successful")

            # Build LLM explicitly — NeMo cannot auto-build Groq from config.yml
            llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                temperature=0,
                api_key=os.getenv("GROQ_API_KEY"),
            )

            # Load Colang config (reads config.yml + rails.co from config/)
            config = RailsConfig.from_path(str(self.config_path))

            # Pass llm= so NeMo's runtime uses it for flow execution
            self._rails = LLMRails(config, llm=llm)

            # Register Python functions as named Colang actions
            # These resolve 'execute check_financial_topic' and 'execute check_citation'
            # in rails.co at runtime
            self._rails.register_action(
                check_financial_topic, name="check_financial_topic"
            )
            self._rails.register_action(
                check_citation, name="check_citation"
            )

            print("[Guardrails] NeMo Guardrails initialized successfully.")

        except ImportError as e:
            print("[Guardrails] NeMo package missing:", repr(e))
            self._rails = None

        except Exception as e:
            print("[Guardrails] NeMo initialization error:", repr(e))
            self._rails = None

    # ── Input rail ────────────────────────────────────────────────────────────
    async def apply_input_rail(self, query: str) -> tuple[bool, Optional[str]]:
        if self._rails is not None:
            try:
                result = await self._rails.generate_async(
                    messages=[{"role": "user", "content": query}]
                )
                # extract text if result is a dict
                if isinstance(result, dict):
                    result_text = result.get("content", "")
                else:
                    result_text = str(result)

                blocked = (
                        "financial analyst AI" in result_text
                        or "finance-related" in result_text
                        or "market analysis" in result_text
                )
                if blocked:
                    print(f"[Guardrails] Input blocked (NeMo): '{query[:50]}...'")
                    return False, result_text
                return True, None

            except Exception as e:
                print(f"[Guardrails] NeMo input rail failed, falling back: {e}")

        # Pure-Python fallback
        is_allowed = check_financial_topic(query)
        if not is_allowed:
            print(f"[Guardrails] Input blocked (Python): '{query[:50]}...'")
            return False, _REJECTION_MESSAGE
        return True, None

    # ── Output rail ───────────────────────────────────────────────────────────
    def apply_output_rail(
        self, answer: str, sources: list[str]
    ) -> tuple[str, bool]:
        """
        Apply output guardrail to answer.

        NeMo's output flow runs check_citation on the bot_message internally
        during generate_async, so by the time we have an answer here, NeMo has
        already appended the citation warning via 'bot add citation warning'.

        This method handles the sources-empty case (which NeMo can't check
        since it doesn't know about ChromaDB results) and is also the fallback
        when NeMo is unavailable.

        Returns:
            (final_answer: str, was_flagged: bool)
        """
        final_answer, flagged = check_output_citation(answer, sources)
        if flagged:
            print("[Guardrails] Output flagged for potential hallucination.")
        return final_answer, flagged

    # ── Full pipeline ─────────────────────────────────────────────────────────
    async def process_query(
        self,
        query: str,
        generate_fn,
    ) -> tuple[str, list[str], bool]:
        """
        Full guardrails pipeline:
            1. Input rail  — block off-topic queries
            2. RAG generate — call generate_fn(query) → (answer, sources)
            3. Output rail — flag ungrounded financial claims

        Args:
            query:       user question string
            generate_fn: async or sync callable → (answer: str, sources: list[str])

        Returns:
            (final_answer: str, sources: list[str], was_flagged: bool)
        """
        # Step 1 — Input rail
        is_allowed, rejection = await self.apply_input_rail(query)
        if not is_allowed:
            return rejection, [], False

        # Step 2 — Generate answer via RAG pipeline
        try:
            result = generate_fn(query)
            # Support both sync and async generate_fn
            if hasattr(result, "__await__"):
                answer, sources = await result
            else:
                answer, sources = result
        except Exception as e:
            return f"Error generating answer: {str(e)}", [], False

        # Step 3 — Output rail
        final_answer, flagged = self.apply_output_rail(answer, sources)

        return final_answer, sources, flagged


# ── Singleton instance ────────────────────────────────────────────────────────
_guardrails_instance: Optional[FinancialGuardrails] = None


def get_guardrails() -> FinancialGuardrails:
    """Returns singleton FinancialGuardrails instance (created on first call)."""
    global _guardrails_instance
    if _guardrails_instance is None:
        _guardrails_instance = FinancialGuardrails()
    return _guardrails_instance