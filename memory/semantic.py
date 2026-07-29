"""Semantic memory engine — vector embeddings + cosine similarity search.

Provides semantic search over memories using lightweight embeddings.
No external dependencies (numpy-free) — uses pure Python vector math.

Architecture:
- Character n-gram based embeddings (works well for Chinese + English)
- SQLite storage with BLOB vectors
- Cosine similarity for search
- Episodic memory for conversation events
"""
import json
import math
import sqlite3
import struct
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Real semantic embeddings replace the old 128-d character n-gram hashing.
# DIM / embed come from the shared memory embedding module, which uses the same
# fastembed (bge-small-zh-v1.5, 512-d) vector space as the knowledge base, so the
# agent can finally recall its own past by *meaning*, not just by keyword overlap.
from memory.embeddings import DIM as EMBED_DIM, embed as _embed_text

# Half-life (days) for the access-time decay applied to memory relevance scores.
MEMORY_DECAY_HALF_LIFE_DAYS = 30


def _vec_to_blob(vec: list[float]) -> bytes:
    """Convert vector to compact binary blob."""
    return struct.pack(f'{len(vec)}f', *vec)


def _blob_to_vec(blob: bytes) -> list[float]:
    """Convert binary blob back to vector."""
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two already-normalized vectors."""
    return sum(x * y for x, y in zip(a, b))


class SemanticMemory:
    """Semantic memory with vector embeddings for similarity search."""
    
    def __init__(self, db_path: str = "data/semantic_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    embedding BLOB NOT NULL,
                    importance REAL DEFAULT 0.5,
                    access_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    last_accessed TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    embedding BLOB NOT NULL,
                    session_id TEXT DEFAULT '',
                    importance REAL DEFAULT 0.3,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # Index for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_semantic_category 
                ON semantic_memories(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_type 
                ON episodic_events(event_type)
            """)
            # Add metadata columns (idempotent — safe to run on existing DBs)
            try:
                conn.execute("ALTER TABLE semantic_memories ADD COLUMN metadata TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE episodic_events ADD COLUMN metadata TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
            # Space isolation column (idempotent — safe on existing DBs)
            try:
                conn.execute("ALTER TABLE semantic_memories ADD COLUMN space TEXT DEFAULT 'work'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE episodic_events ADD COLUMN space TEXT DEFAULT 'work'")
            except sqlite3.OperationalError:
                pass
    
    # ── Semantic Memory Operations ──
    
    def save(self, key: str, content: str, category: str = "general", 
             importance: float = 0.5, metadata: dict | None = None, space: str = "work"):
        """Save a memory with its semantic embedding."""
        embedding = _embed_text(f"{key} {content}")
        blob = _vec_to_blob(embedding)
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO semantic_memories (key, content, category, embedding, importance, metadata, space)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET 
                    content=excluded.content,
                    embedding=excluded.embedding,
                    importance=excluded.importance,
                    metadata=excluded.metadata,
                    space=excluded.space,
                    updated_at=datetime('now')
            """, (key, content, category, blob, importance, meta_json, space))
    
    def search(self, query: str, limit: int = 5, 
               category: str = None, min_score: float = 0.1, space: str | None = None) -> list[dict]:
        """Semantic similarity search — finds memories by meaning, not just keywords."""
        query_vec = _embed_text(query)
        
        with sqlite3.connect(self.db_path) as conn:
            if category and space:
                rows = conn.execute(
                    "SELECT id, key, content, category, embedding, importance, access_count, created_at, metadata, last_accessed "
                    "FROM semantic_memories WHERE category=? AND space=?",
                    (category, space),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT id, key, content, category, embedding, importance, access_count, created_at, metadata, last_accessed "
                    "FROM semantic_memories WHERE category=?",
                    (category,),
                ).fetchall()
            elif space:
                rows = conn.execute(
                    "SELECT id, key, content, category, embedding, importance, access_count, created_at, metadata, last_accessed "
                    "FROM semantic_memories WHERE space=?",
                    (space,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, key, content, category, embedding, importance, access_count, created_at, metadata, last_accessed "
                    "FROM semantic_memories"
                ).fetchall()
            
            # Compute similarity scores
            scored = []
            for row in rows:
                mem_vec = _blob_to_vec(row[4])
                # Lazy migration: a legacy vector stored with a different dimension
                # (e.g. the old 128-d hash) is re-embedded on first access so recall
                # keeps working after the upgrade. Only persist when the new vector
                # actually matches the expected dimension (guards the fallback path).
                if len(mem_vec) != EMBED_DIM:
                    _new = _embed_text(f"{row[1]} {row[2]}")
                    if len(_new) == EMBED_DIM:
                        mem_vec = _new
                        conn.execute(
                            "UPDATE semantic_memories SET embedding=? WHERE id=?",
                            (_vec_to_blob(mem_vec), row[0]),
                        )
                sim = _cosine_similarity(query_vec, mem_vec)
                # Boost by importance and access count
                score = sim * (0.7 + 0.3 * row[5])  # importance boost
                # 时间衰减：越久未访问，相关度越低（30 天半衰期）
                _la = row[9] if len(row) > 9 else None
                if _la:
                    try:
                        _la_dt = datetime.fromisoformat(_la)
                        _hours = (datetime.now() - _la_dt).total_seconds() / 3600.0
                        _decay = math.exp(-_hours / (MEMORY_DECAY_HALF_LIFE_DAYS * 24))
                        score *= (0.4 + 0.6 * _decay)
                    except Exception:
                        pass
                score += row[6] * 0.01  # access count boost
                if score >= min_score:
                    scored.append((score, row))
            
            # Sort by score descending
            scored.sort(key=lambda x: -x[0])
            
            # Update access stats for top results
            top_ids = [r[1][0] for r in scored[:limit]]
            if top_ids:
                placeholders = ",".join("?" * len(top_ids))
                conn.execute(
                    f"UPDATE semantic_memories SET access_count = access_count + 1, "
                    f"last_accessed = datetime('now') WHERE id IN ({placeholders})",
                    top_ids,
                )
            
            return [
                {
                    "key": r[1][1],
                    "content": r[1][2],
                    "category": r[1][3],
                    "score": round(r[0], 4),
                    "importance": r[1][5],
                    "access_count": r[1][6],
                    "created_at": r[1][7],
                    "metadata": json.loads(r[1][8]) if r[1][8] else {},
                }
                for r in scored[:limit]
            ]
    
    def recall(self, key: str) -> dict | None:
        """Recall a specific memory by key."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT key, content, category, importance, access_count, created_at, updated_at, metadata "
                "FROM semantic_memories WHERE key=?",
                (key,),
            ).fetchone()
            if not row:
                return None
            return {
                "key": row[0], "content": row[1], "category": row[2],
                "importance": row[3], "access_count": row[4],
                "created_at": row[5], "updated_at": row[6],
                "metadata": json.loads(row[7]) if row[7] else {},
            }
    
    def list_all(self, category: str = None, limit: int = 100, space: str | None = None) -> list[dict]:
        """List all memories, optionally filtered by category."""
        with sqlite3.connect(self.db_path) as conn:
            if category and space:
                rows = conn.execute(
                    "SELECT key, content, category, importance, access_count, created_at, metadata "
                    "FROM semantic_memories WHERE category=? AND space=? ORDER BY updated_at DESC LIMIT ?",
                    (category, space, limit),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT key, content, category, importance, access_count, created_at, metadata "
                    "FROM semantic_memories WHERE category=? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            elif space:
                rows = conn.execute(
                    "SELECT key, content, category, importance, access_count, created_at, metadata "
                    "FROM semantic_memories WHERE space=? ORDER BY updated_at DESC LIMIT ?",
                    (space, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, content, category, importance, access_count, created_at, metadata "
                    "FROM semantic_memories ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"key": r[0], "content": r[1], "category": r[2],
                 "importance": r[3], "access_count": r[4], "created_at": r[5],
                 "metadata": json.loads(r[6]) if r[6] else {}}
                for r in rows
            ]
    
    def delete(self, key: str):
        """Delete a memory by key."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM semantic_memories WHERE key=?", (key,))
    
    def get_stats(self) -> dict:
        """Get memory statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM semantic_memories").fetchone()[0]
            categories = conn.execute(
                "SELECT category, COUNT(*) FROM semantic_memories GROUP BY category"
            ).fetchall()
            episodic_total = conn.execute(
                "SELECT COUNT(*) FROM episodic_events"
            ).fetchone()[0]
            return {
                "semantic_count": total,
                "categories": {r[0]: r[1] for r in categories},
                "episodic_count": episodic_total,
            }
    
    # ── Episodic Memory Operations ──
    
    def record_event(self, event_type: str, description: str, 
                     details: str = "", session_id: str = "",
                     importance: float = 0.3, metadata: dict | None = None, space: str = "work"):
        """Record an episodic event (conversation milestone, decision, etc.)."""
        embedding = _embed_text(f"{event_type} {description} {details}")
        blob = _vec_to_blob(embedding)
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO episodic_events (event_type, description, details, embedding, session_id, importance, metadata, space)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_type, description, details, blob, session_id, importance, meta_json, space))
    
    def search_events(self, query: str, limit: int = 5,
                      event_type: str = None, space: str | None = None) -> list[dict]:
        """Search episodic events by semantic similarity."""
        query_vec = _embed_text(query)
        
        with sqlite3.connect(self.db_path) as conn:
            if event_type and space:
                rows = conn.execute(
                    "SELECT id, event_type, description, details, embedding, session_id, importance, created_at, metadata "
                    "FROM episodic_events WHERE event_type=? AND space=?",
                    (event_type, space),
                ).fetchall()
            elif event_type:
                rows = conn.execute(
                    "SELECT id, event_type, description, details, embedding, session_id, importance, created_at, metadata "
                    "FROM episodic_events WHERE event_type=?",
                    (event_type,),
                ).fetchall()
            elif space:
                rows = conn.execute(
                    "SELECT id, event_type, description, details, embedding, session_id, importance, created_at, metadata "
                    "FROM episodic_events WHERE space=?",
                    (space,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, event_type, description, details, embedding, session_id, importance, created_at, metadata "
                    "FROM episodic_events"
                ).fetchall()
            
            scored = []
            for row in rows:
                mem_vec = _blob_to_vec(row[4])
                # Lazy migration for legacy embeddings (see search() for details).
                if len(mem_vec) != EMBED_DIM:
                    _new = _embed_text(f"{row[1]} {row[2]} {row[3]}")
                    if len(_new) == EMBED_DIM:
                        mem_vec = _new
                        conn.execute(
                            "UPDATE episodic_events SET embedding=? WHERE id=?",
                            (_vec_to_blob(mem_vec), row[0]),
                        )
                sim = _cosine_similarity(query_vec, mem_vec)
                score = sim * (0.7 + 0.3 * row[6])
                scored.append((score, row))
            
            scored.sort(key=lambda x: -x[0])
            
            return [
                {
                    "event_type": r[1][1],
                    "description": r[1][2],
                    "details": r[1][3],
                    "session_id": r[1][5],
                    "importance": r[1][6],
                    "score": round(r[0], 4),
                    "created_at": r[1][7],
                    "metadata": json.loads(r[1][8]) if r[1][8] else {},
                }
                for r in scored[:limit]
            ]
    
    def get_recent_events(self, limit: int = 10) -> list[dict]:
        """Get most recent episodic events."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT event_type, description, details, session_id, importance, created_at, metadata "
                "FROM episodic_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {"event_type": r[0], "description": r[1], "details": r[2],
                 "session_id": r[3], "importance": r[4], "created_at": r[5],
                 "metadata": json.loads(r[6]) if r[6] else {}}
                for r in rows
            ]
    
    def cleanup_old_episodes(self, days: int = 30, keep_important: bool = True):
        """Remove old episodic events to keep the database lean."""
        with sqlite3.connect(self.db_path) as conn:
            if keep_important:
                conn.execute(
                    "DELETE FROM episodic_events WHERE created_at < datetime('now', ?) AND importance < 0.7",
                    (f"-{days} days",),
                )
            else:
                conn.execute(
                    "DELETE FROM episodic_events WHERE created_at < datetime('now', ?)",
                    (f"-{days} days",),
                )
