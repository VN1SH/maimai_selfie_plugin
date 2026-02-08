import json
from typing import Any, Dict, List, Optional

import aiohttp

from .storage import strip_data_uri


class ImageClient:
    def __init__(
        self,
        provider: str,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.provider = (provider or "openai").strip().lower()
        self.api_base = (api_base or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_seconds = timeout_seconds

    async def generate_with_reference(
        self,
        prompt: str,
        negative_prompt: str,
        base_image_base64: str,
        image_size: str,
    ) -> str:
        if not self.api_base:
            raise RuntimeError("image_api_base 未配置")
        if not self.model:
            raise RuntimeError("image_model 未配置")

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "size": image_size,
            "image": strip_data_uri(base_image_base64),
            "reference_image": strip_data_uri(base_image_base64),
            "response_format": "b64_json",
        }
        endpoints: List[str] = []
        if self.provider == "openai":
            endpoints = ["/images/edits", "/images/generations"]
        else:
            endpoints = ["/images/edits", "/images/generations"]

        last_error = ""
        for ep in endpoints:
            try:
                response_data = await self._post_json(ep, payload)
                image_base64 = self._extract_base64(response_data)
                if image_base64:
                    return image_base64
            except Exception as exc:  # noqa: PERF203
                last_error = str(exc)

        raise RuntimeError(f"图片生成失败: {last_error or '无可用响应'}")

    async def _post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.api_base
        if not url.endswith(endpoint):
            url = f"{url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"返回非 JSON 响应: {text[:200]}") from exc

    def _extract_base64(self, data: Dict[str, Any]) -> Optional[str]:
        if not isinstance(data, dict):
            return None

        top_candidates = [
            data.get("image_base64"),
            data.get("b64_json"),
            data.get("base64"),
            data.get("output"),
        ]
        for candidate in top_candidates:
            if isinstance(candidate, str) and candidate.strip():
                return strip_data_uri(candidate.strip())

        rows = data.get("data")
        if isinstance(rows, list):
            for item in rows:
                if not isinstance(item, dict):
                    continue
                for key in ("b64_json", "base64", "image_base64"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        return strip_data_uri(value.strip())
                url = item.get("url")
                if isinstance(url, str) and url.startswith("data:image/") and "," in url:
                    return strip_data_uri(url)
        return None
