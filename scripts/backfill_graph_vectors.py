"""P1-2: 回填统一 512 维 graph_vec，使知识球体可绘制真实的跨类型余弦边。

- 仅新增独立列 graph_vec（BLOB, float32, 512 维），绝不改动语义记忆自有的 embedding 列。
- 使用 knowledge.embedding.get_embedding（BAAI/bge-small-zh-v1.5, 512d），与 knowledge.embedding 同模型同向量空间。
- 幂等：已填过的行跳过；重复运行安全。

用法:
    cd /opt/agent-framework && .venv/bin/python scripts/backfill_graph_vectors.py
"""
import sqlite3
import numpy as np
from pathlib import Path

from knowledge.embedding import get_embedding

HOME = Path("/opt/agent-framework")
DATA = HOME / "data"
DIM = 512


def add_col(db_path: Path, table: str, col: str = "graph_vec"):
    c = sqlite3.connect(db_path)
    try:
        cur = c.execute(f"PRAGMA table_info({table})").fetchall()
        if not any(r[1] == col for r in cur):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} BLOB")
            c.commit()
            print(f"  + 新增列 {col} -> {table}")
        else:
            print(f"  = 列 {col} 已存在 -> {table}")
    finally:
        c.close()


def backfill(db_path: Path, table: str, text_fn, pk="id", col="graph_vec", batch=50):
    c = sqlite3.connect(db_path)
    try:
        rows = c.execute(f"SELECT * FROM {table}").fetchall()
        cols = [d[1] for d in c.execute(f"PRAGMA table_info({table})").fetchall()]
        n, done = 0, 0
        for row in rows:
            rec = dict(zip(cols, row))
            if rec.get(col):
                continue
            text = text_fn(rec)
            if not text or not text.strip():
                continue
            try:
                vec = np.array(get_embedding(text[:2000]), dtype=np.float32)
                c.execute(f"UPDATE {table} SET {col}=? WHERE {pk}=?", (vec.tobytes(), rec.get(pk)))
            except Exception as e:
                print(f"  ! 嵌入失败 {table}/{rec.get(pk)}: {e}")
                continue
            done += 1
            n += 1
            if n % batch == 0:
                c.commit()
        c.commit()
        print(f"  {table}: 回填 {done} 条向量（共 {len(rows)} 行）")
    finally:
        c.close()


def main():
    print("== 回填 graph_vec (512d bge-small-zh) ==")
    # 核心记忆
    add_col(DATA / "memory.db", "memories")
    backfill(DATA / "memory.db", "memories", lambda r: r.get("content") or "")

    # 语义记忆 + 情景记忆
    add_col(DATA / "semantic_memory.db", "semantic_memories")
    backfill(DATA / "semantic_memory.db", "semantic_memories", lambda r: r.get("content") or "")
    add_col(DATA / "semantic_memory.db", "episodic_events")
    backfill(
        DATA / "semantic_memory.db", "episodic_events",
        lambda r: f"{r.get('event_type') or ''} {(r.get('description') or '')} {(r.get('details') or '')}",
        pk="id",
    )

    # 自学习经验
    add_col(DATA / "lessons.db", "lessons")
    backfill(
        DATA / "lessons.db", "lessons",
        lambda r: " ".join([r.get("title") or "", r.get("description") or "", r.get("action") or ""]),
        pk="id",
    )

    print("== 完成 ==")


if __name__ == "__main__":
    main()
