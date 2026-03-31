# 💀 Financial Analyst RAG System

An AI-powered financial analysis tool that extracts insights from news articles and answers user queries using Retrieval-Augmented Generation (RAG).

🔗 Live App: https://financial-analyst-rag.streamlit.app/

---

## 🚀 Features

- 🔗 Input multiple financial news URLs
- 🧠 Automatic web scraping & text cleaning
- 🔍 Semantic search using vector embeddings
- 📊 Intelligent multi-company comparison
- 💬 Natural language question answering
- 📚 Source attribution for transparency

---

## 🧠 Tech Stack

- **Frontend**: Streamlit  
- **LLM**: Groq (LLaMA 3.3 70B)  
- **Embeddings**: HuggingFace (BAAI / MiniLM)  
- **Vector DB**: ChromaDB  
- **Scraping**: BeautifulSoup + WebBaseLoader  
- **Orchestration**: LangChain  

---

## ⚙️ How It Works

1. User provides URLs
2. System scrapes and cleans HTML content
3. Text is split into chunks
4. Embeddings are generated
5. Stored in vector database (ChromaDB)
6. User query is processed
7. Relevant chunks retrieved using similarity search
8. LLM generates answer using retrieved context

---

## 💡 Key Innovations

### 🔥 Dynamic Company Comparison
- Automatically detects companies from content
- Expands user queries intelligently
- Enables comparison without hardcoding

### ⚡ Smart Retrieval Optimization
- Multi-stage retrieval (broad → refined)
- Score filtering to remove irrelevant chunks

### 🔐 Secure Deployment
- Removed API keys from Git history
- Used Streamlit Secrets for secure key management

---

## 🚧 Challenges Faced

### ❌ 1. Slow Vector DB Ingestion
- Problem: Large text chunks slowed down embedding
- Solution: Optimized chunk size & overlap

---

### ❌ 2. Embedding Dimension Mismatch
- Problem: Switching models caused errors
- Solution: Cleared vector DB before changing models

---

### ❌ 3. "I don't know" Responses
- Problem: Model failed for comparison queries
- Solution:
  - Increased retrieval size (k)
  - Implemented query expansion
  - Added smarter prompt design

---

### ❌ 4. Hardcoded Company Logic
- Problem: System worked only for Apple/Microsoft
- Solution:
  - Built dynamic company detection from metadata
  - Enabled generic multi-company comparison

---

### ❌ 5. API Key Leak (Critical)
- Problem: GitHub blocked push due to exposed key
- Solution:
  - Removed `.env` from repo
  - Rewrote Git history using git-filter-repo
  - Regenerated API keys

---

### ❌ 6. Deployment Failure (Groq Error)
- Problem: API key not found in production
- Solution:
  - Used Streamlit Secrets
  - Added fallback logic (`os.getenv` + `st.secrets`)

---

## 🧪 Example Queries

- "What was Apple's iPhone revenue?"
- "Compare Apple and Microsoft performance"
- "Which company performed better and why?"

---

## 📦 Setup Instructions

```bash
git clone https://github.com/Shashwat-Mahajan/Financial-Analyst.git
cd Financial-Analyst
pip install -r requirements.txt
streamlit run main.py
