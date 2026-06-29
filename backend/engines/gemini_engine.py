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


def _friendly_error(status_code: int, body: str) -> str:
    """Turn a Gemini error response into a concise, actionable message."""
    try:
        err = json.loads(body).get("error", {})
        msg = err.get("message", "")
        # Look for a quota detail with the actual limit value.
        for d in err.get("details", []):
            meta = d.get("metadata", {})
            if "quota_limit_value" in meta:
                limit = meta.get("quota_limit_value")
                region = meta.get("quota_location", "")
                if str(limit) == "0":
                    return (
                        f"Gemini 配额为 0（项目在 {region} 区域没有 API 配额）。"
                        "该 Key 所属项目未启用 Generative Language API 或未开通计费/不在免费层区域，"
                        "等待无效。请在 Google Cloud 启用该 API 并开通计费，或改用 Ollama 本地引擎。"
                        f" 原始信息: {msg}"
                    )
                return (
                    f"Gemini 限额：当前上限 {limit}/分钟，区域 {region}。请降低频率或稍后重试。"
                    f" 原始信息: {msg}"
                )
        if msg:
            return f"Gemini API error {status_code}: {msg}"
    except Exception:
        pass
    return f"Gemini API error {status_code}: {body[:500]}"


from engines.prompt import TAG_PROMPT


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
        extra_context: str = "",
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
        if extra_context:
            context_lines.append(extra_context)
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
                "maxOutputTokens": 2048,
                "temperature": 0.2,
                "responseMimeType": "application/json",
                # gemini-2.5-flash is a "thinking" model: without this it spends
                # output tokens on internal reasoning (thoughtsTokenCount) and can
                # hit MAX_TOKENS before emitting any text, yielding an empty
                # candidate. Disable thinking so the full budget goes to the JSON.
                "thinkingConfig": {"thinkingBudget": 0},
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
            raise RuntimeError(_friendly_error(resp.status_code, resp.text))

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
                return {"ok": False, "message": _friendly_error(resp.status_code, resp.text)}
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
            location=obj.get("location", ""),
            place_in_name=obj.get("place_in_name", ""),
            photographer=obj.get("photographer", ""),
            engine="gemini",
            raw_response=text,
        )
