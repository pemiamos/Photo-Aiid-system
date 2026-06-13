"""
Ollama local LLM engine for Photo-Aiid-system.

Connects to a locally-running Ollama instance with a vision-capable model
(e.g., gemma3, llava, qwen-vl). Sends the image for analysis.
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


class OllamaEngine(BaseEngine):
    """Ollama local LLM – privacy-first, runs entirely on the user's machine."""

    def __init__(self, url: str = "http://localhost:11434", model: str = "gemma3:12b", **kwargs):
        self.base_url = url.rstrip("/")
        self.model = model

    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
    ) -> AnalysisResult:
        b64 = base64.b64encode(image_bytes).decode("utf-8")

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
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64],
                }
            ],
            "stream": False,
        }

        url = f"{self.base_url}/api/chat"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")

        text = data.get("message", {}).get("content", "")
        return self._parse_response(text)

    async def test_connection(self) -> dict:
        """Test connection to Ollama and verify model exists."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check if Ollama is reachable
                resp = await client.get(f"{self.base_url}/api/tags")
            if resp.status_code != 200:
                return {"ok": False, "message": f"Ollama returned HTTP {resp.status_code}"}

            models = resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            # Check if the configured model is available
            found = any(self.model in name for name in model_names)
            if found:
                return {
                    "ok": True,
                    "message": f"Ollama OK, model '{self.model}' found",
                    "models": model_names,
                }
            else:
                return {
                    "ok": False,
                    "message": f"Ollama OK, but model '{self.model}' not found. Available: {', '.join(model_names[:10])}",
                    "models": model_names,
                }
        except httpx.ConnectError:
            return {
                "ok": False,
                "message": f"Cannot connect to Ollama at {self.base_url}. Is it running?",
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @staticmethod
    def _parse_response(text: str) -> AnalysisResult:
        """Extract JSON from Ollama's text response."""
        cleaned = text.replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            raise ValueError(f"Cannot parse JSON from Ollama response: {text[:200]}")
        obj = json.loads(m.group(0))
        return AnalysisResult(
            category=obj.get("category", ""),
            tags=obj.get("tags", []),
            description=obj.get("desc", obj.get("description", "")),
            slug=obj.get("slug", ""),
            engine="ollama",
            raw_response=text,
        )
