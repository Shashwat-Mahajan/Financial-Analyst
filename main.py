import streamlit as st
from rag import process_urls, generate_answer

st.set_page_config(page_title="RAG App 💀", layout="wide")

st.title("💀 RAG Q&A System (Financial Analyst AI)")
st.markdown("Ask questions from URLs using AI")

# 🔥 Sidebar
st.sidebar.header("📥 Enter URLs")

url1 = st.sidebar.text_input("URL 1", "")
url2 = st.sidebar.text_input("URL 2", "")

process_button = st.sidebar.button("🚀 Process URLs")

# 🔥 State
if "processed" not in st.session_state:
    st.session_state.processed = False

# 🔥 Process URLs
if process_button:
    with st.spinner("Processing URLs... ⏳"):
        urls = [u for u in [url1, url2] if u.strip()]

        if not urls:
            st.warning("⚠️ Please enter at least one URL")
        else:
            for step in process_urls(urls):
                st.write(step)

            st.session_state.processed = True
            st.success("✅ Data processed successfully!")

# 🔥 Query
st.header("💬 Ask a Question")

query = st.text_input("Enter your question:")

if st.button("🔍 Get Answer"):

    if not st.session_state.processed:
        st.warning("⚠️ Please process URLs first!")
    elif not query.strip():
        st.warning("⚠️ Please enter a question!")
    else:
        with st.spinner("Thinking... 🤖"):
            answer, sources = generate_answer(query)

        st.subheader("🧠 Answer")
        st.write(answer)

        st.subheader("📚 Sources")
        for src in sources:
            st.write(f"🔗 {src}")