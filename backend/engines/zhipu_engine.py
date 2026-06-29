"""
Zhipu AI (智谱 GLM) Vision engine for Photo-Aiid-system.

Uses the OpenAI-compatible chat-completions endpoint with a base64 image.
Default model `glm-4v-flash` is free and vision-capable.
Parses JSON response for category/tags/desc/location/slug.
"""

import base64
import json
import re

import httpx

from engines.base import BaseEngine, AnalysisResult

from engines.prompt import TAG_PROMPT


class ZhipuEngine(BaseEngine):
    """Zhipu AI (智谱 GLM) Vision API – cloud-based, glm-4v-flash is free."""

    API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def __init__(self, api_key: str = "", model: str = "glm-4v-flash", **kwargs):
        self.api_key = api_key
        self.model = model

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
        extra_context: str = "",
    ) -> AnalysisResult:
        if not self.api_key:
            raise ValueError("Zhipu API key is required. Set it in settings.")

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build context text from filename/folder/neighbors
        context_lines = []
        if file_name:
            context_lines.append(f"文件名：{file_name}")
        if folder_path:
            context_lines.append(f"所在文件夹：{folder_path}")
        if extra_context:
            context_lines.append(extra_context)
        context = "\n".join(context_lines) if context_lines else "(无上下文)"

        prompt = (
            TAG_PROMPT
            + "\n\n--- 文件上下文（请结合图像与下列信息综合判断）---\n"
            + context
        )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.API_URL, json=payload, headers=self._headers())

        if resp.status_code != 200:
            raise RuntimeError(f"Zhipu API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        text = ""
        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str):
                text += content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        text += part["text"]

        return self._parse_response(text)

    async def test_connection(self) -> dict:
        if not self.api_key:
            return {"ok": False, "message": "API key not configured"}
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "回复一个字：通"}],
                "max_tokens": 10,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self.API_URL, json=payload, headers=self._headers())
            if resp.status_code == 200:
                return {"ok": True, "message": f"Zhipu API connection OK (model: {self.model})"}
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @staticmethod
    def _parse_response(text: str) -> AnalysisResult:
        """Extract JSON from the model's text response."""
        cleaned = text.replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            raise ValueError(f"Cannot parse JSON from Zhipu response: {text[:200]}")
        obj = json.loads(m.group(0))
        return AnalysisResult(
            category=obj.get("category", ""),
            tags=obj.get("tags", []),
            description=obj.get("desc", obj.get("description", "")),
            slug=obj.get("slug", ""),
            location=obj.get("location", ""),
            place_in_name=obj.get("place_in_name", ""),
            photographer=obj.get("photographer", ""),
            engine="zhipu",
            raw_response=text,
        )
