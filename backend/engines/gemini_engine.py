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


TAG_PROMPT = """Analyze this photo for a photo-indexing app. Reason in English internally for accuracy, then output Chinese labels.
You are also given the file's name and the folder path it lives in. These often carry human-authored context (event, place, date, project, client, subject). Treat them as strong hints: cross-check them against what you actually see in the image. When the filename/folder names a specific place, person, event or theme that is consistent with the image, fold that into the category/tags/description; if they clearly contradict the image, trust the image and ignore the misleading name.
特别规则（务必遵守）：
1) 摄影师：文件名或文件夹中常含摄影师名，可能是真名、昵称、网名或拼音（如「戴频」「老王」「Ansel」）。必须把它填入 photographer 字段，同时加入 tags、并在 desc 中点明（如「戴频 摄」）。务必不要遗漏。
2) 地名：若文件名或文件夹中出现地名，必须把它加入 tags 与 desc；但若该地名与下方「GPS定位地名」重复或同义，则省略以免重复。
Respond with ONLY a JSON object, no markdown fences, no preamble:
{"category":"主类别：若文件名或文件夹中含具体地点/事件/物种名，则优先采用它（如 兰亭、阳澄湖、白鹭、龙舟赛）；否则用你识别的画面大类(2-4字，如 自然风光/人像/美食/建筑/街拍)。无论如何 tags 都要由你识别生成、不可省略","tags":["3到6个中文标签，可包含从文件名/文件夹推断出的地点/事件/项目等信息"],"desc":"一句不超过30字的中文画面描述（如有摄影师/地名需包含）","location":"拍摄地点（市/县级）：优先采用文件名/文件夹中的明确地名，否则结合画面地标推断到市县级；不要包含国家和省份，多级地名用-连接（如 苏州-甪直、绍兴-兰亭、盐城）；无法判断则留空","photographer":"摄影师的姓名或昵称：从文件名或文件夹中提取，可能是真名/昵称/网名/拼音（如 戴频、老王、Ansel）；无法判断则留空字符串","slug":"short-english-slug-for-filename"}"""


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
            photographer=obj.get("photographer", ""),
            engine="gemini",
            raw_response=text,
        )
