import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from src.plugin_system import ActionActivationType, BaseAction

try:
    from src.plugin_system.apis import get_logger, message_api, person_api, send_api
except Exception:  # pragma: no cover
    from src.plugin_system import get_logger, message_api, person_api, send_api

from ..services.image_client import ImageClient
from ..services.llm_client import LLMClient
from ..services.rate_limiter import RateLimiter
from ..services.storage import SelfieStorage

LOGGER = get_logger("maimai_selfie_plugin.action")


class SelfieAutoAction(BaseAction):
    action_name = "selfie_auto_action"
    action_description = "群友索要自拍时，基于角色底图和聊天场景自动生成自拍图"
    activation_type = ActionActivationType.ALWAYS
    parallel_action = False
    associated_types = ["text", "image", "reply"]
    action_parameters = {
        "trigger_text": "触发关键词的消息文本",
    }
    action_require = [
        "当用户索要自拍、照片、来张图时可使用",
        "必须基于已设置底图保持同一角色一致性",
        "结合最近聊天上下文推断场景、服装和动作",
    ]

    async def execute(self) -> Tuple[bool, str]:
        if not bool(self.get_config("plugin.enabled", True)):
            return True, "插件已禁用"
        if not bool(self.get_config("selfie.enabled", True)):
            return True, "自拍功能已禁用"

        trigger_text = self._trigger_text()
        if not self._keyword_hit(trigger_text):
            return True, "关键词未命中"

        storage = self._storage()
        owner_key = self._owner_key()
        cooldown = int(self.get_config("selfie.cooldown_seconds", 30) or 30)
        now_ts = time.time()
        last_ts = storage.get_last_trigger(owner_key)
        if cooldown > 0 and (now_ts - last_ts) < cooldown:
            return True, f"触发冷却中 ({cooldown}s)"

        base_image_b64 = storage.read_base_image_base64(owner_key)
        reply_message = self._latest_message_for_reply()
        if not base_image_b64:
            await send_api.text_to_stream(
                text="请管理员先用 `/selfie_base set` 上传角色底图。",
                stream_id=self._stream_id(),
                typing=False,
                set_reply=bool(reply_message),
                reply_message=reply_message,
                storage_message=True,
            )
            return True, "缺少底图"

        try:
            context = self._build_context_text()
            prompt_style = str(self.get_config("selfie.prompt_style", "写实"))
            disallow_nsfw = bool(self.get_config("safety.disallow_nsfw", True))
            llm_client = LLMClient(
                provider=str(self.get_config("llm.llm_provider", "openai")),
                api_base=str(self.get_config("llm.llm_api_base", "https://api.openai.com/v1")),
                api_key=str(self.get_config("llm.llm_api_key", "")),
                model=str(self.get_config("llm.llm_model", "gpt-4o-mini")),
            )
            rate_limiter = None
            window_hours = int(self.get_config("selfie.rate_limit_window_hours", 6) or 6)
            max_images = int(self.get_config("selfie.rate_limit_max_images", 3) or 3)
            if bool(self.get_config("selfie.rate_limit_enabled", True)):
                scope = str(self.get_config("selfie.rate_limit_scope", "chat")).strip().lower()
                scope_id = self._rate_limit_scope_id(scope)
                rate_limiter = RateLimiter(storage.data_dir, scope_id)
                limited, count = rate_limiter.check(window_hours, max_images, now_ts)
                if limited:
                    LOGGER.info(
                        "selfie rate limit hit",
                        scope=scope,
                        scope_id=scope_id,
                        window_hours=window_hours,
                        max_images=max_images,
                        current_count=count,
                    )
                    refusal_reason = f"{window_hours} 小时内已拍了太多张照片"
                    refusal_text = await llm_client.generate_refusal_reply(context, refusal_reason)
                    await send_api.text_to_stream(
                        text=refusal_text,
                        stream_id=self._stream_id(),
                        typing=False,
                        set_reply=bool(reply_message),
                        reply_message=reply_message,
                        storage_message=True,
                    )
                    return True, "限流触发，已拒绝生图"

            prompt_plan = await llm_client.generate_prompt_plan(context, prompt_style, disallow_nsfw)

            image_client = ImageClient(
                provider=str(self.get_config("image.image_provider", "openai")),
                api_base=str(self.get_config("image.image_api_base", "https://api.openai.com/v1")),
                api_key=str(self.get_config("image.image_api_key", "")),
                model=str(self.get_config("image.image_model", "gpt-image-1")),
            )
            output_b64 = await image_client.generate_with_reference(
                prompt=prompt_plan.prompt,
                negative_prompt=prompt_plan.negative,
                base_image_base64=base_image_b64,
                image_size=str(self.get_config("image.image_size", "1024x1024")),
            )

            ok = await send_api.image_to_stream(
                image_base64=output_b64,
                stream_id=self._stream_id(),
                storage_message=True,
                set_reply=bool(reply_message),
                reply_message=reply_message,
            )
            if ok:
                storage.set_last_trigger(owner_key, now_ts)
                if rate_limiter is not None:
                    rate_limiter.record(window_hours, now_ts)
                return True, "自拍图已生成并发送"
            await self.send_text("图片生成成功但发送失败，请稍后重试。")
            return False, "图片发送失败"
        except Exception as exc:
            LOGGER.error("selfie action failed", error=str(exc), chat_id=self._chat_id())
            await send_api.text_to_stream(
                text="生成自拍图失败了，请稍后再试。",
                stream_id=self._stream_id(),
                typing=False,
                set_reply=bool(reply_message),
                reply_message=reply_message,
                storage_message=True,
            )
            return False, f"生成失败: {exc}"

    def _storage(self) -> SelfieStorage:
        plugin_dir = Path(__file__).resolve().parents[1]
        data_dir = plugin_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return SelfieStorage(data_dir)

    def _trigger_text(self) -> str:
        from_action = str((self.action_data or {}).get("trigger_text", "")).strip() if isinstance(self.action_data, dict) else ""
        if from_action:
            return from_action
        message = getattr(self, "action_message", None) or {}
        if isinstance(message, dict):
            return str(message.get("processed_plain_text", "") or "").strip()
        return ""

    def _keyword_hit(self, text: str) -> bool:
        if not text:
            return False
        keywords = self.get_config("selfie.trigger_keywords", ["自拍", "照片", "来张", "发张", "看看你"])
        if not isinstance(keywords, list):
            keywords = ["自拍", "照片", "来张", "发张", "看看你"]
        low_text = text.lower()
        return any(str(k).strip().lower() in low_text for k in keywords if str(k).strip())

    def _chat_id(self) -> str:
        return str(getattr(self, "chat_id", "") or getattr(getattr(self, "chat_stream", None), "stream_id", ""))

    def _stream_id(self) -> str:
        stream = getattr(self, "chat_stream", None)
        return str(getattr(stream, "stream_id", "") or self._chat_id())

    def _person_id(self) -> str:
        platform = str(getattr(self, "platform", "qq"))
        user_id_raw = str(getattr(self, "user_id", ""))
        try:
            return person_api.get_person_id(platform, int(user_id_raw))
        except Exception:
            return f"{platform}_{user_id_raw}"

    def _owner_key(self) -> str:
        scope = str(self.get_config("selfie.base_image_scope", "chat")).strip().lower()
        scope = "user" if scope == "user" else "chat"
        return SelfieStorage.owner_key(scope=scope, chat_id=self._chat_id(), person_id=self._person_id())

    def _rate_limit_scope_id(self, scope: str) -> str:
        normalized = "user" if scope == "user" else "chat"
        if normalized == "user":
            return f"user_{self._person_id()}"
        return f"chat_{self._chat_id()}"

    def _load_recent_messages(self) -> List[Any]:
        chat_id = self._chat_id()
        if not chat_id:
            return []
        limit = int(self.get_config("selfie.context_message_limit", 20) or 20)
        limit = max(1, min(200, limit))
        try:
            return message_api.get_recent_messages(chat_id=chat_id, hours=24.0, limit=limit, limit_mode="latest", filter_mai=True)
        except TypeError:
            return message_api.get_recent_messages(chat_id, 24.0, limit, "latest", True)

    def _latest_message_for_reply(self) -> Optional[Any]:
        messages = self._load_recent_messages()
        if not messages:
            return None
        return sorted(messages, key=lambda x: float(self._msg_value(x, "time", 0.0)))[-1]

    def _build_context_text(self) -> str:
        messages = self._load_recent_messages()
        rows: List[Tuple[float, str, str]] = []
        for msg in messages:
            text = str(self._msg_value(msg, "processed_plain_text", "") or "").strip()
            if not text:
                continue
            if text.startswith("/"):
                continue
            nickname = ""
            user_info = self._msg_value(msg, "user_info", None)
            if user_info is not None:
                if isinstance(user_info, dict):
                    nickname = str(user_info.get("user_nickname", "") or user_info.get("nickname", "") or "").strip()
                else:
                    nickname = str(getattr(user_info, "user_nickname", "") or getattr(user_info, "nickname", "") or "").strip()
            if not nickname:
                nickname = str(self._msg_value(msg, "user_id", "") or "user")
            ts = float(self._msg_value(msg, "time", 0.0))
            rows.append((ts, nickname, text))
        rows.sort(key=lambda x: x[0])
        if not rows:
            return "（无可用上下文）"
        return "\n".join(f"[{name}] {text}" for _, name, text in rows)

    def _msg_value(self, msg: Any, key: str, default: Any = None) -> Any:
        if isinstance(msg, dict):
            return msg.get(key, default)
        return getattr(msg, key, default)
