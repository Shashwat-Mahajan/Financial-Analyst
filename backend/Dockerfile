FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ make curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Pin bcrypt first
RUN pip install --no-cache-dir bcrypt==4.0.1

# Install torch 2.7 CPU (needed by transformers 5.x + sentence-transformers 5.x)
RUN pip install --no-cache-dir \
    "torch==2.7.0+cpu" \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Install everything else — let pip resolve versions freely
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install NeMo last
RUN pip install --no-cache-dir nemoguardrails==0.22.0

# Re-pin bcrypt — must be last as nemoguardrails may override
RUN pip install --no-cache-dir bcrypt==4.0.1

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]