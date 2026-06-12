"""
main.py — FastAPI application with startup warmup
"""
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth import router as auth_router
from routes.rag  import router as rag_router
from eval_route import router as eval_router


app = FastAPI(
    title="Financial Analyst RAG API",
    description="Production RAG system with JWT auth and RBAC",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(eval_router)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(rag_router)


# ── Startup warmup ────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """
    Warms up ChromaDB and LLM in background on server start.
    First request won't have to wait for initialization.
    """
    def warmup():
        try:
            from rag import initialize_components
            print("[Startup] Warming up components in background...")
            initialize_components()
            print("[Startup] Warmup complete.")
        except Exception as e:
            print(f"[Startup] Warmup failed: {e}")

    threading.Thread(target=warmup, daemon=True).start()


@app.get("/", tags=["Health"])
def root():
    return {"message": "Financial Analyst RAG API v2.0", "status": "running"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}