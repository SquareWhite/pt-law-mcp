from __future__ import annotations

import os

_DEFAULT_MODEL = "intfloat/multilingual-e5-base"


def prepare_embedding_text(article: dict) -> str:
    parts = []
    if article.get("chapter"):
        parts.append(article["chapter"])
    if article.get("section"):
        parts.append(article["section"])
    if article.get("title"):
        parts.append(article["title"])
    base = " | ".join(parts)
    text = article.get("text") or ""
    return f"{base} | {text}" if base else text


class EmbeddingService:
    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        model = model_name or os.getenv("EMBEDDING_MODEL", _DEFAULT_MODEL)
        self._model: SentenceTransformer = SentenceTransformer(model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {t}" for t in texts]
        embeddings = self._model.encode(prefixed, batch_size=32, show_progress_bar=False)
        return [e.tolist() for e in embeddings]

    def embed_query(self, query: str) -> list[float]:
        result = self._model.encode(f"query: {query}", show_progress_bar=False)
        return result.tolist()

    def dimensions(self) -> int:
        return self._model.get_sentence_embedding_dimension()
