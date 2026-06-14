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
特别规则（务必遵守）：
1) 摄影师：文件名或文件夹中常含摄影师名，可能是真名、昵称、网名或拼音（如「戴频」「老王」「Ansel」）。必须把它填入 photographer 字段，同时加入 tags、并在 desc 中点明（如「戴频 摄」）。务必不要遗漏。
2) 地名：若文件名或文件夹中出现地名，必须把它加入 tags 与 desc；但若该地名与下方「GPS定位地名」重复或同义，则省略以免重复。
Respond with ONLY a JSON object, no markdown fences, no preamble:
{"category":"主类别：①若画面主体是某一物种(鸟/兽/鱼/虫/花草等生物)，类别一律判定为「物种」；②否则若文件名或文件夹中含具体地点/事件名，则优先采用它（如 兰亭、阳澄湖、龙舟赛）；③否则用你识别的画面大类(2-4字，如 自然风光/人像/美食/建筑/街拍)。无论如何 tags 都要由你识别生成、不可省略","tags":["3到6个中文标签，可包含从文件名/文件夹推断出的地点/事件/项目等信息"],"desc":"一句不超过30字的中文画面描述（如有摄影师/地名需包含）","location":"拍摄地点（市/县级）：优先采用文件名/文件夹中的明确地名，否则结合画面地标推断到市县级；不要包含国家和省份，多级地名用-连接（如 苏州-甪直、绍兴-兰亭、盐城）；无法判断则留空","place_in_name":"文件名或文件夹中明确写出的地名原文（如 石臼湖、阳澄湖、兰亭、甪直）；只填确实出现在文件名/文件夹里的地名，没有则留空字符串","photographer":"摄影师的姓名或昵称：从文件名或文件夹中提取，可能是真名/昵称/网名/拼音（如 戴频、老王、Ansel）；无法判断则留空字符串","slug":"short-english-slug-for-filename"}"""


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
        extra_context: str = "",
    ) -> AnalysisResult:
        b64 = base64.b64encode(image_bytes).decode("utf-8")

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
            location=obj.get("location", ""),
            place_in_name=obj.get("place_in_name", ""),
            photographer=obj.get("photographer", ""),
            engine="ollama",
            raw_response=text,
        )
