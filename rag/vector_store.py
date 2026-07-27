"""Vector store — ChromaDB-backed document indexing with embedding support."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np


class VectorStore:
    """ChromaDB-compatible vector store for document chunks.
    
    Uses a lightweight hash-bucket embedding approach for zero-dependency operation,
    with optional support for sentence-transformers or API-based embeddings.
    """

    def __init__(self, db_path: str, dim: int = 384, embedding_fn=None):
        self.db_path = db_path
        self.dim = dim
        self.embedding_fn = embedding_fn or self._default_embedding
        self._init_db()

    def _init_db(self):
        """Initialize SQLite tables for vector storage."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    collection TEXT DEFAULT 'default',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collection ON documents(collection)")
            conn.commit()

    def _default_embedding(self, text: str) -> list[float]:
        """Hash-bucket embedding — deterministic, no model needed.
        
        For production use with better accuracy, pass a sentence-transformers
        or API-based embedding function to the constructor.
        """
        # Use character n-grams for better Chinese text support
        ngrams = []
        for n in (2, 3, 4):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i:i + n])
        
        vec = np.zeros(self.dim, dtype=np.float32)
        for ng in ngrams:
            h = int(hashlib.md5(ng.encode()).hexdigest(), 16)
            idx = h % self.dim
            val = ((h >> 32) % 1000 - 500) / 500.0
            vec[idx] += val
        
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def add(self, doc_id: str, text: str, metadata: dict, collection: str = "default"):
        """Add a document chunk to the vector store."""
        embedding = self.embedding_fn(text)
        emb_blob = np.array(embedding, dtype=np.float32).tobytes()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO documents (id, text, metadata, embedding, collection)
                   VALUES (?, ?, ?, ?, ?)""",
                (doc_id, text, json.dumps(metadata, ensure_ascii=False), emb_blob, collection),
            )
            conn.commit()

    def add_batch(self, items: list[dict], collection: str = "default"):
        """Batch add documents. Each item: {id, text, metadata}."""
        with sqlite3.connect(self.db_path) as conn:
            rows = []
            for item in items:
                embedding = self.embedding_fn(item["text"])
                emb_blob = np.array(embedding, dtype=np.float32).tobytes()
                rows.append((
                    item["id"],
                    item["text"],
                    json.dumps(item.get("metadata", {}), ensure_ascii=False),
                    emb_blob,
                    collection,
                ))
            conn.executemany(
                """INSERT OR REPLACE INTO documents (id, text, metadata, embedding, collection)
                   VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def search(self, query: str, top_k: int = 5, collection: str = "default", 
               filters: dict = None) -> list[dict]:
        """Search for similar documents using cosine similarity."""
        query_emb = np.array(self.embedding_fn(query), dtype=np.float32)
        
        with sqlite3.connect(self.db_path) as conn:
            if collection:
                rows = conn.execute(
                    "SELECT id, text, metadata, embedding FROM documents WHERE collection = ?",
                    (collection,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, text, metadata, embedding FROM documents"
                ).fetchall()

        if not rows:
            return []

        results = []
        for row in rows:
            doc_id, text, meta_json, emb_blob = row
            doc_emb = np.frombuffer(emb_blob, dtype=np.float32)
            
            # Cosine similarity
            dot = np.dot(query_emb, doc_emb)
            norm_q = np.linalg.norm(query_emb)
            norm_d = np.linalg.norm(doc_emb)
            sim = dot / (norm_q * norm_d + 1e-10)
            
            metadata = json.loads(meta_json)
            
            # Apply filters if provided
            if filters:
                match = all(metadata.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            
            results.append({
                "id": doc_id,
                "text": text,
                "metadata": metadata,
                "score": float(sim),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete(self, doc_id: str):
        """Delete a document by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()

    def delete_collection(self, collection: str):
        """Delete all documents in a collection."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM documents WHERE collection = ?", (collection,))
            conn.commit()

    def count(self, collection: str = "default") -> int:
        """Count documents in a collection."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE collection = ?", (collection,)
            ).fetchone()
            return row[0] if row else 0

    def list_collections(self) -> list[str]:
        """List all collections."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT collection FROM documents"
            ).fetchall()
            return [r[0] for r in rows]

    def get(self, doc_id: str) -> Optional[dict]:
        """Get a document by ID."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, text, metadata FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
        if row:
            return {"id": row[0], "text": row[1], "metadata": json.loads(row[2])}
        return None
