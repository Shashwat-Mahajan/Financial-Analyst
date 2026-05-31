"""
rag.py — Phase 1 Upgraded Financial Analyst RAG System
Architecture:
  - PDF + bulk URL ingestion
  - Async URL fetching via httpx
  - ChromaDB persisted to AWS S3
  - Scheduled refresh via GitHub Actions cron
"""

import asyncio
import boto3
import io
import os
import sys
import tarfile
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
CHUNK_SIZE      = 500
CHUNK_OVERLAP   = 50
COLLECTION_NAME = "rag_collection"
EMBEDDING_MODEL = "BAAI/bge-small-en"

S3_BUCKET       = os.getenv("S3_BUCKET", "your-rag-bucket")
S3_RAW_PREFIX   = "raw/"
S3_CHROMA_KEY   = "chroma/chroma_db.tar.gz"
VECTORSTORE_DIR = str(Path(__file__).parent / "vectorstore")

# ── Globals ───────────────────────────────────────────────────────────────────
llm          = None
vector_store = None
s3_client    = None


# ── S3 client ─────────────────────────────────────────────────────────────────
def get_s3():
    global s3_client
    if s3_client is None:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name           = os.getenv("AWS_REGION", "ap-south-1"),
        )
    return s3_client


# ── ChromaDB S3 sync ──────────────────────────────────────────────────────────
def upload_chroma_to_s3():
    try:
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            tar.add(VECTORSTORE_DIR, arcname="chroma_db")
        tar_buffer.seek(0)
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=S3_CHROMA_KEY,
            Body=tar_buffer.read(),
        )
        print("[S3] ChromaDB uploaded.")
    except Exception as e:
        print(f"[S3] ChromaDB upload failed: {e}")


def download_chroma_from_s3():
    try:
        response   = get_s3().get_object(Bucket=S3_BUCKET, Key=S3_CHROMA_KEY)
        tar_buffer = io.BytesIO(response["Body"].read())
        with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
            tar.extractall(str(Path(__file__).parent))
        print("[S3] ChromaDB downloaded.")
        return True
    except Exception as e:
        print(f"[S3] ChromaDB not found, starting fresh: {e}")
        return False


def backup_raw_to_s3(doc_id: str, text: str, metadata: dict):
    try:
        content = f"SOURCE: {metadata.get('source', 'unknown')}\n\n{text}"
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=f"{S3_RAW_PREFIX}{doc_id}.txt",
            Body=content.encode("utf-8"),
            ContentType="text/plain",
        )
    except Exception as e:
        print(f"[S3] Raw backup failed: {e}")


# ── Init ──────────────────────────────────────────────────────────────────────
def initialize_components():
    global llm, vector_store

    # Download latest ChromaDB from S3 before initializing
    download_chroma_from_s3()

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
            persist_directory=VECTORSTORE_DIR,
        )


# ── PDF loader ────────────────────────────────────────────────────────────────
def load_pdf(source: str) -> list[Document]:
    docs = []
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
            text = " ".join(text.split())
            if text.strip():
                docs.append(Document(
                    page_content=text,
                    metadata={"source": source, "page": i + 1, "type": "pdf"},
                ))
    return docs


# ── Async URL loader ──────────────────────────────────────────────────────────
async def _fetch_one(client: httpx.AsyncClient, url: str):
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
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        limits=httpx.Limits(max_connections=10),
    ) as client:
        results = await asyncio.gather(*[_fetch_one(client, url) for url in urls])
    return [doc for doc in results if doc is not None]


def load_urls_async(urls: list[str]) -> list[Document]:
    return asyncio.run(_fetch_all_urls(urls))


# ── Unified source loader ─────────────────────────────────────────────────────
def load_sources(sources: list[str]) -> list[Document]:
    urls = [s for s in sources if not s.lower().endswith(".pdf")]
    pdfs = [s for s in sources if s.lower().endswith(".pdf")]
    docs = []
    if urls:
        docs += load_urls_async(urls)
    for pdf in pdfs:
        docs += load_pdf(pdf)
    return docs


def load_urls_from_txt(filepath: str) -> list[str]:
    with open(filepath, "r") as f:
        lines = f.readlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


# ── Splitter ──────────────────────────────────────────────────────────────────
def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


# ── Ingestion pipeline ────────────────────────────────────────────────────────
def process_sources(sources: list[str]):
    yield "🚀 Initialising components..."
    initialize_components()

    yield f"📥 Loading {len(sources)} source(s)..."
    docs = load_sources(sources)

    if not docs:
        yield "❌ No documents loaded. Check your URLs/PDFs."
        return

    yield f"✂️  Splitting {len(docs)} documents..."
    chunks = split_documents(docs)

    yield f"💾 Storing {len(chunks)} chunks in ChromaDB..."
    ids = [str(uuid4()) for _ in chunks]
    vector_store.add_documents(chunks, ids=ids)

    yield "☁️  Backing up raw docs to S3..."
    for doc in docs:
        backup_raw_to_s3(str(uuid4()), doc.page_content, doc.metadata)

    yield "📤 Syncing ChromaDB to S3..."
    upload_chroma_to_s3()

    yield f"✅ Done! {len(chunks)} chunks indexed from {len(docs)} documents."


def process_urls(urls: list[str]):
    yield from process_sources(urls)


# ── Answer generation ─────────────────────────────────────────────────────────
def extract_companies_from_docs(docs):
    companies = set()
    for doc in docs:
        source = doc.metadata.get("source", "").lower()
        if "apple"     in source: companies.add("Apple")
        if "microsoft" in source: companies.add("Microsoft")
        if "tesla"     in source: companies.add("Tesla")
        if "google"    in source or "alphabet" in source: companies.add("Google")
    return list(companies)


def generate_answer(query):
    if not vector_store:
        raise RuntimeError("Vector DB not initialised.")

    initial_results = vector_store.similarity_search(query, k=20)
    companies       = extract_companies_from_docs(initial_results)

    if ("company" in query.lower() or "better" in query.lower()) and len(companies) >= 2:
        query = query + " comparison " + " vs ".join(companies)

    results = vector_store.similarity_search_with_score(query, k=30)
    docs    = [doc for doc, score in results if score < 0.95]

    if not docs:
        return "I don't know", []

    context  = "\n\n".join([doc.page_content for doc in docs])
    response = llm.invoke(f"""
You are a financial analyst AI.

Rules:
- Use ONLY the given context
- Combine information from multiple sources
- If multiple companies are present, compare them clearly
- If answer not found say I don't know

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


# ── CLI entry point for GitHub Actions ───────────────────────────────────────
if __name__ == "__main__":
    if "--refresh" in sys.argv:
        print("[Refresh] Starting scheduled refresh...")
        initialize_components()

        try:
            response = get_s3().get_object(
                Bucket=S3_BUCKET,
                Key="config/Financial news sources refreshed.txt"
            )
            content = response["Body"].read().decode("utf-8")
            urls = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except Exception as e:
            print(f"[Refresh] Could not read urls file from S3: {e}")
            sys.exit(1)

        print(f"[Refresh] Found {len(urls)} URLs.")
        for status in process_sources(urls):
            print(status)

        print("[Refresh] Done.")