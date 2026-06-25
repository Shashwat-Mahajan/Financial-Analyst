"""
agentic_rag.py — True Agentic RAG with LangGraph
Phase 5: Agent autonomously decides which tools to use

Graph flow:
    search_chromadb → grade_context
        → SUFFICIENT  → generate_answer → END
        → INSUFFICIENT → web_search_urls → fetch_live_url
                          → search_chromadb (loop, max 2 web fetches)
                          → MAX REACHED → generate_answer → END

Fixes:
    - candidate_urls in AgentState (was dropped between nodes)
    - web_fetch_count increments correctly
    - No hardcoded URLs — DuckDuckGo HTML search finds real URLs
    - Async web search runs in thread to avoid blocking event loop
"""

import os
import httpx
from typing import TypedDict, List
from dotenv import load_dotenv
from urllib.parse import unquote, urlparse, parse_qs

load_dotenv()

MAX_WEB_FETCHES = 2

# Financial news domains to prioritize
TRUSTED_DOMAINS = [
    "cnbc.com", "reuters.com", "bloomberg.com",
    "finance.yahoo.com", "marketwatch.com", "wsj.com",
    "ft.com", "businessinsider.com", "seekingalpha.com",
]


# ── Agent State ───────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question:        str
    query:           str
    documents:       List[str]
    sources:         List[str]
    answer:          str
    web_fetch_count: int
    fetched_urls:    List[str]
    candidate_urls:  List[str]


# ── Tool 1: Search ChromaDB ───────────────────────────────────────────────────
def search_chromadb(state: AgentState) -> AgentState:
    from rag import vector_store

    print(f"[AgenticRAG] Searching ChromaDB: '{state['query'][:60]}...'")

    results = vector_store.similarity_search_with_score(state["query"], k=10)

    filtered = [(doc, score) for doc, score in results if score < 1.5]
    if not filtered and results:
        print(f"[AgenticRAG] Relaxing threshold — using top 3 chunks.")
        filtered = results[:3]

    documents = [doc.page_content for doc, score in filtered]
    sources   = list(set([
        doc.metadata.get("source", "Unknown")
        for doc, score in filtered
    ]))

    print(f"[AgenticRAG] Found {len(documents)} chunks in ChromaDB.")
    return {**state, "documents": documents, "sources": sources}


# ── Web Search Helper (sync, runs in thread) ──────────────────────────────────
def _duckduckgo_search(query: str, fetched_urls: list) -> list:
    """
    Searches DuckDuckGo HTML for relevant financial URLs.
    Runs synchronously — called via asyncio.to_thread in the node.
    No API key required.
    """
    try:
        search_query = f"{query} earnings revenue financial results"

        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": search_query},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            follow_redirects=True,
        )

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")

        urls = []

        # Extract from result links (DuckDuckGo encodes real URL in uddg param)
        for a in soup.select(".result__a")[:10]:
            href = a.get("href", "")
            if "uddg=" in href:
                parsed  = parse_qs(urlparse(href).query)
                real_url = unquote(parsed.get("uddg", [""])[0])
                if (real_url.startswith("http")
                        and real_url not in fetched_urls
                        and any(domain in real_url for domain in TRUSTED_DOMAINS)):
                    urls.append(real_url)

        # Also try direct result URLs
        for result in soup.select(".result__url")[:10]:
            href = result.get_text(strip=True)
            if href and not href.startswith("http"):
                href = "https://" + href
            if (href.startswith("http")
                    and href not in fetched_urls
                    and href not in urls
                    and any(domain in href for domain in TRUSTED_DOMAINS)):
                urls.append(href)

        print(f"[AgenticRAG] DuckDuckGo returned {len(urls)} trusted URLs.")
        return urls[:3]

    except Exception as e:
        print(f"[AgenticRAG] DuckDuckGo search failed: {e}")
        return []


# ── Tool 2: Web Search for URLs ───────────────────────────────────────────────
def web_search_urls(state: AgentState) -> AgentState:
    """Finds relevant financial URLs via DuckDuckGo — no API key needed."""
    import asyncio

    print(f"[AgenticRAG] Searching web for: '{state['question'][:60]}'...")

    fetched_urls = state.get("fetched_urls", [])

    # Run sync HTTP call in thread to avoid blocking event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_duckduckgo_search, state["question"], fetched_urls)
                urls = future.result(timeout=20)
        else:
            urls = asyncio.run(
                asyncio.to_thread(_duckduckgo_search, state["question"], fetched_urls)
            )
    except Exception as e:
        print(f"[AgenticRAG] Web search error: {e}")
        urls = []

    print(f"[AgenticRAG] Found {len(urls)} candidate URLs.")
    return {**state, "candidate_urls": urls}


# ── Tool 3: Fetch and Ingest Live URL ─────────────────────────────────────────
def fetch_live_url(state: AgentState) -> AgentState:
    """
    Fetches a live URL, ingests it into ChromaDB, backs up to S3.
    This is what makes the agent truly agentic — it autonomously
    expands its knowledge base when existing data is insufficient.
    """
    candidate_urls = state.get("candidate_urls", [])
    fetched_urls   = state.get("fetched_urls", [])

    url_to_fetch = next(
        (u for u in candidate_urls if u not in fetched_urls),
        None
    )

    if not url_to_fetch:
        print(f"[AgenticRAG] No new URLs to fetch — incrementing counter.")
        return {
            **state,
            "web_fetch_count": state.get("web_fetch_count", 0) + 1,
        }

    print(f"[AgenticRAG] Fetching live URL: {url_to_fetch}")

    try:
        from rag import load_sources, split_documents, vector_store, upload_chroma_to_s3
        from uuid import uuid4

        docs = load_sources([url_to_fetch])

        if not docs:
            print(f"[AgenticRAG] Could not fetch content from {url_to_fetch}")
            return {
                **state,
                "fetched_urls":    fetched_urls + [url_to_fetch],
                "web_fetch_count": state.get("web_fetch_count", 0) + 1,
            }

        chunks = split_documents(docs)
        ids    = [str(uuid4()) for _ in chunks]
        vector_store.add_documents(chunks, ids=ids)
        upload_chroma_to_s3()

        print(f"[AgenticRAG] ✅ Ingested {len(chunks)} chunks from {url_to_fetch}")

        return {
            **state,
            "fetched_urls":    fetched_urls + [url_to_fetch],
            "web_fetch_count": state.get("web_fetch_count", 0) + 1,
            "sources":         list(set(state.get("sources", []) + [url_to_fetch])),
        }

    except Exception as e:
        print(f"[AgenticRAG] Fetch failed for {url_to_fetch}: {e}")
        return {
            **state,
            "fetched_urls":    fetched_urls + [url_to_fetch],
            "web_fetch_count": state.get("web_fetch_count", 0) + 1,
        }


# ── Node: Grade Context ───────────────────────────────────────────────────────
def grade_context(state: AgentState) -> AgentState:
    from langchain_groq import ChatGroq

    print(f"[AgenticRAG] Grading context (web fetches: {state.get('web_fetch_count', 0)})...")

    if not state["documents"]:
        print("[AgenticRAG] No documents — marking insufficient.")
        return {**state, "answer": "INSUFFICIENT"}

    context = "\n\n".join(state["documents"][:5])

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=10,
        api_key=os.getenv("GROQ_API_KEY"),
    )

    response = llm.invoke(
        f"Does the following context contain ANY relevant financial information "
        f"that could help answer the question, even partially?\n\n"
        f"Question: {state['question']}\n\n"
        f"Context: {context[:2000]}\n\n"
        f"Answer only YES or NO."
    )

    is_sufficient = "YES" in response.content.upper()
    print(f"[AgenticRAG] Grade: {'SUFFICIENT' if is_sufficient else 'INSUFFICIENT'}")

    return {**state, "answer": "" if is_sufficient else "INSUFFICIENT"}


# ── Node: Generate Answer ─────────────────────────────────────────────────────
def generate_answer_node(state: AgentState) -> AgentState:
    from langchain_groq import ChatGroq

    print(f"[AgenticRAG] Generating answer...")

    if not state["documents"]:
        return {
            **state,
            "answer": "I don't have enough information to answer this question accurately."
        }

    context = "\n\n".join(state["documents"])

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.3,
        max_tokens=600,
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


# ── Router ────────────────────────────────────────────────────────────────────
def route_after_grade(state: AgentState) -> str:
    if state["answer"] != "INSUFFICIENT":
        return "generate"

    if state.get("web_fetch_count", 0) >= MAX_WEB_FETCHES:
        print(f"[AgenticRAG] Max web fetches ({MAX_WEB_FETCHES}) reached — generating best-effort answer.")
        return "generate"

    return "web_search"


# ── Build Graph ───────────────────────────────────────────────────────────────
def build_graph():
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError("langgraph not installed. Run: pip install langgraph")

    graph = StateGraph(AgentState)

    graph.add_node("search_chromadb", search_chromadb)
    graph.add_node("grade_context",   grade_context)
    graph.add_node("web_search_urls", web_search_urls)
    graph.add_node("fetch_live_url",  fetch_live_url)
    graph.add_node("generate_answer", generate_answer_node)

    graph.set_entry_point("search_chromadb")

    graph.add_edge("search_chromadb", "grade_context")
    graph.add_conditional_edges(
        "grade_context",
        route_after_grade,
        {
            "generate":   "generate_answer",
            "web_search": "web_search_urls",
        }
    )
    graph.add_edge("web_search_urls", "fetch_live_url")
    graph.add_edge("fetch_live_url",  "search_chromadb")
    graph.add_edge("generate_answer", END)

    return graph.compile()


# ── Singleton ─────────────────────────────────────────────────────────────────
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Public API ────────────────────────────────────────────────────────────────
def agentic_query(question: str) -> tuple[str, list[str], int]:
    from rag import initialize_components
    initialize_components()

    graph = get_graph()

    initial_state: AgentState = {
        "question":        question,
        "query":           question,
        "documents":       [],
        "sources":         [],
        "answer":          "",
        "web_fetch_count": 0,
        "fetched_urls":    [],
        "candidate_urls":  [],
    }

    final_state = graph.invoke(initial_state)

    answer    = final_state.get("answer", "")
    sources   = final_state.get("sources", [])
    web_count = final_state.get("web_fetch_count", 0)

    if not answer or answer == "INSUFFICIENT":
        answer = "I don't have enough information to answer this question accurately."

    return answer, sources, web_count