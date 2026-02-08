from pathlib import Path
from typing import Any, List, Optional, Tuple

from src.plugin_system import BaseCommand

try:
    from src.plugin_system.apis import get_logger, message_api, person_api, send_api
except Exception:  # pragma: no cover
    from src.plugin_system import get_logger, message_api, person_api, send_api

from ..services.storage import SelfieStorage, find_image_base64_in_message

LOGGER = get_logger("maimai_selfie_plugin.command")


class SelfieBaseCommand(BaseCommand):
    command_name = "selfie_base"
    command_description = "管理自拍角色底图：/selfie_base set|show|clear"
    command_pattern = r"^/selfie_base(?:\s+(?P<action>set|show|clear))?\s*$"

    async def execute(self) -> Tuple[bool, Optional[str], bool]:
        action = (self.matched_groups or {}).get("action") if hasattr(self, "matched_groups") else None
        action = (action or "show").strip().lower()

        try:
            if action == "set":
                return await self._handle_set()
            if action == "clear":
                return await self._handle_clear()
            return await self._handle_show()
        except Exception as exc:
            LOGGER.error("selfie_base command failed", error=str(exc))
            await self.send_text("❌ 处理底图命令失败，请稍后再试。")
            return False, f"selfie_base 执行异常: {exc}", True

    def _storage(self) -> SelfieStorage:
        plugin_dir = Path(__file__).resolve().parents[1]
        data_dir = plugin_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return SelfieStorage(data_dir)

    def _scope(self) -> str:
        scope = str(self.get_config("selfie.base_image_scope", "chat")).strip().lower()
        return "user" if scope == "user" else "chat"

    def _person_id(self) -> str:
        platform = str(getattr(self, "platform", "qq"))
        user_id_raw = str(getattr(self, "user_id", ""))
        try:
            return person_api.get_person_id(platform, int(user_id_raw))
        except Exception:
            return f"{platform}_{user_id_raw}"

    def _owner_key(self) -> str:
        scope = self._scope()
        chat_id = str(getattr(self, "chat_id", "") or getattr(getattr(self, "chat_stream", None), "stream_id", ""))
        return SelfieStorage.owner_key(scope=scope, chat_id=chat_id, person_id=self._person_id())

    def _chat_id(self) -> str:
        return str(getattr(self, "chat_id", "") or getattr(getattr(self, "chat_stream", None), "stream_id", ""))

    def _stream_id(self) -> str:
        stream = getattr(self, "chat_stream", None)
        return str(getattr(stream, "stream_id", "") or self._chat_id())

    def _command_reply_to_id(self) -> str:
        command_message = getattr(self, "command_message", None) or getattr(self, "action_message", None) or {}
        if not isinstance(command_message, dict):
            return ""
        for key in ("reply_to", "reply_message_id", "reply_message", "reply_message_id_str"):
            value = command_message.get(key)
            if value:
                return str(value)
        return ""

    def _load_recent_messages(self, limit: int = 50) -> List[Any]:
        chat_id = self._chat_id()
        if not chat_id:
            return []
        try:
            return message_api.get_recent_messages(chat_id=chat_id, hours=72.0, limit=limit, limit_mode="latest", filter_mai=False)
        except TypeError:
            return message_api.get_recent_messages(chat_id, 72.0, limit, "latest", False)

    def _find_message_by_id(self, messages: List[Any], message_id: str) -> Optional[Any]:
        for msg in messages:
            if str(self._msg_value(msg, "message_id", "")) == str(message_id):
                return msg
        return None

    def _pick_latest_image_message(self, messages: List[Any]) -> Optional[Any]:
        sorted_msgs = sorted(messages, key=lambda x: float(self._msg_value(x, "time", 0.0)))
        for msg in reversed(sorted_msgs):
            text = str(self._msg_value(msg, "processed_plain_text", "") or "").strip()
            if text.startswith("/"):
                continue
            image_b64 = find_image_base64_in_message(msg)
            if image_b64:
                return msg
        return None

    def _latest_message_for_reply(self, messages: List[Any]) -> Optional[Any]:
        if not messages:
            return None
        return sorted(messages, key=lambda x: float(self._msg_value(x, "time", 0.0)))[-1]

    def _msg_value(self, msg: Any, key: str, default: Any = None) -> Any:
        if isinstance(msg, dict):
            return msg.get(key, default)
        return getattr(msg, key, default)

    async def _handle_set(self) -> Tuple[bool, Optional[str], bool]:
        storage = self._storage()
        owner_key = self._owner_key()
        messages = self._load_recent_messages(limit=80)

        target_message: Optional[Any] = None
        reply_to_id = self._command_reply_to_id()
        if reply_to_id:
            target_message = self._find_message_by_id(messages, reply_to_id)
        if target_message is None:
            target_message = self._pick_latest_image_message(messages)

        if target_message is None:
            await self.send_text("❌ 未找到可用图片。请引用一条图片消息后执行 `/selfie_base set`。")
            return False, "set 失败：未找到图片消息", True

        image_b64 = find_image_base64_in_message(target_message)
        if not image_b64:
            await self.send_text("❌ 找到了消息，但未提取到图片 base64。请换一条原始图片消息重试。")
            return False, "set 失败：图片提取失败", True

        out_path = storage.save_base_image(owner_key, image_b64)
        await self.send_text(f"✅ 角色底图已设置：`{out_path.name}`")
        return True, f"set 成功: {out_path}", True

    async def _handle_clear(self) -> Tuple[bool, Optional[str], bool]:
        storage = self._storage()
        owner_key = self._owner_key()
        removed = storage.clear_base_image(owner_key)
        if removed:
            await self.send_text("✅ 角色底图已清空。")
            return True, "clear 成功", True
        await self.send_text("ℹ️ 当前作用域没有已设置底图。")
        return True, "clear: 无底图", True

    async def _handle_show(self) -> Tuple[bool, Optional[str], bool]:
        storage = self._storage()
        owner_key = self._owner_key()
        exists = storage.has_base_image(owner_key)
        if not exists:
            await self.send_text("ℹ️ 当前作用域未设置底图。可用 `/selfie_base set` 进行设置。")
            return True, "show: 无底图", True

        image_b64 = storage.read_base_image_base64(owner_key)
        path = storage.get_base_image_path(owner_key)
        await self.send_text(f"✅ 当前底图存在：`{path.name if path else 'unknown'}`")
        if image_b64:
            recent = self._load_recent_messages(limit=10)
            reply_message = self._latest_message_for_reply(recent)
            try:
                await send_api.image_to_stream(
                    image_base64=image_b64,
                    stream_id=self._stream_id(),
                    storage_message=True,
                    set_reply=bool(reply_message),
                    reply_message=reply_message,
                )
            except Exception as exc:
                LOGGER.warning("show base image send failed", error=str(exc), owner_key=owner_key)
        return True, "show 成功", True
