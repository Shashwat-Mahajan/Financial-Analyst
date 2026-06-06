"""
routes/rag.py — with request timeout on ingest and status pagination
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List
from auth import get_current_user, require_analyst
from models import QueryRequest, QueryResponse, IngestRequest, IngestResponse
from rag import (
    generate_answer,
    process_sources,
    initialize_components,
    load_urls_from_txt,
    sanitize_urls,
    VECTORSTORE_DIR,
    S3_BUCKET,
    S3_CHROMA_KEY,
)

router = APIRouter(prefix="/rag", tags=["RAG"])

INGEST_TIMEOUT = 120   # 2 minutes max per ingest request


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, user: dict = Depends(get_current_user)):
    """All logged-in users can query."""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        initialize_components()
        answer, sources = generate_answer(body.question)
        return QueryResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest, user: dict = Depends(require_analyst)):
    """
    Analyst and admin only.
    Times out after 2 minutes to prevent hanging requests.
    Unsafe URLs are silently blocked.
    """
    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    # Sanitize URLs
    safe_urls, blocked = sanitize_urls(body.urls)
    if not safe_urls:
        raise HTTPException(
            status_code=400,
            detail=f"All {len(blocked)} URLs were blocked for security reasons"
        )

    def run_ingest():
        initialize_components()
        results = list(process_sources(safe_urls))
        return results[-1] if results else "Ingestion complete"

    try:
        message = await asyncio.wait_for(
            asyncio.to_thread(run_ingest),
            timeout=INGEST_TIMEOUT
        )
        warning = f" ({len(blocked)} URLs blocked)" if blocked else ""
        return IngestResponse(message=message + warning)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408,
            detail=f"Ingestion timed out after {INGEST_TIMEOUT}s. Try fewer URLs."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-files", response_model=IngestResponse)
async def ingest_files(
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_analyst)
):
    """Analyst and admin only — PDF or TXT file upload."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    initialize_components()
    sources = []

    for file in files:
        suffix = os.path.splitext(file.filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        if suffix == ".pdf":
            sources.append(tmp_path)
        elif suffix == ".txt":
            urls = load_urls_from_txt(tmp_path)
            safe_urls, _ = sanitize_urls(urls)
            sources.extend(safe_urls)
            os.unlink(tmp_path)
        else:
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {suffix}. Only PDF and TXT allowed."
            )

    if not sources:
        raise HTTPException(status_code=400, detail="No valid sources found in uploaded files")

    def run_ingest():
        return list(process_sources(sources))

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(run_ingest),
            timeout=INGEST_TIMEOUT
        )
        return IngestResponse(message=results[-1] if results else "Done")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="File ingestion timed out after 2 minutes")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for src in sources:
            if src.startswith(tempfile.gettempdir()) and src.endswith(".pdf"):
                try:
                    os.unlink(src)
                except Exception:
                    pass


@router.get("/status")
def get_status(user: dict = Depends(get_current_user)):
    """
    Returns what's indexed — companies, sources, suggested questions.
    All roles can access. Paginated to max 1000 chunks for performance.
    """
    try:
        initialize_components()
        from chromadb import PersistentClient

        client     = PersistentClient(path=VECTORSTORE_DIR)
        collection = client.get_or_create_collection("rag_collection")

        # Paginated — max 1000 to prevent memory issues
        results   = collection.get(include=["metadatas"], limit=1000)
        metadatas = results.get("metadatas", [])

        sources = list(set([
            m.get("source", "Unknown")
            for m in metadatas
            if m.get("source")
        ]))

        companies = set()
        for source in sources:
            s = source.lower()
            if "apple"     in s: companies.add("Apple")
            if "microsoft" in s: companies.add("Microsoft")
            if "tesla"     in s: companies.add("Tesla")
            if "google"    in s or "alphabet" in s: companies.add("Google")
            if "amazon"    in s: companies.add("Amazon")
            if "meta"      in s: companies.add("Meta")
            if "nvidia"    in s: companies.add("NVIDIA")
            if "netflix"   in s: companies.add("Netflix")

        suggested = []
        if companies:
            cl = list(companies)
            suggested.append(f"What is the latest revenue of {cl[0]}?")
            if len(cl) >= 2:
                suggested.append(f"Compare {cl[0]} and {cl[1]} performance")
            suggested.append(f"What are the risks facing {cl[0]}?")
            suggested.append("Which company has the best growth outlook?")
            suggested.append("What are the key financial metrics across all companies?")
        else:
            suggested = ["No data ingested yet. Ask an analyst to add sources."]

        return {
            "total_chunks":        len(metadatas),
            "total_sources":       len(sources),
            "companies_detected":  sorted(list(companies)),
            "sources":             sources[:20],
            "suggested_questions": suggested,
            "last_refreshed":      "Every 6 hours via GitHub Actions",
        }

    except Exception as e:
        return {
            "total_chunks":        0,
            "total_sources":       0,
            "companies_detected":  [],
            "sources":             [],
            "suggested_questions": ["No data ingested yet."],
            "last_refreshed":      "Never",
        }


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    return {
        "id":    str(user["id"]),
        "email": user["email"],
        "role":  user["role"],
    }