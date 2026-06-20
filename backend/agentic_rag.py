"""
agentic_rag.py — Agentic RAG with LangGraph
Phase 5: Dynamic multi-step retrieval with self-evaluation

Graph nodes:
    1. retrieve  — ChromaDB similarity search
    2. grade     — LLM evaluates if context is sufficient
    3. generate  — produces final answer if context passes grading
    4. rewrite   — expands query and loops back to retrieve if context fails

Max 3 retrieval attempts to prevent infinite loops.

Flow:
    retrieve → grade → generate   (if context is sufficient)
                     → rewrite → retrieve (loop, max 3 times)
"""

import os
from typing import TypedDict, List, Annotated
from dotenv import load_dotenv

load_dotenv()


# ── Graph state ───────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question:       str
    query:          str          # may be rewritten across iterations
    documents:      List[str]    # retrieved chunk texts
    sources:        List[str]    # source URLs
    answer:         str
    retrieval_count: int         # tracks loop iterations


# ── Node: Retrieve ────────────────────────────────────────────────────────────
def retrieve(state: AgentState) -> AgentState:
    """
    Searches ChromaDB with the current query (original or rewritten).
    Returns top-5 chunk texts and their source URLs.
    """
    from rag import vector_store

    print(f"[AgenticRAG] Retrieve — query: '{state['query'][:60]}...'")

    results = vector_store.similarity_search_with_score(state["query"], k=5)

    documents = [doc.page_content for doc, score in results if score < 0.95]
    sources   = list(set([
        doc.metadata.get("source", "Unknown")
        for doc, score in results
        if score < 0.95
    ]))

    print(f"[AgenticRAG] Retrieved {len(documents)} chunks.")

    return {
        **state,
        "documents":      documents,
        "sources":        sources,
        "retrieval_count": state.get("retrieval_count", 0) + 1,
    }


# ── Node: Grade ───────────────────────────────────────────────────────────────
def grade(state: AgentState) -> AgentState:
    """
    LLM evaluates whether retrieved chunks contain enough information
    to answer the question. Sets answer to 'INSUFFICIENT' as a signal
    if context fails — the router checks this to decide next node.
    """
    from langchain_groq import ChatGroq

    print(f"[AgenticRAG] Grading context (attempt {state['retrieval_count']})...")

    if not state["documents"]:
        print("[AgenticRAG] No documents retrieved — marking insufficient.")
        return {**state, "answer": "INSUFFICIENT"}

    context = "\n\n".join(state["documents"][:3])  # use top 3 for grading

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=10,
        api_key=os.getenv("GROQ_API_KEY"),
    )

    response = llm.invoke(
        f"Does the following context contain enough information to answer "
        f"the question?\n\n"
        f"Question: {state['question']}\n\n"
        f"Context: {context}\n\n"
        f"Answer only YES or NO."
    )

    is_sufficient = "YES" in response.content.upper()
    print(f"[AgenticRAG] Grade: {'SUFFICIENT' if is_sufficient else 'INSUFFICIENT'}")

    return {
        **state,
        "answer": "" if is_sufficient else "INSUFFICIENT",
    }


# ── Node: Rewrite ─────────────────────────────────────────────────────────────
def rewrite(state: AgentState) -> AgentState:
    """
    LLM rewrites the query to be more specific when initial retrieval
    didn't return sufficient context. Expands with financial terminology.
    """
    from langchain_groq import ChatGroq

    print(f"[AgenticRAG] Rewriting query for better retrieval...")

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=100,
        api_key=os.getenv("GROQ_API_KEY"),
    )

    response = llm.invoke(
        f"Rewrite this financial analysis question to be more specific "
        f"and include relevant financial terms to improve document retrieval.\n\n"
        f"Original question: {state['question']}\n\n"
        f"Rewritten question (one sentence only):"
    )

    new_query = response.content.strip()
    print(f"[AgenticRAG] Rewritten query: '{new_query[:80]}...'")

    return {**state, "query": new_query}


# ── Node: Generate ────────────────────────────────────────────────────────────
def generate(state: AgentState) -> AgentState:
    """
    Generates the final answer using retrieved context.
    Called only when grade() determines context is sufficient.
    """
    from langchain_groq import ChatGroq

    print(f"[AgenticRAG] Generating answer...")

    context = "\n\n".join(state["documents"])

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.3,
        max_tokens=500,
        api_key=os.getenv("GROQ_API_KEY"),
    )

    response = llm.invoke(
        f"""You are a financial analyst AI.

Rules:
- Use ONLY the given context
- If multiple companies are present, compare them clearly
- Use bullet points and separate sections per company
- Give a final conclusion

Context:
{context}

Question:
{state['question']}
"""
    )

    print(f"[AgenticRAG] Answer generated.")

    return {**state, "answer": response.content}


# ── Router: after grade ───────────────────────────────────────────────────────
def route_after_grade(state: AgentState) -> str:
    """
    Decides next node after grading:
    - If context sufficient → generate
    - If insufficient and under retry limit → rewrite
    - If insufficient and over retry limit → generate anyway (best effort)
    """
    if state["answer"] != "INSUFFICIENT":
        return "generate"

    if state.get("retrieval_count", 0) >= 3:
        print("[AgenticRAG] Max retries reached — generating best-effort answer.")
        return "generate"

    return "rewrite"


# ── Build graph ───────────────────────────────────────────────────────────────
def build_graph():
    """
    Builds and compiles the LangGraph StateGraph.
    Called once and reused for all queries.
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError(
            "langgraph not installed. Run: pip install langgraph"
        )

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade",    grade)
    graph.add_node("rewrite",  rewrite)
    graph.add_node("generate", generate)

    # Entry point
    graph.set_entry_point("retrieve")

    # Edges
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        route_after_grade,
        {
            "generate": "generate",
            "rewrite":  "rewrite",
        }
    )
    graph.add_edge("rewrite",  "retrieve")   # loop back
    graph.add_edge("generate", END)

    return graph.compile()


# ── Singleton graph instance ──────────────────────────────────────────────────
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Public API ────────────────────────────────────────────────────────────────
def agentic_query(question: str) -> tuple[str, list[str], int]:
    """
    Runs the agentic RAG pipeline for a given question.

    Returns:
        (answer: str, sources: list[str], retrieval_attempts: int)
    """
    from rag import initialize_components
    initialize_components()

    graph = get_graph()

    initial_state: AgentState = {
        "question":       question,
        "query":          question,
        "documents":      [],
        "sources":        [],
        "answer":         "",
        "retrieval_count": 0,
    }

    final_state = graph.invoke(initial_state)

    answer   = final_state.get("answer", "I don't know")
    sources  = final_state.get("sources", [])
    attempts = final_state.get("retrieval_count", 1)

    if not answer or answer == "INSUFFICIENT":
        answer = "I don't have enough information in the indexed sources to answer this question."

    return answer, sources, attempts