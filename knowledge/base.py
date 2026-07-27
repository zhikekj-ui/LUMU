"""Knowledge base — persistent document-level knowledge storage with semantic search."""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional


class KnowledgeBase:
    """Persistent knowledge base for storing and retrieving structured knowledge.
    
    Stores knowledge entries with:
    - Full text content
    - Metadata (source, tags, category)
    - Vector embeddings for semantic search
    - Relationships between entries
    """

    def __init__(self, db_path: str, dim: int = 384, embedding_fn=None):
        self.db_path = db_path
        self.dim = dim
        from knowledge.embedding import get_embedding_fn
        self.embedding_fn = embedding_fn or get_embedding_fn()
        self._init_db()

    def _init_db(self):
        """Initialize knowledge base tables."""
        import numpy as np
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    source TEXT,
                    metadata TEXT DEFAULT '{}',
                    embedding BLOB,
                    related_ids TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge(category)")
            
            # Full-text search table
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    title, content, tags,
                    content='knowledge',
                    content_rowid='rowid'
                )
            """)
            
            # Triggers to keep FTS in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS kb_fts_insert AFTER INSERT ON knowledge BEGIN
                    INSERT INTO knowledge_fts(rowid, title, content, tags)
                    VALUES (new.rowid, new.title, new.content, new.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS kb_fts_delete AFTER DELETE ON knowledge BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
                    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS kb_fts_update AFTER UPDATE ON knowledge BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
                    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                    INSERT INTO knowledge_fts(rowid, title, content, tags)
                    VALUES (new.rowid, new.title, new.content, new.tags);
                END
            """)
            
            # v4: Quality scoring columns (non-destructive ALTER for existing DBs)
            try:
                conn.execute("ALTER TABLE knowledge ADD COLUMN quality_score REAL DEFAULT 0.5")
            except Exception:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE knowledge ADD COLUMN hit_count INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE knowledge ADD COLUMN last_used TEXT")
            except Exception:
                pass
            
            conn.commit()

    def _default_embedding(self, text: str) -> list[float]:
        """Hash-bucket embedding for zero-dependency operation."""
        import hashlib
        import numpy as np
        
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

    def add(self, title: str, content: str, category: str = "general",
            tags: list[str] = None, source: str = None, metadata: dict = None,
            related_ids: list[str] = None) -> dict:
        """Add a knowledge entry."""
        import numpy as np
        
        entry_id = str(uuid.uuid4())
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        related_json = json.dumps(related_ids or [], ensure_ascii=False)
        
        # Generate embedding
        full_text = f"{title}\n{content}"
        embedding = np.array(self.embedding_fn(full_text), dtype=np.float32)
        emb_blob = embedding.tobytes()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO knowledge 
                   (id, title, content, category, tags, source, metadata, embedding, related_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, title, content, category, tags_json, source,
                 metadata_json, emb_blob, related_json),
            )
            conn.commit()
        
        return {
            "id": entry_id,
            "title": title,
            "category": category,
            "status": "created",
        }

    def update(self, entry_id: str, title: str = None, content: str = None,
               category: str = None, tags: list[str] = None,
               metadata: dict = None) -> dict:
        """Update an existing knowledge entry."""
        import numpy as np
        
        updates = []
        params = []
        
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        
        # Regenerate embedding if title or content changed
        if title is not None or content is not None:
            entry = self.get(entry_id)
            if entry:
                new_title = title or entry["title"]
                new_content = content or entry["content"]
                embedding = np.array(self.embedding_fn(f"{new_title}\n{new_content}"), dtype=np.float32)
                updates.append("embedding = ?")
                params.append(embedding.tobytes())
        
        if not updates:
            return {"status": "no_changes"}
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(entry_id)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE knowledge SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        
        return {"id": entry_id, "status": "updated"}

    def delete(self, entry_id: str) -> dict:
        """Delete a knowledge entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
            conn.commit()
        return {"id": entry_id, "status": "deleted"}

    def get(self, entry_id: str) -> Optional[dict]:
        """Get a knowledge entry by ID."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, title, content, category, tags, source, metadata, related_ids, created_at, updated_at FROM knowledge WHERE id = ?",
                (entry_id,),
            ).fetchone()
        
        if not row:
            return None
        
        return {
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "category": row[3],
            "tags": json.loads(row[4]),
            "source": row[5],
            "metadata": json.loads(row[6]),
            "related_ids": json.loads(row[7]),
            "created_at": row[8],
            "updated_at": row[9],
        }

    def search(self, query: str, limit: int = 10, category: str = None,
               tags: list[str] = None) -> list[dict]:
        """Hybrid search: FTS5 + vector similarity."""
        import numpy as np
        
        results = {}
        
        # FTS5 search (keyword-based)
        with sqlite3.connect(self.db_path) as conn:
            try:
                fts_rows = conn.execute(
                    """SELECT k.id, k.title, k.content, k.category, k.tags, k.source, k.metadata, k.related_ids, k.created_at, k.updated_at
                       FROM knowledge_fts f
                       JOIN knowledge k ON k.rowid = f.rowid
                       WHERE knowledge_fts MATCH ? LIMIT ?""",
                    (query, limit),
                ).fetchall()
                
                for row in fts_rows:
                    results[row[0]] = {
                        "id": row[0],
                        "title": row[1],
                        "content": row[2],
                        "category": row[3],
                        "tags": json.loads(row[4]),
                        "source": row[5],
                        "metadata": json.loads(row[6]),
                        "related_ids": json.loads(row[7]),
                        "score": 0.8,  # FTS matches get high score
                        "match_type": "keyword",
                    }
            except Exception:
                pass
            
            # LIKE fallback for Chinese text
            if len(results) < limit:
                terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
                if not terms:
                    terms = [query]
                
                for term in terms:
                    like_rows = conn.execute(
                        """SELECT id, title, content, category, tags, source, metadata, related_ids, created_at, updated_at
                           FROM knowledge
                           WHERE content LIKE ? OR title LIKE ?
                           LIMIT ?""",
                        (f"%{term}%", f"%{term}%", limit),
                    ).fetchall()
                    
                    for row in like_rows:
                        if row[0] not in results:
                            results[row[0]] = {
                                "id": row[0],
                                "title": row[1],
                                "content": row[2],
                                "category": row[3],
                                "tags": json.loads(row[4]),
                                "source": row[5],
                                "metadata": json.loads(row[6]),
                                "related_ids": json.loads(row[7]),
                                "score": 0.6,
                                "match_type": "keyword",
                            }
        
        # Vector similarity search
        query_emb = np.array(self.embedding_fn(query), dtype=np.float32)
        
        with sqlite3.connect(self.db_path) as conn:
            all_rows = conn.execute(
                "SELECT id, title, content, category, tags, source, metadata, related_ids, created_at, updated_at, embedding FROM knowledge"
            ).fetchall()
            
            for row in all_rows:
                if row[10]:  # embedding exists
                    doc_emb = np.frombuffer(row[10], dtype=np.float32)
                    dot = np.dot(query_emb, doc_emb)
                    norm_q = np.linalg.norm(query_emb)
                    norm_d = np.linalg.norm(doc_emb)
                    sim = float(dot / (norm_q * norm_d + 1e-10))
                    
                    if row[0] in results:
                        # Combine scores
                        results[row[0]]["score"] = max(results[row[0]]["score"], sim)
                        results[row[0]]["match_type"] = "hybrid"
                    elif sim > 0.1:  # Threshold for vector matches
                        results[row[0]] = {
                            "id": row[0],
                            "title": row[1],
                            "content": row[2],
                            "category": row[3],
                            "tags": json.loads(row[4]),
                            "source": row[5],
                            "metadata": json.loads(row[6]),
                            "related_ids": json.loads(row[7]),
                            "score": sim,
                            "match_type": "vector",
                        }
        
        # Apply filters
        filtered = []
        for entry in results.values():
            if category and entry["category"] != category:
                continue
            if tags:
                entry_tags = set(entry["tags"])
                if not any(t in entry_tags for t in tags):
                    continue
            filtered.append(entry)
        
        # Sort by score
        filtered.sort(key=lambda x: x["score"], reverse=True)
        return filtered[:limit]

    def list_entries(self, category: str = None, limit: int = 50) -> list[dict]:
        """List knowledge entries with optional category filter."""
        with sqlite3.connect(self.db_path) as conn:
            if category:
                rows = conn.execute(
                    """SELECT id, title, category, tags, source, created_at, updated_at
                       FROM knowledge WHERE category = ? ORDER BY updated_at DESC LIMIT ?""",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, title, category, tags, source, created_at, updated_at
                       FROM knowledge ORDER BY updated_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        
        return [
            {
                "id": r[0],
                "title": r[1],
                "category": r[2],
                "tags": json.loads(r[3]),
                "source": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    def list_categories(self) -> list[dict]:
        """List all categories with entry counts."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM knowledge GROUP BY category ORDER BY count DESC"
            ).fetchall()
        return [{"category": r[0], "count": r[1]} for r in rows]

    def stats(self) -> dict:
        """Get knowledge base statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            categories = conn.execute(
                "SELECT COUNT(DISTINCT category) FROM knowledge"
            ).fetchone()[0]
            with_source = conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE source IS NOT NULL"
            ).fetchone()[0]
        
        return {
            "total_entries": total,
            "categories": categories,
            "entries_with_source": with_source,
            "db_path": self.db_path,
        }

    def touch_entries(self, entry_ids: list[str]):
        """v4: Mark knowledge entries as used — increment hit_count, update last_used, boost quality."""
        if not entry_ids:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            for eid in entry_ids:
                conn.execute(
                    "UPDATE knowledge SET hit_count = hit_count + 1, last_used = ?, quality_score = MIN(1.0, quality_score + 0.05) WHERE id = ?",
                    (ts, eid),
                )
            conn.commit()

    def adjust_quality(self, entry_id: str, delta: float):
        """v4: Adjust quality score by delta. Clamped to [0.0, 1.0]."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT quality_score FROM knowledge WHERE id = ?", (entry_id,)).fetchone()
            if row:
                new_score = max(0.0, min(1.0, (row[0] or 0.5) + delta))
                conn.execute("UPDATE knowledge SET quality_score = ? WHERE id = ?", (new_score, entry_id))
                conn.commit()

    def evict_low_quality(self, threshold: float = 0.2, min_age_days: int = 14, max_entries: int = 100) -> dict:
        """v4: Delete knowledge entries below quality threshold that haven't been used recently.
        
        Only evicts entries created at least min_age_days ago AND below threshold.
        Keeps at most max_entries total (evicts lowest-scoring excess).
        """
        import time as _time
        cutoff_ts = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime(_time.time() - min_age_days * 86400))
        
        with sqlite3.connect(self.db_path) as conn:
            # Count total
            total = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            
            if total <= max_entries:
                # Only evict below-threshold entries older than cutoff
                rows = conn.execute(
                    "SELECT id FROM knowledge WHERE quality_score < ? AND created_at < ?",
                    (threshold, cutoff_ts),
                ).fetchall()
            else:
                # Also evict lowest-scoring excess entries
                excess = total - max_entries
                rows = conn.execute(
                    "SELECT id FROM knowledge WHERE quality_score < ? AND created_at < ? ORDER BY quality_score ASC, last_used ASC LIMIT ?",
                    (threshold, cutoff_ts, excess + 50),
                ).fetchall()
            
            evicted = 0
            for row in rows:
                conn.execute("DELETE FROM knowledge WHERE id = ?", (row[0],))
                evicted += 1
            
            conn.commit()
        
        return {"evicted": evicted, "remaining": total - evicted}

    def search_with_tracking(self, query: str, limit: int = 10, category: str = None,
                             tags: list[str] = None) -> tuple[list[dict], list[str]]:
        """v4: Search and return both results AND entry IDs for quality tracking."""
        results = self.search(query, limit=limit, category=category, tags=tags)
        entry_ids = [r["id"] for r in results if r.get("score", 0) > 0.15]
        # Boost results by quality_score for better ranking
        for r in results:
            q_score = r.get("quality_score", 0.5)
            r["score"] = r.get("score", 0) * (0.5 + 0.5 * q_score)  # Quality-weighted score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results, entry_ids

    def reembed_all(self) -> dict:
        """Re-embed all entries using the current embedding function.
        
        Use after changing embedding configuration to upgrade all vectors.
        """
        import numpy as np
        reembedded = 0
        errors = 0
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, content FROM knowledge"
            ).fetchall()
            
            for row in rows:
                entry_id, title, content = row
                try:
                    full_text = f"{title}\n{content}"
                    embedding = np.array(self.embedding_fn(full_text), dtype=np.float32)
                    emb_blob = embedding.tobytes()
                    conn.execute(
                        "UPDATE knowledge SET embedding = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (emb_blob, entry_id),
                    )
                    reembedded += 1
                except Exception as e:
                    errors += 1
            
            conn.commit()
        
        return {
            "reembedded": reembedded,
            "errors": errors,
            "total": reembedded + errors,
            "embedding_info": "see kb_stats for details",
        }


