"""Session persistence — saves/loads sessions as JSON files."""
import json
from pathlib import Path
from datetime import datetime, timezone


class SessionStore:
    """Persist sessions to data/sessions/ as individual JSON files."""

    def __init__(self, base_dir: str = "data/sessions"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def save(self, session_id: str, messages: list[dict], created_at: str = ""):
        """Save a session to disk."""
        data = {
            "id": session_id,
            "messages": messages,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._session_path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def load(self, session_id: str) -> dict | None:
        """Load a session from disk. Returns None if not found."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def load_all(self) -> list[dict]:
        """Load all sessions from disk."""
        sessions = []
        for path in self.base_dir.glob("*.json"):
            try:
                sessions.append(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return sessions

    def delete(self, session_id: str):
        """Delete a session file."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()

    def list_ids(self) -> list[str]:
        """List all saved session IDs."""
        return [p.stem for p in self.base_dir.glob("*.json")]
