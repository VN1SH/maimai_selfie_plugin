import json
import re
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp


@dataclass
class SelfiePromptPlan:
    scene: str
    activity: str
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
            "activity": "string",
            "outfit": "string",
            "pose": "string",
            "camera": "string",
            "lighting": "string",
            "mood": "string",
            "negative": "string",
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
            f"请基于以下聊天上下文，推断自拍场景并生成自拍规划。\n"
            f"风格偏好：{style}\n"
            f"安全要求：{safety_line}\n"
            "输出要求：\n"
            "1) 人物固定为同一角色，强调与参考图一致的人脸、发型、标志物；\n"
            "2) scene 与 activity 必须来自上下文推断，并与当前状态一致；\n"
            "3) 若上下文无法推断，使用室内日常/默认场景，但要与麦麦最后一条自述一致；\n"
            "4) 动作自然，像随手自拍；\n"
            "5) negative 写负向提示词；\n\n"
            f"聊天上下文：\n{context_text}"
        )

        raw = await self._chat(system_prompt, user_prompt)
        parsed = self._parse_json(raw)
        if not parsed:
            return self._fallback_plan(context_text, style, disallow_nsfw)
        plan = SelfiePromptPlan(
            scene=str(parsed.get("scene", "")).strip() or "",
            activity=str(parsed.get("activity", "")).strip() or "",
            outfit=str(parsed.get("outfit", "")).strip() or "",
            pose=str(parsed.get("pose", "")).strip() or "",
            camera=str(parsed.get("camera", "")).strip() or "",
            lighting=str(parsed.get("lighting", "")).strip() or "",
            mood=str(parsed.get("mood", "")).strip() or "",
            negative=str(parsed.get("negative", "")).strip() or "",
            prompt="",
        )
        plan = self._ensure_plan_defaults(plan, context_text, style, disallow_nsfw)
        plan.prompt = self._build_prompt(plan, style)
        return plan

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

    def _ensure_plan_defaults(
        self,
        plan: SelfiePromptPlan,
        context_text: str,
        style: str,
        disallow_nsfw: bool,
    ) -> SelfiePromptPlan:
        fallback = self._fallback_plan(context_text, style, disallow_nsfw)
        if not plan.scene:
            plan.scene = fallback.scene
        if not plan.activity:
            plan.activity = fallback.activity
        if not plan.outfit:
            plan.outfit = fallback.outfit
        if not plan.pose:
            plan.pose = fallback.pose
        if not plan.camera:
            plan.camera = fallback.camera
        if not plan.lighting:
            plan.lighting = fallback.lighting
        if not plan.mood:
            plan.mood = fallback.mood
        if not plan.negative:
            plan.negative = fallback.negative
        return plan

    def _build_prompt(self, plan: SelfiePromptPlan, style: str) -> str:
        return (
            "same character as reference image, consistent face shape hairstyle and signature accessories, "
            f"{style} style, scene: {plan.scene}, activity: {plan.activity}, outfit: {plan.outfit}, "
            f"pose: {plan.pose}, camera: {plan.camera}, lighting: {plan.lighting}, mood: {plan.mood}, "
            "natural candid selfie, high detail, realistic skin texture"
        )

    def _fallback_plan(self, context_text: str, style: str, disallow_nsfw: bool) -> SelfiePromptPlan:
        context_lower = context_text.lower()
        scene = "daily life indoor setting"
        activity = "relaxed casual selfie while staying indoors"
        if "上课" in context_text or "教室" in context_text:
            scene = "classroom with desks, blackboard, and blurred classmates"
            activity = "sitting at a desk listening to a lecture and taking notes"
        elif "开会" in context_text or "会议" in context_text or "公司" in context_text or "办公室" in context_text:
            scene = "office meeting room with conference table and presentation screen"
            activity = "attending a meeting, looking at the presentation"
        elif "地铁" in context_text or "公交" in context_text or "通勤" in context_text:
            scene = "subway carriage with handrails and commuters"
            activity = "standing during commute holding the phone for a quick selfie"
        elif "睡觉" in context_text or "睡了" in context_text or "休息" in context_text:
            scene = "cozy bedroom with bed and soft bedding"
            activity = "lying on the bed, sleepy, taking a quiet selfie"
        elif "吃饭" in context_text or "午饭" in context_text or "晚饭" in context_text or "早餐" in context_text:
            scene = "home dining area with tableware"
            activity = "sitting at the table about to eat, taking a quick selfie"
        elif "打游戏" in context_text or "游戏" in context_text:
            scene = "gaming desk with monitor and soft RGB lights"
            activity = "sitting at the desk gaming, pausing for a quick selfie"
        elif "户外" in context_text or "公园" in context_text or "outdoor" in context_lower:
            scene = "outdoor urban park"
            activity = "standing outdoors taking a casual selfie"
        elif "在家" in context_text or "家里" in context_text:
            scene = "cozy home interior"
            activity = "relaxed at home taking a casual selfie"
        negative = self._default_negative(disallow_nsfw)
        plan = SelfiePromptPlan(
            scene=scene,
            activity=activity,
            outfit="casual daily outfit",
            pose="natural hand-held selfie",
            camera="smartphone front camera close-up",
            lighting="soft ambient light",
            mood="friendly relaxed",
            negative=negative,
            prompt="",
        )
        plan.prompt = self._build_prompt(plan, style)
        return plan

    async def generate_refusal_reply(self, context_text: str, reason: str) -> str:
        system_prompt = (
            "你是麦麦，擅长在聊天中用自然口吻回应。"
            "请结合上下文说明当前状态，给出简短拒绝自拍的回复。"
            "不要提及模型、接口、系统指令。"
        )
        user_prompt = (
            "请基于以下聊天上下文生成拒绝回复。\n"
            f"拒绝原因：{reason}\n"
            "要求：语气自然，符合麦麦口吻，字数不宜过长。\n"
            f"聊天上下文：\n{context_text}"
        )
        raw = await self._chat(system_prompt, user_prompt)
        text = str(raw or "").strip()
        if not text:
            return "我现在有点忙，不方便拍照呢。"
        return text.split("\n")[0].strip()
