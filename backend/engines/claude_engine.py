"""
Claude Vision API engine for Photo-Aiid-system.

Sends images as base64 to Anthropic's Messages API with the TAG_PROMPT,
parses JSON response for category/tags/desc/slug.
"""

import base64
import json
import httpx

from engines.base import BaseEngine, AnalysisResult

from engines.prompt import TAG_PROMPT


class ClaudeEngine(BaseEngine):
    """Claude Vision API – cloud-based high-accuracy analysis."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-6", **kwargs):
        self.api_key = api_key
        self.model = model

    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
        extra_context: str = "",
    ) -> AnalysisResult:
        if not self.api_key:
            raise ValueError("Claude API key is required. Set it in settings.")

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build context text from filename/folder
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
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.API_URL, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"Claude API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        return self._parse_response(text)

    async def test_connection(self) -> dict:
        if not self.api_key:
            return {"ok": False, "message": "API key not configured"}
        try:
            payload = {
                "model": self.model,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "回复一个字：通"}],
            }
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                return {"ok": True, "message": "Claude API connection OK"}
            else:
                return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @staticmethod
    def _parse_response(text: str) -> AnalysisResult:
        """Extract JSON from Claude's text response."""
        # Strip markdown fences if present
        cleaned = text.replace("```json", "").replace("```", "").strip()
        # Find JSON object
        import re
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            raise ValueError(f"Cannot parse JSON from Claude response: {text[:200]}")
        obj = json.loads(m.group(0))
        return AnalysisResult(
            category=obj.get("category", ""),
            tags=obj.get("tags", []),
            description=obj.get("desc", obj.get("description", "")),
            slug=obj.get("slug", ""),
            location=obj.get("location", ""),
            place_in_name=obj.get("place_in_name", ""),
            photographer=obj.get("photographer", ""),
            engine="claude",
            raw_response=text,
        )
