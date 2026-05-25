"""
app.py — Streamlit UI for Financial Analyst RAG System
"""

import os
import streamlit as st
import tempfile
from rag import process_sources, generate_answer, load_urls_from_txt

st.set_page_config(page_title="RAG App 💀", layout="wide")

st.title("💀 RAG Q&A System — Financial Analyst AI")
st.markdown("Ask questions from URLs and PDFs using AI")

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.header("📥 Add Sources")

input_mode = st.sidebar.radio(
    "Input mode",
    ["Manual URLs", "Bulk .txt file", "PDF upload"],
    index=0,
)

sources_to_process = []

# ── Mode 1: Manual URLs ───────────────────────────────────────────────────────
if input_mode == "Manual URLs":
    st.sidebar.markdown("Enter one URL per line:")
    url_text = st.sidebar.text_area(
        "URLs",
        placeholder="https://finance.yahoo.com/...\nhttps://reuters.com/...",
        height=180,
    )
    if url_text.strip():
        sources_to_process = [
            u.strip() for u in url_text.strip().splitlines() if u.strip()
        ]

# ── Mode 2: Bulk .txt file ────────────────────────────────────────────────────
elif input_mode == "Bulk .txt file":
    st.sidebar.markdown("Upload a `.txt` file — one URL per line.")
    txt_file = st.sidebar.file_uploader("Upload urls.txt", type=["txt"])
    if txt_file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp.write(txt_file.read())
            tmp_path = tmp.name
        sources_to_process = load_urls_from_txt(tmp_path)
        os.unlink(tmp_path)
        st.sidebar.success(f"✅ Loaded {len(sources_to_process)} URLs")
        for url in sources_to_process:
            st.sidebar.caption(f"• {url}")

# ── Mode 3: PDF upload ────────────────────────────────────────────────────────
elif input_mode == "PDF upload":
    st.sidebar.markdown("Upload one or more PDF files:")
    pdf_files = st.sidebar.file_uploader(
        "Upload PDFs", type=["pdf"], accept_multiple_files=True
    )
    if pdf_files:
        for pdf in pdf_files:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(pdf.read())
            tmp.flush()
            sources_to_process.append(tmp.name)
        st.sidebar.success(f"✅ {len(pdf_files)} PDF(s) ready")

# ── Process button ────────────────────────────────────────────────────────────
process_button = st.sidebar.button(
    "🚀 Process Sources", disabled=not sources_to_process
)

if "processed" not in st.session_state:
    st.session_state.processed = False

if process_button and sources_to_process:
    st.info(f"Processing {len(sources_to_process)} source(s)...")
    log_lines = []
    log_area  = st.empty()

    for step in process_sources(sources_to_process):
        log_lines.append(step)
        log_area.markdown("\n\n".join(log_lines))

    st.session_state.processed = True
    st.success("✅ All sources processed and indexed!")

    for src in sources_to_process:
        if src.startswith("/tmp/") and src.endswith(".pdf"):
            try:
                os.unlink(src)
            except Exception:
                pass

# ── Query ─────────────────────────────────────────────────────────────────────
st.header("💬 Ask a Question")
query = st.text_input("Enter your question:")

if st.button("🔍 Get Answer"):
    if not st.session_state.processed:
        st.warning("⚠️ Please process at least one source first!")
    elif not query.strip():
        st.warning("⚠️ Please enter a question!")
    else:
        with st.spinner("Thinking... 🤖"):
            answer, sources = generate_answer(query)

        st.subheader("🧠 Answer")
        st.write(answer)

        st.subheader("📚 Sources")
        for src in sources:
            icon = "📄" if src.endswith(".pdf") else "🔗"
            st.write(f"{icon} {src}")