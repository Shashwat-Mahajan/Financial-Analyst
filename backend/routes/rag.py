"""
routes/rag.py — /rag/query, /rag/ingest, /rag/me endpoints with RBAC
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user, require_analyst
from models import QueryRequest, QueryResponse, IngestRequest, IngestResponse
from rag import generate_answer, process_sources, initialize_components

router = APIRouter(prefix="/rag", tags=["RAG"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, user: dict = Depends(get_current_user)):
    """
    All logged-in users can query.
    viewer / analyst / admin → allowed
    """
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
    """
    Only analyst and admin can ingest.
    viewer → 403 Forbidden
    """
    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")
    try:
        initialize_components()
        results = list(process_sources(body.urls))
        return IngestResponse(message=results[-1] if results else "Ingestion complete")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    """Returns current logged-in user info."""
    return {
        "id":    str(user["id"]),
        "email": user["email"],
        "role":  user["role"],
    }