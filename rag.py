from uuid import uuid4
from dotenv import load_dotenv
from pathlib import Path
import os
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import WebBaseLoader
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_huggingface.embeddings import HuggingFaceEmbeddings

load_dotenv()

os.environ["USER_AGENT"] = "Mozilla/5.0"

CHUNK_SIZE = 500
COLLECTION_NAME = "rag_collection"
# VECTORSTORE_DIR = Path(__file__).parent / "resources/vectorstore"
VECTORSTORE_DIR = "/tmp/chroma_db"
EMBEDDING_MODEL = "BAAI/bge-small-en"

llm = None
vector_store = None


# ✅ INIT (with caching support)
def initialize_components():
    global llm, vector_store

    if llm is None:
        llm = ChatGroq(
            model='llama-3.3-70b-versatile',
            temperature=0.3,
            max_tokens=500,
            api_key=os.getenv("GROQ_API_KEY")
        )

    if vector_store is None:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )

        vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(VECTORSTORE_DIR)
        )


# ✅ CLEAN HTML
def clean_html(docs):
    cleaned_docs = []

    for doc in docs:
        soup = BeautifulSoup(doc.page_content, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator=" ")
        text = " ".join(text.split())

        doc.page_content = text

        # ✅ metadata fix
        if "source" not in doc.metadata:
            doc.metadata["source"] = "Unknown URL"

        cleaned_docs.append(doc)

    return cleaned_docs


# ✅ PROCESS URLS
def process_urls(urls):
    yield "🚀 Initializing components..."
    initialize_components()

    yield "📥 Loading data..."

    try:
        loader = WebBaseLoader(urls)
        data = loader.load()
    except Exception as e:
        yield f"❌ Error loading URLs: {e}"
        return

    yield "🧹 Cleaning data..."
    data = clean_html(data)

    yield "✂️ Splitting text..."
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=50
    )
    docs = splitter.split_documents(data)

    yield "💾 Storing in vector DB..."
    ids = [str(uuid4()) for _ in docs]
    vector_store.add_documents(docs, ids=ids)

    yield "✅ Done!"


# ✅ GENERATE ANSWER
def extract_companies_from_docs(docs):
    companies = set()

    for doc in docs:
        source = doc.metadata.get("source", "").lower()

        if "apple" in source:
            companies.add("Apple")
        if "microsoft" in source:
            companies.add("Microsoft")
        if "tesla" in source:
            companies.add("Tesla")
        if "google" in source or "alphabet" in source:
            companies.add("Google")

    return list(companies)


def generate_answer(query):
    if not vector_store:
        raise RuntimeError("Vector DB not initialized")

    # 🔥 STEP 1: broad retrieval (no filtering)
    initial_results = vector_store.similarity_search(query, k=20)

    # 🔥 STEP 2: extract companies from broad context
    companies = extract_companies_from_docs(initial_results)

    # 🔥 STEP 3: smart query expansion (EARLY)
    if ("company" in query.lower() or "better" in query.lower()) and len(companies) >= 2:
        query = query + " comparison " + " vs ".join(companies)

    # 🔥 STEP 4: final retrieval with better query
    results = vector_store.similarity_search_with_score(query, k=30)

    docs = [doc for doc, score in results if score < 0.95]

    if not docs:
        return "I don't know", []

    # 🔥 STEP 5: context
    context = "\n\n".join([doc.page_content for doc in docs])

    # 🔥 STEP 6: LLM
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