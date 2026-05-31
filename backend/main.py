"""
main.py — FastAPI app entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth import router as auth_router
from routes.rag  import router as rag_router

app = FastAPI(
    title="Financial Analyst RAG API",
    description="RAG system with JWT auth and RBAC",
    version="2.0.0"
)

# ── CORS — allow React frontend ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(rag_router)


@app.get("/")
def root():
    return {"message": "Financial Analyst RAG API v2.0"}


@app.get("/health")
def health():
    return {"status": "ok"}