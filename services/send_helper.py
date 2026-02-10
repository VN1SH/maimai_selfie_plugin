import base64
import binascii
import tempfile
from pathlib import Path
from typing import Any, Optional

try:
    from src.plugin_system.apis import get_logger, send_api
except Exception:  # pragma: no cover
    from src.plugin_system import get_logger, send_api

from .storage import guess_image_ext, strip_data_uri

LOGGER = get_logger("maimai_selfie_plugin.send")


def normalize_image_base64(image_b64: str) -> str:
    compact = strip_data_uri(str(image_b64 or ""))
    compact = "".join(compact.split())
    return compact


async def _send_with_primary_api(stream_id: str, image_b64: str, reply_message: Optional[Any] = None) -> bool:
    return bool(
        await send_api.image_to_stream(
            image_base64=image_b64,
            stream_id=stream_id,
            storage_message=True,
            set_reply=bool(reply_message),
            reply_message=reply_message,
        )
    )


async def _send_with_file_api(stream_id: str, image_path: Path, reply_message: Optional[Any] = None) -> bool:
    kwargs = {
        "stream_id": stream_id,
        "storage_message": True,
        "set_reply": bool(reply_message),
        "reply_message": reply_message,
    }
    candidates = [
        ("image_file_to_stream", {"image_path": str(image_path), **kwargs}),
        ("file_image_to_stream", {"file_path": str(image_path), **kwargs}),
        ("file_to_stream", {"file_path": str(image_path), **kwargs}),
        ("local_image_to_stream", {"image_path": str(image_path), **kwargs}),
    ]
    for method_name, call_kwargs in candidates:
        method = getattr(send_api, method_name, None)
        if method is None:
            continue
        try:
            result = method(**call_kwargs)
            if hasattr(result, "__await__"):
                result = await result
            if result:
                return True
        except TypeError:
            # 某些接口不支持全部 kwargs，降级重试最小参数
            minimal = {k: v for k, v in call_kwargs.items() if k in ("stream_id", "file_path", "image_path")}
            try:
                result = method(**minimal)
                if hasattr(result, "__await__"):
                    result = await result
                if result:
                    return True
            except Exception:
                continue
        except Exception:
            continue
    return False


async def send_image_base64(stream_id: str, image_b64: str, reply_message: Optional[Any] = None) -> tuple[bool, str]:
    normalized = normalize_image_base64(image_b64)
    if not normalized:
        return False, "图片内容为空"

    try:
        if await _send_with_primary_api(stream_id, normalized, reply_message=reply_message):
            return True, "ok"
        LOGGER.warning("primary image sending api returned false")
    except Exception as exc:
        LOGGER.warning("primary image sending api failed", error=str(exc))

    temp_path: Optional[Path] = None
    try:
        image_bytes = base64.b64decode(normalized, validate=False)
        if not image_bytes:
            return False, "图片数据解码为空"
        ext = guess_image_ext(image_bytes)
        with tempfile.NamedTemporaryFile(prefix="maimai_selfie_", suffix=ext, delete=False) as f:
            f.write(image_bytes)
            temp_path = Path(f.name)

        if await _send_with_file_api(stream_id, temp_path, reply_message=reply_message):
            return True, "ok"
        LOGGER.error("all file-image sending fallback methods failed", temp_path=str(temp_path))
        return False, "图片发送失败（主接口和文件兜底均失败）"
    except (binascii.Error, ValueError) as exc:
        LOGGER.error("invalid base64 image data", error=str(exc))
        return False, "图片数据不是有效 base64"
    except Exception as exc:
        LOGGER.error("unexpected image sending fallback error", error=str(exc))
        return False, f"图片发送异常: {exc}"
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
