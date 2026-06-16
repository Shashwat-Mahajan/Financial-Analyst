FROM python:3.11-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10
ENV NEMOGUARDRAILS_LLM_FRAMEWORK=langchain

RUN apt-get update && apt-get install -y \
    gcc g++ make curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir bcrypt==4.0.1

RUN pip install --no-cache-dir \
    "torch==2.7.0+cpu" \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .

# Install in smaller batches to avoid network timeouts
RUN pip install --no-cache-dir \
    langchain langchain-core langchain-chroma \
    langchain-groq langchain-huggingface langchain-text-splitters

RUN pip install --no-cache-dir \
    chromadb sentence-transformers transformers

RUN pip install --no-cache-dir \
    python-dotenv beautifulsoup4 pdfplumber httpx boto3 nest_asyncio

RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" python-multipart

RUN pip install --no-cache-dir \
    "python-jose[cryptography]" "passlib[bcrypt]" "pydantic[email]" supabase

RUN pip install --no-cache-dir \
    ragas datasets langsmith

RUN pip install --no-cache-dir nemoguardrails==0.22.0

RUN pip install --no-cache-dir bcrypt==4.0.1

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]