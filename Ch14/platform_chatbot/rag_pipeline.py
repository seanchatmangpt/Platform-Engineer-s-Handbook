#!/usr/bin/env python3
"""Production RAG pipeline for platform documentation.

Missing production dependencies or configuration fail closed; all retrieval and synthesis use configured live backends.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import time
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_clients import AnthropicRuntime, ConfigurationError


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    context_documents: List[str]
    confidence_scores: List[float]
    answer: str
    source_citations: List[str]
    retrieval_time_ms: float


class RAGPipeline:
    def __init__(self, *, collection_name: str = "platform_docs", similarity_threshold: float = 0.60, chroma_path: str | None = None, embedding_model: str | None = None):
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ConfigurationError("chromadb and sentence-transformers are required; install Ch14/requirements.txt") from exc
        self.collection_name = collection_name
        self.similarity_threshold = similarity_threshold
        self.embedding_model_name = embedding_model or os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        self.chroma_path = Path(chroma_path or os.getenv("RAG_CHROMA_PATH", ".platform-rag/chroma"))
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        self.collection = self.client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        self.llm = AnthropicRuntime()

    @staticmethod
    def _chunk(text: str, *, chunk_size: int = 1400, overlap: int = 180) -> Iterable[str]:
        if chunk_size <= overlap:
            raise ValueError("chunk_size must be greater than overlap")
        text = text.strip()
        if not text:
            return
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            chunk = text[start:end].strip()
            if chunk:
                yield chunk
            if end == len(text):
                break
            start = end - overlap

    @staticmethod
    def _id(source: str, ordinal: int, content: str) -> str:
        return hashlib.sha256(f"{source}\0{ordinal}\0{content}".encode("utf-8")).hexdigest()

    def index_documents(self, doc_paths: Iterable[str], *, chunk_size: int = 1400) -> int:
        ids: list[str] = []
        docs: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        for raw_path in doc_paths:
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(path)
            files = [path] if path.is_file() else sorted(p for pattern in ("*.md", "*.txt", "*.yaml", "*.yml", "*.toml") for p in path.rglob(pattern))
            for file in files:
                content = file.read_text(encoding="utf-8")
                for ordinal, chunk in enumerate(self._chunk(content, chunk_size=chunk_size)):
                    source = str(file.resolve())
                    ids.append(self._id(source, ordinal, chunk))
                    docs.append(chunk)
                    metadatas.append({"source": source, "ordinal": ordinal})
        if not docs:
            raise RuntimeError("no indexable documents found")
        embeddings = self.embedding_model.encode(docs, normalize_embeddings=True).tolist()
        self.collection.upsert(ids=ids, documents=docs, embeddings=embeddings, metadatas=metadatas)
        return len(docs)

    def query(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        started = time.perf_counter()
        query_embedding = self.embedding_model.encode([query], normalize_embeddings=True)[0].tolist()
        result = self.collection.query(query_embeddings=[query_embedding], n_results=top_k, include=["documents", "distances", "metadatas"])
        documents = list((result.get("documents") or [[]])[0])
        distances = list((result.get("distances") or [[]])[0])
        metadatas = list((result.get("metadatas") or [[]])[0])
        filtered_docs: list[str] = []
        scores: list[float] = []
        sources: list[str] = []
        document_sources: list[str] = []
        for document, distance, metadata in zip(documents, distances, metadatas):
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            if score < self.similarity_threshold:
                continue
            filtered_docs.append(document)
            scores.append(score)
            source = str((metadata or {}).get("source", "unknown"))
            document_sources.append(source)
            if source not in sources:
                sources.append(source)
        if not filtered_docs:
            raise RuntimeError(f"no retrieved context met similarity threshold {self.similarity_threshold:.2f}")
        context = "\n\n---\n\n".join(f"SOURCE: {source}\n{document}" for source, document in zip(document_sources, filtered_docs))
        prompt = "Answer the platform-engineering question using only the supplied context. Cite the SOURCE paths you rely on. If the context is insufficient, say so.\n\n" + f"QUESTION:\n{query}\n\nCONTEXT:\n{context}"
        answer = self.llm.answer(prompt, max_tokens=1600, temperature=0.0)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return RetrievalResult(query, filtered_docs, scores, answer, sources, elapsed_ms)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index real platform docs and query the production RAG backend")
    parser.add_argument("--docs", nargs="+", required=True, help="Files/directories to index")
    parser.add_argument("--query", required=True)
    parser.add_argument("--collection", default=os.getenv("RAG_COLLECTION", "platform_docs"))
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    pipeline = RAGPipeline(collection_name=args.collection)
    indexed = pipeline.index_documents(args.docs)
    result = pipeline.query(args.query, top_k=args.top_k)
    print(f"indexed_chunks={indexed}")
    print(f"retrieval_time_ms={result.retrieval_time_ms:.2f}")
    print("sources:")
    for source in result.source_citations:
        print(f"- {source}")
    print("answer:")
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
