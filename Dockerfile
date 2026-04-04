FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml .

# Install CPU-only torch first to avoid pulling the much larger CUDA wheels
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install the rest of the package dependencies
RUN pip install .

# Pre-download the embedding model at build time so the container starts fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"

COPY src/ src/
COPY laws.json .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
CMD ["./entrypoint.sh"]
