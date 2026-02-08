import base64
import binascii
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


def strip_data_uri(value: str) -> str:
    if not value:
        return ""
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1].strip()
    return value.strip()


def guess_image_ext(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return ".gif"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return ".webp"
    return ".png"


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(value or "unknown"))
    return cleaned[:120]


class SelfieStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.base_dir = self.data_dir / "base_images"
        self.meta_file = self.data_dir / "base_images.json"
        self.rate_file = self.data_dir / "rate_limit.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def owner_key(scope: str, chat_id: str, person_id: str) -> str:
        if scope == "user":
            return f"user_{safe_id(person_id)}"
        return f"chat_{safe_id(chat_id)}"

    def _read_json(self, file_path: Path) -> Dict[str, Any]:
        if not file_path.exists():
            return {}
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_json(self, file_path: Path, data: Dict[str, Any]) -> None:
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_meta(self) -> Dict[str, str]:
        raw = self._read_json(self.meta_file)
        return {str(k): str(v) for k, v in raw.items()}

    def _set_meta(self, value: Dict[str, str]) -> None:
        self._write_json(self.meta_file, value)

    def save_base_image(self, owner_key: str, image_base64: str) -> Path:
        raw = strip_data_uri(image_base64)
        try:
            image_bytes = base64.b64decode(raw, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("底图不是有效的 base64 图片数据") from exc
        if not image_bytes:
            raise ValueError("底图内容为空")

        ext = guess_image_ext(image_bytes)
        filename = f"{safe_id(owner_key)}{ext}"
        out_path = self.base_dir / filename

        meta = self._get_meta()
        old_name = meta.get(owner_key)
        if old_name and old_name != filename:
            old_path = self.base_dir / old_name
            if old_path.exists():
                old_path.unlink()

        out_path.write_bytes(image_bytes)
        meta[owner_key] = filename
        self._set_meta(meta)
        return out_path

    def get_base_image_path(self, owner_key: str) -> Optional[Path]:
        meta = self._get_meta()
        filename = meta.get(owner_key)
        if not filename:
            return None
        path = self.base_dir / filename
        if not path.exists():
            return None
        return path

    def has_base_image(self, owner_key: str) -> bool:
        return self.get_base_image_path(owner_key) is not None

    def read_base_image_base64(self, owner_key: str) -> Optional[str]:
        path = self.get_base_image_path(owner_key)
        if not path:
            return None
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    def clear_base_image(self, owner_key: str) -> bool:
        meta = self._get_meta()
        filename = meta.pop(owner_key, None)
        self._set_meta(meta)
        if not filename:
            return False
        path = self.base_dir / filename
        if path.exists():
            path.unlink()
        return True

    def get_last_trigger(self, owner_key: str) -> float:
        rate = self._read_json(self.rate_file)
        try:
            return float(rate.get(owner_key, 0.0))
        except Exception:
            return 0.0

    def set_last_trigger(self, owner_key: str, ts: Optional[float] = None) -> None:
        rate = self._read_json(self.rate_file)
        rate[owner_key] = float(ts if ts is not None else time.time())
        self._write_json(self.rate_file, rate)


def find_image_base64_in_message(message: Any) -> Optional[str]:
    visited: set[int] = set()

    def _iter_values(obj: Any):
        oid = id(obj)
        if oid in visited:
            return
        visited.add(oid)

        if obj is None:
            return
        if isinstance(obj, str):
            yield obj
            return
        if isinstance(obj, (int, float, bool)):
            return
        if isinstance(obj, dict):
            for v in obj.values():
                yield from _iter_values(v)
            return
        if isinstance(obj, (list, tuple, set)):
            for v in obj:
                yield from _iter_values(v)
            return
        if hasattr(obj, "__dict__"):
            yield from _iter_values(vars(obj))

    for value in _iter_values(message):
        text = value.strip()
        if not text:
            continue
        if text.startswith("data:image/") and "," in text:
            return strip_data_uri(text)
        compact = strip_data_uri(text)
        if len(compact) < 128:
            continue
        if re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", compact):
            return compact.replace("\n", "").replace("\r", "")
    return None
