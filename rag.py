"""
rag.py — Phase 1 Upgraded Financial Analyst RAG System
Changes from original:
  - Step 1: PDF support via pdfplumber
  - Step 2: Bulk URL input (.txt file or list) with async fetching via httpx
  - Step 3: Supabase Storage (free S3 replacement) for raw doc backup
  - Step 4: Scheduler-ready ingestion (called by GitHub Actions cron)
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


load_dotenv()

os.environ["USER_AGENT"] = "Mozilla/5.0"

# ── Config ────────────────────────────────────────────────────────────────────
CHUNK_SIZE       = 500
CHUNK_OVERLAP    = 50
COLLECTION_NAME  = "rag_collection"
VECTORSTORE_DIR  = "/tmp/chroma_db"
EMBEDDING_MODEL  = "BAAI/bge-small-en"
SUPABASE_BUCKET  = "rag-raw-docs"          # create this bucket in Supabase dashboard

# ── Globals (cached) ──────────────────────────────────────────────────────────
llm          = None
vector_store = None
supabase: Client = None


# ── Init ──────────────────────────────────────────────────────────────────────
def initialize_components():
    global llm, vector_store, supabase

    if llm is None:
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=500,
            api_key=os.getenv("GROQ_API_KEY"),
        )

    if vector_store is None:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(VECTORSTORE_DIR),
        )

    # Supabase is optional — only init if credentials exist
    if supabase is None:
        url  = os.getenv("SUPABASE_URL")
        key  = os.getenv("SUPABASE_KEY")
        if url and key:
            supabase = create_client(url, key)


# ── STEP 3: Supabase storage (free S3 replacement) ────────────────────────────
def backup_to_supabase(doc_id: str, text: str, metadata: dict) -> None:
    """
    Uploads raw text to Supabase Storage for durability.
    If Supabase is not configured, silently skips — won't break the pipeline.
    """
    if supabase is None:
        return
    try:
        path = f"raw/{doc_id}.txt"
        content = f"SOURCE: {metadata.get('source', 'unknown')}\n\n{text}"
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            path,
            content.encode("utf-8"),
            {"content-type": "text/plain", "upsert": "true"},
        )
    except Exception as e:
        print(f"[Supabase backup skipped] {e}")


# ── STEP 1: PDF loader ────────────────────────────────────────────────────────
def load_pdf(source: str) -> list[Document]:
    """
    Accepts a local file path OR a URL pointing to a PDF.
    Returns a list of LangChain Documents, one per page.
    """
    docs = []

    # If it's a URL, download first
    if source.startswith("http"):
        response = httpx.get(source, follow_redirects=True, timeout=30)
        response.raise_for_status()
        tmp_path = f"/tmp/{uuid4()}.pdf"
        with open(tmp_path, "wb") as f:
            f.write(response.content)
        source = tmp_path

    with pdfplumber.open(source) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            text = " ".join(text.split())           # normalise whitespace
            if text.strip():
                docs.append(Document(
                    page_content=text,
                    metadata={"source": source, "page": i + 1, "type": "pdf"},
                ))
    return docs


# ── STEP 2: Async URL loader ──────────────────────────────────────────────────
async def _fetch_one(client: httpx.AsyncClient, url: str) -> Document | None:
    """Fetches a single URL and returns a cleaned Document."""
    try:
        r = await client.get(url, follow_redirects=True, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return Document(
            page_content=text,
            metadata={"source": url, "type": "url"},
        )
    except Exception as e:
        print(f"[fetch failed] {url}: {e}")
        return None


async def _fetch_all_urls(urls: list[str]) -> list[Document]:
    """
    Fetches all URLs concurrently using httpx.AsyncClient.
    20 URLs that used to take 40s sequentially now take ~5s.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        limits=httpx.Limits(max_connections=10),
    ) as client:
        tasks = [_fetch_one(client, url) for url in urls]
        results = await asyncio.gather(*tasks)
    return [doc for doc in results if doc is not None]


def load_urls_async(urls: list[str]) -> list[Document]:
    """Sync wrapper around the async URL fetcher — safe to call from Streamlit."""
    return asyncio.run(_fetch_all_urls(urls))


# ── STEP 1: Unified source loader ────────────────────────────────────────────
def load_source(source: str) -> list[Document]:
    """
    Accepts a single source — either a URL or a path/URL to a PDF.
    Returns LangChain Documents with consistent metadata.
    """
    if source.lower().endswith(".pdf"):
        return load_pdf(source)
    else:
        return load_urls_async([source])


def load_sources(sources: list[str]) -> list[Document]:
    """
    Accepts a mixed list of URLs and PDF paths.
    URLs are fetched concurrently; PDFs are loaded directly.
    """
    urls = [s for s in sources if not s.lower().endswith(".pdf")]
    pdfs = [s for s in sources if s.lower().endswith(".pdf")]

    docs = []
    if urls:
        docs += load_urls_async(urls)
    for pdf in pdfs:
        docs += load_pdf(pdf)
    return docs


# ── STEP 2: .txt bulk URL file reader ────────────────────────────────────────
def load_urls_from_txt(filepath: str) -> list[str]:
    """
    Reads a .txt file where each line is a URL.
    Skips blank lines and comment lines starting with #.

    Example urls.txt:
        https://finance.yahoo.com/...
        https://reuters.com/...
        # this line is ignored
    """
    with open(filepath, "r") as f:
        lines = f.readlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


# ── Text splitter (shared for both PDFs and URLs) ────────────────────────────
def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


# ── Main ingestion pipeline ───────────────────────────────────────────────────
def process_sources(sources: list[str]):
    """
    Unified ingestion pipeline.
    `sources` can be a mix of URLs and PDF paths/URLs.
    Yields status strings for Streamlit to display.
    """
    yield "🚀 Initialising components..."
    initialize_components()

    yield f"📥 Loading {len(sources)} source(s)..."
    docs = load_sources(sources)

    if not docs:
        yield "❌ No documents loaded. Check your URLs/PDFs."
        return

    yield f"✂️ Splitting {len(docs)} documents..."
    chunks = split_documents(docs)

    yield f"💾 Storing {len(chunks)} chunks in vector DB..."
    ids = [str(uuid4()) for _ in chunks]
    vector_store.add_documents(chunks, ids=ids)

    yield "☁️ Backing up raw docs to Supabase..."
    for doc in docs:
        doc_id = str(uuid4())
        backup_to_supabase(doc_id, doc.page_content, doc.metadata)

    yield f"✅ Done! {len(chunks)} chunks indexed from {len(docs)} documents."


# ── Legacy wrapper (keeps old Streamlit UI working unchanged) ─────────────────
def process_urls(urls: list[str]):
    """Kept for backward compatibility with the existing Streamlit app."""
    yield from process_sources(urls)


# ── STEP 4: Scheduler entry point (called by GitHub Actions cron) ─────────────
def scheduled_refresh():
    """
    Called by GitHub Actions on a cron schedule (every 6 hours).
    Reads URLs from urls.txt in the repo, ingests fresh content.

    GitHub Actions workflow (.github/workflows/refresh.yml):
    ─────────────────────────────────────────────────────────
    name: Scheduled RAG Refresh
    on:
      schedule:
        - cron: '0 */6 * * *'   # every 6 hours
      workflow_dispatch:         # also allow manual trigger

    jobs:
      refresh:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.11'
          - run: pip install -r requirements.txt
          - run: python rag.py --refresh
            env:
              GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
              SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
              SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
    ─────────────────────────────────────────────────────────
    Add GROQ_API_KEY, SUPABASE_URL, SUPABASE_KEY as GitHub repo secrets.
    """
    print("[Scheduler] Starting scheduled refresh...")
    initialize_components()

    urls_file = Path(__file__).parent / "urls.txt"
    if not urls_file.exists():
        print("[Scheduler] urls.txt not found. Create it with one URL per line.")
        return

    urls = load_urls_from_txt(str(urls_file))
    print(f"[Scheduler] Found {len(urls)} URLs to refresh.")

    for status in process_sources(urls):
        print(f"[Scheduler] {status}")

    print("[Scheduler] Refresh complete.")


# ── Answer generation (unchanged from original) ───────────────────────────────
def extract_companies_from_docs(docs):
    companies = set()
    for doc in docs:
        source = doc.metadata.get("source", "").lower()
        if "apple" in source:    companies.add("Apple")
        if "microsoft" in source: companies.add("Microsoft")
        if "tesla" in source:    companies.add("Tesla")
        if "google" in source or "alphabet" in source: companies.add("Google")
    return list(companies)


def generate_answer(query):
    if not vector_store:
        raise RuntimeError("Vector DB not initialised. Call initialize_components() first.")

    initial_results = vector_store.similarity_search(query, k=20)
    companies       = extract_companies_from_docs(initial_results)

    if ("company" in query.lower() or "better" in query.lower()) and len(companies) >= 2:
        query = query + " comparison " + " vs ".join(companies)

    results = vector_store.similarity_search_with_score(query, k=30)
    docs    = [doc for doc, score in results if score < 0.95]

    if not docs:
        return "I don't know", []

    context = "\n\n".join([doc.page_content for doc in docs])

    response = llm.invoke(f"""
You are a financial analyst AI.

Rules:
- Use ONLY the given context
- Combine information from multiple sources
- If multiple companies are present, compare them clearly
- If answer not found → say "I don't know"

Format:
- Use bullet points
- Separate sections per company
- Give final conclusion

Context:
{context}

Question:
{query}
""")

    sources = list(set([doc.metadata.get("source", "Unknown") for doc in docs]))
    return response.content, sources


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--refresh" in sys.argv:
        scheduled_refresh()
    else:
        # Quick smoke test
        initialize_components()
        for status in process_sources(["https://example.com"]):
            print(status)
        answer, sources = generate_answer("What is the revenue?")
        print("Answer:", answer)
        print("Sources:", sources)