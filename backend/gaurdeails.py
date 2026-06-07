"""
guardrails.py — NeMo Guardrails integration for Financial Analyst RAG
Phase 3: Input + Output rails

Input rail  — blocks off-topic queries (non-financial)
Output rail — flags responses that may contain hallucinated financial data
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
    "acquisition", "merger", "ipo", "buyback", "acquisition", "growth",
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


# ── Input Rail ────────────────────────────────────────────────────────────────
def check_financial_topic(query: str) -> tuple[bool, Optional[str]]:
    """
    Checks if a query is related to financial analysis.

    Returns:
        (is_financial, rejection_message)
        If is_financial=True  → proceed normally
        If is_financial=False → return rejection_message to user
    """
    query_lower = query.lower()

    # Check for explicit blocked topics first
    for blocked in BLOCKED_TOPICS:
        if blocked in query_lower:
            return False, (
                "I'm a financial analyst AI and can only answer questions about "
                "companies, stocks, earnings, revenue, financial metrics, and "
                "market analysis. Please ask a finance-related question."
            )

    # Check for financial keywords
    for keyword in FINANCIAL_KEYWORDS:
        if keyword in query_lower:
            return True, None

    # If no financial keywords found, use LLM to classify
    # (fallback for edge cases)
    return _llm_classify_topic(query)


def _llm_classify_topic(query: str) -> tuple[bool, Optional[str]]:
    """
    Uses Groq LLM as fallback classifier for edge cases.
    Only called when keyword matching is inconclusive.
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
            f"Is this question about financial analysis, companies, stocks, "
            f"or business metrics? Answer only YES or NO.\n\nQuestion: {query}"
        )
        is_financial = "YES" in response.content.upper()
        if not is_financial:
            return False, (
                "I'm a financial analyst AI and can only answer questions about "
                "companies, stocks, earnings, revenue, and financial metrics. "
                "Please ask a finance-related question."
            )
        return True, None
    except Exception as e:
        print(f"[Guardrails] LLM classification failed: {e} — allowing query")
        return True, None  # Fail open — allow if classifier fails


# ── Output Rail ───────────────────────────────────────────────────────────────
def check_output_citation(answer: str, sources: list[str]) -> tuple[str, bool]:
    """
    Checks if the LLM response is grounded in retrieved sources.

    Returns:
        (final_answer, was_flagged)
        If well-cited  → returns answer unchanged, was_flagged=False
        If potentially hallucinated → appends warning, was_flagged=True
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

    # Check for specific financial claims that need citation
    hallucination_patterns = [
        r'\$[\d,]+(?:\.\d+)?(?:\s*(?:billion|million|trillion))?',  # dollar amounts
        r'\d+(?:\.\d+)?%',                                           # percentages
        r'(?:Q[1-4]|FY)\s*\d{4}',                                   # fiscal periods
        r'\d+(?:\.\d+)?\s*(?:billion|million|trillion)',             # large numbers
    ]

    has_specific_claims = any(
        re.search(pattern, answer, re.IGNORECASE)
        for pattern in hallucination_patterns
    )

    # If answer has specific financial figures, verify sources exist
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
    Applies input and output rails to every query.
    """

    def __init__(self):
        self.config_path = Path(__file__).parent / "config"
        self._rails = None
        self._init_nemo()

    def _init_nemo(self):
        """Initialize NeMo Guardrails — falls back gracefully if unavailable."""
        try:
            from nemoguardrails import RailsConfig, LLMRails
            config      = RailsConfig.from_path(str(self.config_path))
            self._rails = LLMRails(config)
            print("[Guardrails] NeMo Guardrails initialized successfully.")
        except ImportError:
            print("[Guardrails] NeMo not installed — using custom rails only.")
            self._rails = None
        except Exception as e:
            print(f"[Guardrails] NeMo init failed: {e} — using custom rails only.")
            self._rails = None

    def apply_input_rail(self, query: str) -> tuple[bool, Optional[str]]:
        """
        Apply input guardrail to query.
        Returns (allowed, rejection_message)
        """
        is_allowed, rejection = check_financial_topic(query)
        if not is_allowed:
            print(f"[Guardrails] Input blocked: '{query[:50]}...'")
        return is_allowed, rejection

    def apply_output_rail(
        self, answer: str, sources: list[str]
    ) -> tuple[str, bool]:
        """
        Apply output guardrail to answer.
        Returns (final_answer, was_flagged)
        """
        final_answer, flagged = check_output_citation(answer, sources)
        if flagged:
            print("[Guardrails] Output flagged for potential hallucination.")
        return final_answer, flagged

    def process_query(
        self,
        query: str,
        generate_fn,
    ) -> tuple[str, list[str], bool]:
        """
        Full guardrails pipeline:
        1. Check input topic
        2. Generate answer if allowed
        3. Check output for hallucination

        Args:
            query:       user question
            generate_fn: function that takes query and returns (answer, sources)

        Returns:
            (final_answer, sources, was_flagged)
        """
        # Step 1 — Input rail
        is_allowed, rejection = self.apply_input_rail(query)
        if not is_allowed:
            return rejection, [], False

        # Step 2 — Generate answer
        try:
            answer, sources = generate_fn(query)
        except Exception as e:
            return f"Error generating answer: {str(e)}", [], False

        # Step 3 — Output rail
        final_answer, flagged = self.apply_output_rail(answer, sources)

        return final_answer, sources, flagged


# ── Singleton instance ────────────────────────────────────────────────────────
_guardrails_instance: Optional[FinancialGuardrails] = None


def get_guardrails() -> FinancialGuardrails:
    """Returns singleton guardrails instance."""
    global _guardrails_instance
    if _guardrails_instance is None:
        _guardrails_instance = FinancialGuardrails()
    return _guardrails_instance