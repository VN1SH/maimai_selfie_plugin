import json
import re
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp


@dataclass
class SelfiePromptPlan:
    scene: str
    outfit: str
    pose: str
    camera: str
    lighting: str
    mood: str
    negative: str
    prompt: str


class LLMClient:
    def __init__(
        self,
        provider: str,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.provider = (provider or "openai").strip().lower()
        self.api_base = (api_base or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_seconds = timeout_seconds

    async def generate_prompt_plan(
        self,
        context_text: str,
        style: str,
        disallow_nsfw: bool,
    ) -> SelfiePromptPlan:
        schema_hint = {
            "scene": "string",
            "outfit": "string",
            "pose": "string",
            "camera": "string",
            "lighting": "string",
            "mood": "string",
            "negative": "string",
            "prompt": "string",
        }
        safety_line = (
            "必须严格排除 NSFW、裸露、未成年人、血腥、暴力、仇恨内容。"
            if disallow_nsfw
            else "避免低俗、血腥、违法内容。"
        )
        system_prompt = (
            "你是图片提示词规划器。根据聊天上下文，输出角色自拍规划。"
            "只输出 JSON，不要输出额外文字。JSON 键必须为："
            + ",".join(schema_hint.keys())
            + "。"
        )
        user_prompt = (
            f"请基于以下聊天上下文，推断自拍场景并生成自拍提示词。\n"
            f"风格偏好：{style}\n"
            f"安全要求：{safety_line}\n"
            "输出要求：\n"
            "1) 人物固定为同一角色，强调与参考图一致的人脸、发型、标志物；\n"
            "2) 动作自然，像随手自拍；\n"
            "3) scene 与上下文一致；\n"
            "4) negative 写负向提示词；\n"
            "5) prompt 是最终可直接用于绘图的完整英文提示词。\n\n"
            f"聊天上下文：\n{context_text}"
        )

        raw = await self._chat(system_prompt, user_prompt)
        parsed = self._parse_json(raw)
        if not parsed:
            return self._fallback_plan(context_text, style, disallow_nsfw)
        return SelfiePromptPlan(
            scene=str(parsed.get("scene", "")).strip() or "indoor casual place",
            outfit=str(parsed.get("outfit", "")).strip() or "daily casual wear",
            pose=str(parsed.get("pose", "")).strip() or "holding phone for a selfie",
            camera=str(parsed.get("camera", "")).strip() or "close-up selfie shot",
            lighting=str(parsed.get("lighting", "")).strip() or "natural soft light",
            mood=str(parsed.get("mood", "")).strip() or "friendly and relaxed",
            negative=str(parsed.get("negative", "")).strip() or self._default_negative(disallow_nsfw),
            prompt=str(parsed.get("prompt", "")).strip() or self._fallback_plan(context_text, style, disallow_nsfw).prompt,
        )

    async def _chat(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_base:
            raise RuntimeError("llm_api_base 未配置")
        if not self.model:
            raise RuntimeError("llm_model 未配置")
        url = self.api_base
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"LLM HTTP {resp.status}: {text[:300]}")
                data = json.loads(text)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content)

    def _parse_json(self, content: str) -> Dict[str, Any]:
        if not content:
            return {}
        content = content.strip()
        try:
            return json.loads(content)
        except Exception:
            pass
        match = re.search(r"```json\s*(\{.*?\})\s*```", content, flags=re.S)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                return {}
        match = re.search(r"(\{.*\})", content, flags=re.S)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                return {}
        return {}

    def _default_negative(self, disallow_nsfw: bool) -> str:
        base = "blurry, low quality, deformed face, extra fingers, bad anatomy, watermark, text"
        if disallow_nsfw:
            return base + ", nsfw, nude, sexual, erotic, gore, blood, minor, child"
        return base

    def _fallback_plan(self, context_text: str, style: str, disallow_nsfw: bool) -> SelfiePromptPlan:
        context_lower = context_text.lower()
        scene = "classroom with desks and blackboard" if ("上课" in context_text or "教室" in context_text) else "daily life indoor setting"
        if "户外" in context_text or "公园" in context_text or "outdoor" in context_lower:
            scene = "outdoor urban park"
        negative = self._default_negative(disallow_nsfw)
        prompt = (
            f"same character as reference image, consistent face shape hairstyle and signature accessories, "
            f"{style} style, {scene}, casual outfit, natural candid selfie pose, hand-held phone angle, "
            f"soft realistic lighting, friendly mood, high detail, realistic skin texture"
        )
        return SelfiePromptPlan(
            scene=scene,
            outfit="casual daily outfit",
            pose="natural hand-held selfie",
            camera="smartphone front camera close-up",
            lighting="soft ambient light",
            mood="friendly relaxed",
            negative=negative,
            prompt=prompt,
        )
