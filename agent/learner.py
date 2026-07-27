"""Active learning and evolution module for the AI agent framework.

Enables the agent to learn from its own interactions and improve over time:
- Tracks all interactions with outcomes and scores
- Extracts reusable lessons from notable interactions (high or low scoring)
- Surfaces relevant lessons for current context
- Generates self-improvement reports with actionable suggestions

Persistence: SQLite (data/interactions.db, data/lessons.db)
No external dependencies beyond the standard library + openai client.
"""
import json
import os
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
INTERACTIONS_DB = DATA_DIR / "interactions.db"
LESSONS_DB = DATA_DIR / "lessons.db"

# 经验提炼阈值：以 config 为唯一权威来源（带降级兜底，保证即使 config 缺失也不崩）。
try:
    from config import LESSON_EXTRACTION_HIGH_SCORE, LESSON_EXTRACTION_LOW_SCORE
    SCORE_HIGH_THRESHOLD = LESSON_EXTRACTION_HIGH_SCORE
    SCORE_LOW_THRESHOLD = LESSON_EXTRACTION_LOW_SCORE
except Exception:
    SCORE_HIGH_THRESHOLD = 7
    SCORE_LOW_THRESHOLD = 4

EXTRACTION_PROMPT = """\
Analyze the following AI agent interaction and extract a reusable lesson.

Interaction:
- User request: {user_msg}
- Agent response summary: {assistant_msg}
- Tools used: {tools}
- Outcome: {outcome}
- Score: {score}/10
- Detected patterns: {patterns}

Extract a concise, actionable lesson. Respond in JSON:
{{
  "title": "Short descriptive title",
  "lesson_type": "success_pattern" | "failure_pattern" | "user_preference" | "technical_insight",
  "description": "The lesson in 1-2 sentences",
  "context": "When this lesson applies",
  "action": "What the agent should do differently",
  "keywords": ["relevant", "keywords", "for", "matching"]
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM output, tolerating markdown fences."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _tokenize(text: str) -> set[str]:
    """Simple word-level tokenizer for keyword matching."""
    return set(re.findall(r"\w+", text.lower()))


async def _call_llm(prompt: str, temperature: float = 0.3,
                    max_tokens: int = 4000) -> str:
    """Call the configured LLM via the OpenAI-compatible API."""
    from openai import AsyncOpenAI
    from providers.registry import get as get_provider
    import config

    provider = get_provider(config.DEFAULT_PROVIDER)
    api_key = os.getenv(provider.api_key_env, "")
    client = AsyncOpenAI(api_key=api_key, base_url=provider.base_url)

    response = await client.chat.completions.create(
        model=config.DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# InteractionTracker — SQLite-backed interaction log
# ---------------------------------------------------------------------------

class InteractionTracker:
    """Track all agent interactions in SQLite.

    Schema: id, timestamp, user_msg, assistant_msg, tools_used (JSON),
            outcome (success/partial/failure), score, notes
    """

    def __init__(self, db_path: str | Path = INTERACTIONS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    user_msg TEXT NOT NULL,
                    assistant_msg TEXT DEFAULT '',
                    tools_used TEXT DEFAULT '[]',
                    outcome TEXT DEFAULT 'partial',
                    score REAL DEFAULT 5.0,
                    notes TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interactions_outcome
                ON interactions(outcome)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interactions_timestamp
                ON interactions(timestamp)
            """)

    # -- write operations ---------------------------------------------------

    def record(self, user_msg: str, assistant_msg: str = "",
               tools_used: list[str] | None = None,
               outcome: str = "partial", score: float = 5.0,
               notes: str = "") -> int:
        """Record an interaction. Returns the new row id."""
        tools_json = json.dumps(tools_used or [])
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO interactions "
                "(user_msg, assistant_msg, tools_used, outcome, score, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_msg, assistant_msg, tools_json, outcome, score, notes),
            )
            return cur.lastrowid

    def update_score(self, interaction_id: int, score: float,
                     outcome: str | None = None, notes: str | None = None):
        """Update score and optionally outcome/notes for an existing interaction."""
        with sqlite3.connect(self.db_path) as conn:
            if outcome is not None and notes is not None:
                conn.execute(
                    "UPDATE interactions SET score=?, outcome=?, notes=? "
                    "WHERE id=?",
                    (score, outcome, notes, interaction_id),
                )
            elif outcome is not None:
                conn.execute(
                    "UPDATE interactions SET score=?, outcome=? WHERE id=?",
                    (score, outcome, interaction_id),
                )
            elif notes is not None:
                conn.execute(
                    "UPDATE interactions SET score=?, notes=? WHERE id=?",
                    (score, notes, interaction_id),
                )
            else:
                conn.execute(
                    "UPDATE interactions SET score=? WHERE id=?",
                    (score, interaction_id),
                )

    # -- read operations ----------------------------------------------------

    def get(self, interaction_id: int) -> dict | None:
        """Fetch a single interaction by id."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, timestamp, user_msg, assistant_msg, tools_used, "
                "outcome, score, notes FROM interactions WHERE id=?",
                (interaction_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_recent(self, n: int = 10) -> list[dict]:
        """Return the *n* most recent interactions."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, user_msg, assistant_msg, tools_used, "
                "outcome, score, notes FROM interactions "
                "ORDER BY timestamp DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_outcome(self, outcome: str, limit: int = 20) -> list[dict]:
        """Return interactions filtered by outcome label."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, user_msg, assistant_msg, tools_used, "
                "outcome, score, notes FROM interactions "
                "WHERE outcome=? ORDER BY timestamp DESC LIMIT ?",
                (outcome, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_since(self, since: str, limit: int = 500) -> list[dict]:
        """Return interactions since a timestamp (ISO-8601 string)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, user_msg, assistant_msg, tools_used, "
                "outcome, score, notes FROM interactions "
                "WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # -- analytics ----------------------------------------------------------

    def get_stats(self) -> dict:
        """Aggregate statistics over all recorded interactions."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM interactions",
            ).fetchone()[0]
            outcome_counts = dict(
                conn.execute(
                    "SELECT outcome, COUNT(*) FROM interactions GROUP BY outcome",
                ).fetchall()
            )
            avg_score = conn.execute(
                "SELECT AVG(score) FROM interactions",
            ).fetchone()[0] or 0.0
            tools_rows = conn.execute(
                "SELECT tools_used FROM interactions WHERE tools_used != '[]'",
            ).fetchall()
        tool_counter: Counter = Counter()
        for (tools_json,) in tools_rows:
            try:
                tool_counter.update(json.loads(tools_json))
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "total": total,
            "outcomes": outcome_counts,
            "avg_score": round(avg_score, 2),
            "tool_usage": dict(tool_counter.most_common(20)),
        }

    def get_failure_patterns(self, limit: int = 10) -> list[dict]:
        """Find the most common failure patterns."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT user_msg, assistant_msg, tools_used, notes, score, "
                "timestamp FROM interactions "
                "WHERE outcome='failure' ORDER BY timestamp DESC LIMIT ?",
                (limit * 5,),
            ).fetchall()

        # Cluster by shared tool names
        tool_clusters: dict[str, list] = {}
        for row in rows:
            try:
                tools = json.loads(row[2]) if row[2] else []
            except (json.JSONDecodeError, TypeError):
                tools = []
            key = ",".join(sorted(tools)) if tools else "no_tools"
            tool_clusters.setdefault(key, []).append(row)

        patterns = []
        for tool_key, entries in tool_clusters.items():
            patterns.append({
                "tools": tool_key,
                "count": len(entries),
                "avg_score": round(
                    sum(e[4] for e in entries) / len(entries), 2
                ),
                "examples": [
                    {"user_msg": e[0][:200], "notes": e[3][:200]}
                    for e in entries[:3]
                ],
            })
        patterns.sort(key=lambda p: -p["count"])
        return patterns[:limit]

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        try:
            tools = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            tools = []
        return {
            "id": row[0],
            "timestamp": row[1],
            "user_msg": row[2],
            "assistant_msg": row[3],
            "tools_used": tools,
            "outcome": row[5],
            "score": row[6],
            "notes": row[7],
        }


# ---------------------------------------------------------------------------
# LessonsDB — extracted lessons store
# ---------------------------------------------------------------------------

class LessonsDB:
    """SQLite store for lessons extracted from interactions.

    Schema:
        lessons(id, timestamp, interaction_id, title, lesson_type,
                description, context, action, score, keywords)
        lesson_keywords(lesson_id, keyword)
    """

    def __init__(self, db_path: str | Path = LESSONS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    interaction_id INTEGER,
                    title TEXT NOT NULL,
                    lesson_type TEXT DEFAULT 'general',
                    description TEXT NOT NULL,
                    context TEXT DEFAULT '',
                    action TEXT DEFAULT '',
                    score REAL DEFAULT 5.0,
                    keywords TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lesson_keywords (
                    lesson_id INTEGER,
                    keyword TEXT,
                    FOREIGN KEY(lesson_id) REFERENCES lessons(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lesson_keywords_keyword
                ON lesson_keywords(keyword)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lessons_type
                ON lessons(lesson_type)
            """)

    def save_lesson(self, lesson_data: dict, interaction_id: int | None = None,
                    score: float = 5.0) -> int:
        """Persist a lesson and its keyword index. Returns the lesson id."""
        keywords = lesson_data.get("keywords", [])
        keywords_json = json.dumps(keywords)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO lessons "
                "(interaction_id, title, lesson_type, description, context, "
                "action, score, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    interaction_id,
                    lesson_data.get("title", "Untitled"),
                    lesson_data.get("lesson_type", "general"),
                    lesson_data.get("description", ""),
                    lesson_data.get("context", ""),
                    lesson_data.get("action", ""),
                    score,
                    keywords_json,
                ),
            )
            lesson_id = cur.lastrowid
            for kw in keywords:
                conn.execute(
                    "INSERT INTO lesson_keywords (lesson_id, keyword) "
                    "VALUES (?, ?)",
                    (lesson_id, kw.lower()),
                )
            return lesson_id

    def get_relevant(self, context: str, limit: int = 5) -> list[dict]:
        """Find lessons relevant to *context* via keyword overlap."""
        query_tokens = _tokenize(context)
        if not query_tokens:
            return []

        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" * len(query_tokens))
            rows = conn.execute(
                "SELECT DISTINCT l.id, l.title, l.lesson_type, "
                "l.description, l.context, l.action, l.score, "
                "l.keywords, l.timestamp "
                "FROM lessons l "
                "JOIN lesson_keywords lk ON l.id = lk.lesson_id "
                f"WHERE lk.keyword IN ({placeholders}) "
                "ORDER BY l.score DESC, l.timestamp DESC",
                [kw.lower() for kw in query_tokens],
            ).fetchall()

        # Rank by keyword overlap ratio
        scored: list[tuple[float, tuple]] = []
        for row in rows:
            try:
                lesson_kws = set(json.loads(row[7]))
            except (json.JSONDecodeError, TypeError):
                lesson_kws = set()
            overlap = len(query_tokens & lesson_kws)
            if overlap > 0:
                relevance = overlap / max(len(query_tokens), 1)
                # Boost by lesson score
                relevance *= 0.5 + 0.5 * (row[6] / 10.0)
                scored.append((relevance, row))

        scored.sort(key=lambda x: -x[0])
        return [self._row_to_dict(r, round(score, 4))
                for score, r in scored[:limit]]

    def get_all(self, limit: int = 50) -> list[dict]:
        """Return all lessons, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, lesson_type, description, context, "
                "action, score, keywords, timestamp "
                "FROM lessons ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_type(self, lesson_type: str, limit: int = 20) -> list[dict]:
        """Return lessons filtered by type."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, lesson_type, description, context, "
                "action, score, keywords, timestamp "
                "FROM lessons WHERE lesson_type=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (lesson_type, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM lessons",
            ).fetchone()[0]

    @staticmethod
    def _row_to_dict(row: tuple, relevance: float | None = None) -> dict:
        try:
            keywords = json.loads(row[7]) if row[7] else []
        except (json.JSONDecodeError, TypeError):
            keywords = []
        d = {
            "id": row[0],
            "title": row[1],
            "lesson_type": row[2],
            "description": row[3],
            "context": row[4],
            "action": row[5],
            "score": row[6],
            "keywords": keywords,
            "timestamp": row[8],
        }
        if relevance is not None:
            d["relevance"] = relevance
        return d


# ---------------------------------------------------------------------------
# LearningEngine — analysis, lesson extraction, improvement reports
# ---------------------------------------------------------------------------

class LearningEngine:
    """Core engine that ties interaction tracking to lesson extraction."""

    def __init__(self):
        _ensure_data_dir()
        self.tracker = InteractionTracker()
        self.lessons_db = LessonsDB()

    # -- interaction analysis -----------------------------------------------

    def analyze_interaction(self, user_msg: str, assistant_msg: str,
                            tool_calls: list[dict] | None = None,
                            outcome: str = "success") -> dict:
        """Analyze a single conversation turn.

        Detects patterns (repeated questions, failed tools, user corrections,
        successful strategies) and scores the interaction 1-10.
        """
        tool_calls = tool_calls or []
        tools_used = [t.get("name", "unknown") for t in tool_calls]
        failed_tools = [
            t.get("name", "unknown")
            for t in tool_calls
            if t.get("error") or t.get("status") == "failed"
        ]

        # --- base score from outcome ---
        base_scores = {"success": 7.0, "partial": 5.0, "failure": 3.0}
        score = base_scores.get(outcome, 5.0)

        # --- tool adjustments ---
        if tool_calls and not failed_tools:
            score += 1.0
        if failed_tools:
            score -= len(failed_tools) * 0.5

        # --- user-message signals ---
        user_lower = user_msg.lower()
        correction_signals = [
            "no,", "no ", "wrong", "incorrect", "that's not",
            "不对", "不是", "错了", "重新", "再试",
        ]
        if any(sig in user_lower for sig in correction_signals):
            score -= 1.5

        repeat_signals = ["again", "还是一样的", "还是不行", "same error",
                          "still not", "i said"]
        if any(sig in user_lower for sig in repeat_signals):
            score -= 1.0

        positive_signals = ["谢谢", "thank", "完美", "perfect", "great",
                            "exactly", "正好", "太好了"]
        if any(sig in user_lower for sig in positive_signals):
            score += 1.0

        score = max(1.0, min(10.0, round(score, 1)))

        # --- pattern detection ---
        patterns: list[str] = []
        if failed_tools:
            patterns.append(f"failed_tools:{','.join(failed_tools)}")
        if any(sig in user_lower for sig in correction_signals):
            patterns.append("user_correction")
        if any(sig in user_lower for sig in repeat_signals):
            patterns.append("repeated_question")
        if any(sig in user_lower for sig in positive_signals):
            patterns.append("positive_feedback")
        if outcome == "success" and not failed_tools:
            patterns.append("clean_success")
        if len(tool_calls) > 3 and outcome == "success":
            patterns.append("complex_task_solved")

        # --- persist ---
        notes = f"Patterns: {', '.join(patterns)}" if patterns else ""
        interaction_id = self.tracker.record(
            user_msg=user_msg,
            assistant_msg=assistant_msg[:1000],
            tools_used=tools_used,
            outcome=outcome,
            score=score,
            notes=notes,
        )

        return {
            "interaction_id": interaction_id,
            "score": score,
            "patterns": patterns,
            "notable": score > SCORE_HIGH_THRESHOLD
                       or score < SCORE_LOW_THRESHOLD,
        }

    async def extract_lesson(self, interaction_data: dict) -> str:
        """Use the LLM to extract a reusable lesson from a notable interaction.

        Only triggers when the interaction score is >8 or <4.
        """
        score = interaction_data.get("score", 5.0)
        if not (score > SCORE_HIGH_THRESHOLD or score < SCORE_LOW_THRESHOLD):
            return f"Interaction score ({score}) is not notable " \
                   f"(need >{SCORE_HIGH_THRESHOLD} or <{SCORE_LOW_THRESHOLD})"

        # Resolve full interaction record when only an id was given
        if "user_msg" not in interaction_data and "id" in interaction_data:
            record = self.tracker.get(interaction_data["id"])
            if record:
                interaction_data.update(record)

        prompt = EXTRACTION_PROMPT.format(
            user_msg=interaction_data.get("user_msg", "")[:500],
            assistant_msg=interaction_data.get("assistant_msg", "")[:500],
            tools=interaction_data.get("tools_used", []),
            outcome=interaction_data.get("outcome", "unknown"),
            score=score,
            patterns=interaction_data.get("patterns", []),
        )

        try:
            response_text = await _call_llm(prompt, temperature=0.4)
            lesson_data = _extract_json(response_text)
            if not lesson_data or not lesson_data.get("title"):
                return "Failed to extract lesson: invalid LLM response"

            lesson_id = self.lessons_db.save_lesson(
                lesson_data,
                interaction_id=interaction_data.get("id")
                               or interaction_data.get("interaction_id"),
                score=score,
            )
            return (
                f"Lesson #{lesson_id} extracted: "
                f"[{lesson_data.get('lesson_type', 'general')}] "
                f"{lesson_data['title']} — {lesson_data.get('description', '')}"
            )
        except Exception as e:
            return f"Failed to extract lesson: {e}"

    def get_relevant_lessons(self, context: str, limit: int = 5) -> list[dict]:
        """Search for lessons relevant to the current context.

        Uses keyword overlap for matching (lightweight, no embeddings).
        """
        return self.lessons_db.get_relevant(context, limit)

    def generate_self_improvement_report(
        self, days_lookback: int = 7,
    ) -> dict:
        """Analyse recent interactions and produce improvement suggestions.

        Returns a structured dict with stats, failure patterns,
        successful strategies, and suggested skill additions.
        """
        since = (
            datetime.now() - timedelta(days=days_lookback)
        ).strftime("%Y-%m-%d %H:%M:%S")

        interactions = self.tracker.get_since(since)
        stats = self.tracker.get_stats()
        failure_patterns = self.tracker.get_failure_patterns()

        # --- derive high-level summaries ---
        successes = [i for i in interactions if i["outcome"] == "success"]
        failures = [i for i in interactions if i["outcome"] == "failure"]

        success_tools: Counter = Counter()
        for i in successes:
            success_tools.update(i.get("tools_used", []))

        failure_tools: Counter = Counter()
        for i in failures:
            failure_tools.update(i.get("tools_used", []))

        # Most successful strategies: tools that appear mostly in successes
        successful_strategies = [
            {"tool": tool, "success_count": cnt}
            for tool, cnt in success_tools.most_common(5)
        ]

        # Suggested skill additions: tools that fail often but also succeed
        suggested_skills: list[dict] = []
        for tool, fail_cnt in failure_tools.most_common(5):
            s_cnt = success_tools.get(tool, 0)
            if s_cnt > 0:
                suggested_skills.append({
                    "tool": tool,
                    "failure_rate": round(
                        fail_cnt / (fail_cnt + s_cnt), 2
                    ),
                    "suggestion": (
                        f"Consider improving {tool} reliability "
                        f"(fails {fail_cnt}/{fail_cnt + s_cnt} times)"
                    ),
                })

        return {
            "period_days": days_lookback,
            "total_interactions": len(interactions),
            "outcome_distribution": stats.get("outcomes", {}),
            "average_score": stats.get("avg_score", 0),
            "most_used_tools": stats.get("tool_usage", {}),
            "failure_patterns": failure_patterns,
            "successful_strategies": successful_strategies,
            "suggested_skills": suggested_skills,
            "total_lessons_learned": self.lessons_db.count(),
        }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

_engine: LearningEngine | None = None


def _get_engine() -> LearningEngine:
    """Lazy-init the global LearningEngine singleton."""
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine


async def handle_learn_from_interaction(
    interaction_id: int = 0,
    user_msg: str = "",
    assistant_msg: str = "",
    outcome: str = "success",
    tools_used: str = "",
) -> str:
    """Manually trigger learning from a specific interaction."""
    try:
        engine = _get_engine()

        if interaction_id > 0:
            record = engine.tracker.get(interaction_id)
            if not record:
                return f"Interaction #{interaction_id} not found."
            analysis = engine.analyze_interaction(
                user_msg=record["user_msg"],
                assistant_msg=record["assistant_msg"],
                outcome=record["outcome"],
            )
        elif user_msg:
            tools_list = (
                [t.strip() for t in tools_used.split(",") if t.strip()]
                if tools_used else []
            )
            analysis = engine.analyze_interaction(
                user_msg=user_msg,
                assistant_msg=assistant_msg,
                tool_calls=[{"name": t} for t in tools_list],
                outcome=outcome,
            )
        else:
            return "Provide interaction_id or user_msg to learn from."

        parts = [
            f"Analyzed interaction #{analysis['interaction_id']}",
            f"Score: {analysis['score']}/10",
            f"Patterns: {', '.join(analysis['patterns']) or 'none'}",
        ]

        if analysis["notable"]:
            lesson_result = await engine.extract_lesson({
                "id": analysis["interaction_id"],
                "score": analysis["score"],
                "patterns": analysis["patterns"],
            })
            parts.append(lesson_result)
        else:
            parts.append(
                "Score not notable enough for lesson extraction "
                f"(need >{SCORE_HIGH_THRESHOLD} or <{SCORE_LOW_THRESHOLD})."
            )

        return "\n".join(parts)

    except Exception as e:
        return f"Learning failed: {e}"


async def handle_get_lessons(
    context_description: str,
    limit: int = 5,
) -> str:
    """Retrieve learned lessons relevant to the current context."""
    try:
        engine = _get_engine()
        lessons = engine.get_relevant_lessons(context_description, limit)
        if not lessons:
            return (
                f"No lessons found for context: {context_description}\n"
                f"Total lessons in database: {engine.lessons_db.count()}"
            )
        lines = [f"Found {len(lessons)} relevant lesson(s):"]
        for lesson in lessons:
            lines.append(
                f"\n[{lesson['lesson_type']}] {lesson['title']} "
                f"(relevance: {lesson.get('relevance', 0):.2f})"
            )
            lines.append(f"  {lesson['description']}")
            if lesson.get("action"):
                lines.append(f"  Action: {lesson['action']}")
            if lesson.get("context"):
                lines.append(f"  When: {lesson['context']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve lessons: {e}"


async def handle_self_improvement_report(days_lookback: int = 7) -> str:
    """Generate a report on agent performance and improvement areas."""
    try:
        engine = _get_engine()
        report = engine.generate_self_improvement_report(days_lookback)

        lines = [
            f"=== Self-Improvement Report (last {report['period_days']} days) ===",
            "",
            f"Total interactions: {report['total_interactions']}",
            f"Average score: {report['average_score']}/10",
            f"Lessons learned: {report['total_lessons_learned']}",
            "",
            "--- Outcome Distribution ---",
        ]
        for outcome, count in report.get("outcome_distribution", {}).items():
            lines.append(f"  {outcome}: {count}")

        lines.append("")
        lines.append("--- Most Used Tools ---")
        for tool, count in report.get("most_used_tools", {}).items():
            lines.append(f"  {tool}: {count}")

        lines.append("")
        lines.append("--- Failure Patterns ---")
        for pattern in report.get("failure_patterns", []):
            lines.append(
                f"  [{pattern['tools']}] {pattern['count']} failures "
                f"(avg score: {pattern['avg_score']})"
            )
            for ex in pattern.get("examples", []):
                lines.append(f"    Example: {ex['user_msg'][:100]}")

        lines.append("")
        lines.append("--- Successful Strategies ---")
        for strategy in report.get("successful_strategies", []):
            lines.append(
                f"  {strategy['tool']}: {strategy['success_count']} successes"
            )

        lines.append("")
        lines.append("--- Suggested Skill Additions ---")
        for skill in report.get("suggested_skills", []):
            lines.append(f"  {skill['suggestion']}")

        if not report.get("failure_patterns") \
                and not report.get("suggested_skills"):
            lines.append("  No major issues detected.")

        return "\n".join(lines)

    except Exception as e:
        return f"Failed to generate report: {e}"


async def handle_record_outcome(
    task_description: str,
    outcome: str,
    notes: str = "",
) -> str:
    """Record whether a task succeeded or failed."""
    try:
        if outcome not in ("success", "failure", "partial"):
            return "Outcome must be 'success', 'failure', or 'partial'."

        engine = _get_engine()
        score_map = {"success": 8.0, "partial": 5.0, "failure": 2.0}
        interaction_id = engine.tracker.record(
            user_msg=task_description,
            outcome=outcome,
            score=score_map.get(outcome, 5.0),
            notes=notes,
        )
        msg = (
            f"Recorded outcome for interaction #{interaction_id}: "
            f"{outcome}"
        )
        if notes:
            msg += f" — {notes}"
        return msg
    except Exception as e:
        return f"Failed to record outcome: {e}"


# ---------------------------------------------------------------------------
# Tool registration (AST-based discovery)
# ---------------------------------------------------------------------------

def register(registry):
    registry.register(
        name="learn_from_interaction",
        description=(
            "Manually trigger learning from a specific interaction. Analyzes the "
            "interaction quality and extracts a reusable lesson when the score is "
            "notably high (>8) or low (<4). Provide either an existing "
            "interaction_id or describe a new interaction inline."
        ),
        parameters={
            "type": "object",
            "properties": {
                "interaction_id": {
                    "type": "integer",
                    "description": (
                        "ID of a previously recorded interaction to analyze"
                    ),
                },
                "user_msg": {
                    "type": "string",
                    "description": "User message (for ad-hoc analysis)",
                },
                "assistant_msg": {
                    "type": "string",
                    "description": "Assistant response (for ad-hoc analysis)",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failure"],
                    "description": "Task outcome (default: success)",
                },
                "tools_used": {
                    "type": "string",
                    "description": (
                        "Comma-separated tool names that were invoked"
                    ),
                },
            },
        },
        handler=handle_learn_from_interaction,
        is_async=True,
        toolset="learning",
        emoji="\U0001f393",  # graduation cap
    )

    registry.register(
        name="get_lessons",
        description=(
            "Retrieve learned lessons relevant to the current context. Searches "
            "through previously extracted lessons by keyword matching. Useful "
            "before starting a task to recall past successes and failures."
        ),
        parameters={
            "type": "object",
            "properties": {
                "context_description": {
                    "type": "string",
                    "description": (
                        "Description of the current task or context to find "
                        "relevant lessons for"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lessons to return (default 5)",
                },
            },
            "required": ["context_description"],
        },
        handler=handle_get_lessons,
        is_async=True,
        toolset="learning",
        emoji="\U0001f4da",  # books
    )

    registry.register(
        name="self_improvement_report",
        description=(
            "Generate a report on agent performance and improvement areas. "
            "Analyzes recent interactions to identify common failure patterns, "
            "successful strategies, and suggests potential skill additions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "days_lookback": {
                    "type": "integer",
                    "description": (
                        "Number of days to look back (default 7)"
                    ),
                },
            },
        },
        handler=handle_self_improvement_report,
        is_async=True,
        toolset="learning",
        emoji="\U0001f4c8",  # chart increasing
    )

    registry.register(
        name="record_outcome",
        description=(
            "Record whether a task succeeded or failed. This feeds into the "
            "learning engine to track performance over time and identify "
            "improvement areas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Brief description of what was attempted",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "partial"],
                    "description": "Whether the task succeeded, failed, or was partial",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about what happened",
                },
            },
            "required": ["task_description", "outcome"],
        },
        handler=handle_record_outcome,
        is_async=True,
        toolset="learning",
        emoji="\U0001f4dd",  # memo
    )
