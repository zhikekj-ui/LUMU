"""RAG pipeline — orchestrates document parsing, indexing, and retrieval."""
import os
import uuid
from pathlib import Path
from typing import Optional

from .parser import DocumentParser, DocumentChunk
from .vector_store import VectorStore


class RAGPipeline:
    """Full RAG pipeline: parse → chunk → embed → store → retrieve."""

    def __init__(self, data_dir: str, dim: int = 384, embedding_fn=None,
                 chunk_size: int = 500, chunk_overlap: int = 50):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.parser = DocumentParser(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.store = VectorStore(
            db_path=str(self.data_dir / "rag_vectors.db"),
            dim=dim,
            embedding_fn=embedding_fn,
        )
        self.collections_db = str(self.data_dir / "rag_collections.db")
        self._init_collections()

    def _init_collections(self):
        """Initialize collections metadata table."""
        import sqlite3
        with sqlite3.connect(self.collections_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collections (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    doc_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def ingest_file(self, file_path: str, collection: str = "default",
                    metadata: dict = None) -> dict:
        """Parse and index a single file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        chunks = self.parser.parse_file(file_path)
        if not chunks:
            return {"status": "empty", "chunks": 0}

        # Add extra metadata
        for chunk in chunks:
            if metadata:
                chunk.metadata.update(metadata)

        # Store chunks
        items = []
        for chunk in chunks:
            doc_id = f"{path.stem}_{chunk.metadata.get('chunk_index', 0)}_{uuid.uuid4().hex[:8]}"
            items.append({
                "id": doc_id,
                "text": chunk.text,
                "metadata": chunk.metadata,
            })

        self.store.add_batch(items, collection=collection)
        self._update_collection(collection, len(items))

        return {
            "status": "success",
            "file": path.name,
            "chunks": len(items),
            "collection": collection,
        }

    def ingest_text(self, text: str, collection: str = "default",
                    source: str = "direct_input", metadata: dict = None) -> dict:
        """Parse and index raw text."""
        chunks = self.parser.parse_text(text, source=source)
        if not chunks:
            return {"status": "empty", "chunks": 0}

        for chunk in chunks:
            if metadata:
                chunk.metadata.update(metadata)

        items = []
        for chunk in chunks:
            doc_id = f"{source}_{chunk.metadata.get('chunk_index', 0)}_{uuid.uuid4().hex[:8]}"
            items.append({
                "id": doc_id,
                "text": chunk.text,
                "metadata": chunk.metadata,
            })

        self.store.add_batch(items, collection=collection)
        self._update_collection(collection, len(items))

        return {
            "status": "success",
            "source": source,
            "chunks": len(items),
            "collection": collection,
        }

    def query(self, question: str, collection: str = "default",
              top_k: int = 5, min_score: float = 0.1) -> dict:
        """Retrieve relevant chunks for a question."""
        results = self.store.search(question, top_k=top_k, collection=collection)
        
        # Filter by minimum score
        results = [r for r in results if r["score"] >= min_score]

        if not results:
            return {
                "answer": "",
                "sources": [],
                "context": "",
            }

        # Build context string
        context_parts = []
        sources = []
        for i, r in enumerate(results):
            context_parts.append(f"[{i+1}] {r['text']}")
            sources.append({
                "text": r["text"][:200],
                "score": r["score"],
                "source": r["metadata"].get("source", "unknown"),
                "filename": r["metadata"].get("filename", "unknown"),
            })

        context = "\n\n".join(context_parts)

        return {
            "context": context,
            "sources": sources,
            "num_results": len(results),
        }

    def query_with_llm(self, question: str, llm_client, model: str,
                       collection: str = "default", top_k: int = 5) -> dict:
        """Retrieve context and generate answer with LLM."""
        retrieval = self.query(question, collection=collection, top_k=top_k)
        
        if not retrieval["context"]:
            return {
                "answer": "未找到相关信息。",
                "sources": [],
                "retrieved": False,
            }

        # Build RAG prompt
        system_prompt = """你是一个基于文档的问答助手。根据提供的文档内容回答用户问题。
规则：
1. 只根据提供的文档内容回答，不要编造信息
2. 如果文档中没有相关信息，明确告知用户
3. 回答时引用来源编号 [1], [2] 等
4. 保持回答简洁准确"""

        user_prompt = f"""文档内容：
{retrieval['context']}

用户问题：{question}

请根据以上文档内容回答问题："""

        # Call LLM
        response = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        answer = response.choices[0].message.content if response.choices else ""

        return {
            "answer": answer,
            "sources": retrieval["sources"],
            "retrieved": True,
        }

    def create_collection(self, name: str, description: str = "") -> dict:
        """Create a new named collection."""
        import sqlite3
        with sqlite3.connect(self.collections_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO collections (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
        return {"status": "created", "name": name}

    def list_collections(self) -> list[dict]:
        """List all collections with metadata."""
        import sqlite3
        with sqlite3.connect(self.collections_db) as conn:
            rows = conn.execute(
                "SELECT name, description, doc_count, created_at FROM collections ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {"name": r[0], "description": r[1], "doc_count": r[2], "created_at": r[3]}
            for r in rows
        ]

    def delete_collection(self, name: str) -> dict:
        """Delete a collection and all its documents."""
        import sqlite3
        self.store.delete_collection(name)
        with sqlite3.connect(self.collections_db) as conn:
            conn.execute("DELETE FROM collections WHERE name = ?", (name,))
            conn.commit()
        return {"status": "deleted", "name": name}

    def _update_collection(self, name: str, count: int):
        """Update collection document count."""
        import sqlite3
        with sqlite3.connect(self.collections_db) as conn:
            # Ensure collection exists
            conn.execute(
                "INSERT OR IGNORE INTO collections (name) VALUES (?)", (name,)
            )
            conn.execute(
                """UPDATE collections SET doc_count = doc_count + ?, 
                   updated_at = CURRENT_TIMESTAMP WHERE name = ?""",
                (count, name),
            )
            conn.commit()

    def stats(self) -> dict:
        """Get RAG system statistics."""
        collections = self.list_collections()
        total_docs = sum(c.get("doc_count", 0) for c in collections)
        return {
            "collections": len(collections),
            "total_documents": total_docs,
            "collection_details": collections,
        }
