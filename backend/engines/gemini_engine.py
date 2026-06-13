"""
Google Gemini Vision API engine for Photo-Aiid-system.

Sends images as base64 to Google's Gemini API with the TAG_PROMPT,
parses JSON response for category/tags/desc/slug.
"""

import base64
import json
import re

import httpx

from engines.base import BaseEngine, AnalysisResult

TAG_PROMPT = """Analyze this photo for a photo-indexing app. Reason in English internally for accuracy, then output Chinese labels.
You are also given the file's name and the folder path it lives in. These often carry human-authored context (event, place, date, project, client, subject). Treat them as strong hints: cross-check them against what you actually see in the image. When the filename/folder names a specific place, person, event or theme that is consistent with the image, fold that into the category/tags/description; if they clearly contradict the image, trust the image and ignore the misleading name.
Respond with ONLY a JSON object, no markdown fences, no preamble:
{"category":"主类别(2-4个汉字，如：自然风光/人像/美食/文档/宠物/建筑/街拍)","tags":["3到6个中文标签，可包含从文件名/文件夹推断出的地点/事件/项目等信息"],"desc":"一句不超过20字的中文画面描述","slug":"short-english-slug-for-filename"}"""


class GeminiEngine(BaseEngine):
    """Google Gemini Vision API – cloud-based multimodal analysis."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash", **kwargs):
        self.api_key = api_key
        self.model = model

    @property
    def api_url(self):
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
    ) -> AnalysisResult:
        if not self.api_key:
            raise ValueError("Gemini API key is required. Set it in settings.")

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build context text from filename/folder
        context_lines = []
        if file_name:
            context_lines.append(f"文件名：{file_name}")
        if folder_path:
            context_lines.append(f"所在文件夹：{folder_path}")
        context = "\n".join(context_lines) if context_lines else "(无上下文)"

        prompt = (
            TAG_PROMPT
            + "\n\n--- 文件上下文（请结合图像与下列信息综合判断）---\n"
            + context
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1000,
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self.api_url,
                json=payload,
                params={"key": self.api_key},
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            # Check if prompt or image was blocked by safety filters
            prompt_feedback = data.get("promptFeedback", {})
            if prompt_feedback:
                raise RuntimeError(f"Gemini API blocked request. Feedback: {prompt_feedback}")
            raise RuntimeError(f"Gemini API returned empty response: {data}")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")

        # Extract text from response
        text = ""
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                text += part["text"]

        if finish_reason and finish_reason != "STOP":
            raise RuntimeError(f"Gemini API generation failed. Finish reason: {finish_reason}. Partial response: {text[:200]}")

        if not text:
            raise RuntimeError("Gemini API returned candidate but no text content.")

        return self._parse_response(text)

    async def test_connection(self) -> dict:
        if not self.api_key:
            return {"ok": False, "message": "API key not configured"}
        try:
            payload = {
                "contents": [{"parts": [{"text": "回复一个字：通"}]}],
                "generationConfig": {"maxOutputTokens": 10},
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.api_url,
                    json=payload,
                    params={"key": self.api_key},
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code == 200:
                return {"ok": True, "message": f"Gemini API connection OK (model: {self.model})"}
            else:
                return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @staticmethod
    def _parse_response(text: str) -> AnalysisResult:
        """Extract JSON from Gemini's text response."""
        cleaned = text.replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            raise ValueError(f"Cannot parse JSON from Gemini response: {text[:200]}")
        json_str = m.group(0)
        # Fix: Gemini sometimes puts newlines inside JSON string values
        # Replace literal newlines inside strings with spaces
        json_str = re.sub(r'(?<=":)"([^"]*)\n([^"]*)"', lambda m: f'"{m.group(1)} {m.group(2)}"', json_str)
        # Also try a simpler fix: replace all newlines with spaces then re-parse
        try:
            obj = json.loads(json_str)
        except json.JSONDecodeError:
            json_str = json_str.replace("\n", " ").replace("\r", "")
            obj = json.loads(json_str)
        return AnalysisResult(
            category=obj.get("category", ""),
            tags=obj.get("tags", []),
            description=obj.get("desc", obj.get("description", "")),
            slug=obj.get("slug", ""),
            engine="gemini",
            raw_response=text,
        )
