"""
routes/rag.py — /rag/query, /rag/ingest, /rag/ingest-files, /rag/me, /rag/status
"""
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
    vector_store,
    VECTORSTORE_DIR,
)

router = APIRouter(prefix="/rag", tags=["RAG"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, user: dict = Depends(get_current_user)):
    """All logged-in users can query — viewer, analyst, admin."""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        initialize_components()
        answer, sources = generate_answer(body.question)
        return QueryResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest", response_model=IngestResponse)
def ingest(body: IngestRequest, user: dict = Depends(require_analyst)):
    """Analyst and admin only — ingest URLs."""
    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")
    try:
        initialize_components()
        results = list(process_sources(body.urls))
        return IngestResponse(message=results[-1] if results else "Ingestion complete")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-files", response_model=IngestResponse)
def ingest_files(
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_analyst)
):
    """
    Analyst and admin only — ingest PDF or TXT files.
    PDF  → parsed page by page
    TXT  → treated as bulk URL list (one URL per line)
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    initialize_components()
    sources = []

    for file in files:
        suffix = os.path.splitext(file.filename)[1].lower()

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        if suffix == ".pdf":
            sources.append(tmp_path)
        elif suffix == ".txt":
            # Read URLs from txt file
            urls = load_urls_from_txt(tmp_path)
            sources.extend(urls)
            os.unlink(tmp_path)
        else:
            os.unlink(tmp_path)
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {suffix}. Only PDF and TXT allowed."
            )

    if not sources:
        raise HTTPException(status_code=400, detail="No valid sources found in uploaded files")

    try:
        results = list(process_sources(sources))
        return IngestResponse(message=results[-1] if results else "Ingestion complete")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp PDF files
        for src in sources:
            if src.startswith(tempfile.gettempdir()) and src.endswith(".pdf"):
                try:
                    os.unlink(src)
                except Exception:
                    pass


@router.get("/status")
def get_status(user: dict = Depends(get_current_user)):
    """
    Returns what data is currently indexed in the RAG system.
    All roles can access — helps viewers know what they can ask about.
    """
    try:
        initialize_components()
        from chromadb import PersistentClient

        # Get all documents from ChromaDB
        client     = PersistentClient(path=VECTORSTORE_DIR)
        collection = client.get_or_create_collection("rag_collection")
        results    = collection.get(include=["metadatas"])
        metadatas  = results.get("metadatas", [])

        # Extract unique sources
        sources = list(set([
            m.get("source", "Unknown")
            for m in metadatas
            if m.get("source")
        ]))

        # Extract companies from source URLs
        companies = set()
        keywords  = set()
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

        # Suggested questions based on available data
        suggested = []
        if companies:
            company_list = list(companies)
            suggested.append(f"What is the latest revenue of {company_list[0]}?")
            if len(company_list) >= 2:
                suggested.append(f"Compare {company_list[0]} and {company_list[1]} performance")
            suggested.append(f"What are the risks facing {company_list[0]}?")
            suggested.append("Which company has the best growth outlook?")
            suggested.append("What are the key financial metrics across all companies?")
        else:
            suggested = [
                "Ask about any company in the ingested data",
                "What are the latest market trends?",
                "Summarize the financial news",
            ]

        return {
            "total_chunks":        len(metadatas),
            "total_sources":       len(sources),
            "companies_detected":  sorted(list(companies)),
            "sources":             sources[:20],   # show max 20
            "suggested_questions": suggested,
            "last_refreshed":      "Every 6 hours via GitHub Actions",
        }

    except Exception as e:
        return {
            "total_chunks":        0,
            "total_sources":       0,
            "companies_detected":  [],
            "sources":             [],
            "suggested_questions": ["No data ingested yet. Ask an analyst to add sources."],
            "last_refreshed":      "Never",
        }


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """Returns current logged-in user info."""
    return {
        "id":    str(user["id"]),
        "email": user["email"],
        "role":  user["role"],
    }