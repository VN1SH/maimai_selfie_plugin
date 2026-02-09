import json
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .storage import safe_id


class RateLimiter:
    def __init__(self, data_dir: Path, scope_id: str) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        safe_scope = safe_id(scope_id or "unknown")
        self.file_path = self.data_dir / f"ratelimit_{safe_scope}.json"

    def check(self, window_hours: int, max_images: int, now_ts: Optional[float] = None) -> Tuple[bool, int]:
        now = float(now_ts) if now_ts is not None else time.time()
        window_seconds = max(0, int(window_hours) * 3600)
        timestamps = self._load()
        timestamps = self._prune(timestamps, window_seconds, now)
        self._save(timestamps)
        count = len(timestamps)
        limited = max_images > 0 and count >= max_images
        return limited, count

    def record(self, window_hours: int, now_ts: Optional[float] = None) -> int:
        now = float(now_ts) if now_ts is not None else time.time()
        window_seconds = max(0, int(window_hours) * 3600)
        timestamps = self._load()
        timestamps.append(now)
        timestamps = self._prune(timestamps, window_seconds, now)
        self._save(timestamps)
        return len(timestamps)

    def _load(self) -> List[float]:
        if not self.file_path.exists():
            return []
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, list):
            return [float(ts) for ts in payload if isinstance(ts, (int, float))]
        if isinstance(payload, dict):
            values = payload.get("timestamps", [])
            if isinstance(values, list):
                return [float(ts) for ts in values if isinstance(ts, (int, float))]
        return []

    def _save(self, timestamps: List[float]) -> None:
        payload = {"timestamps": timestamps}
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _prune(timestamps: List[float], window_seconds: int, now: float) -> List[float]:
        if window_seconds <= 0:
            return timestamps
        threshold = now - window_seconds
        return [ts for ts in timestamps if ts >= threshold]
