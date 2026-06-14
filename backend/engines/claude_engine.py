"""
Claude Vision API engine for Photo-Aiid-system.

Sends images as base64 to Anthropic's Messages API with the TAG_PROMPT,
parses JSON response for category/tags/desc/slug.
"""

import base64
import json
import httpx

from engines.base import BaseEngine, AnalysisResult

TAG_PROMPT = """Analyze this photo for a photo-indexing app. Reason in English internally for accuracy, then output Chinese labels.
You are also given the file's name and the folder path it lives in. These often carry human-authored context (event, place, date, project, client, subject). Treat them as strong hints: cross-check them against what you actually see in the image. When the filename/folder names a specific place, person, event or theme that is consistent with the image, fold that into the category/tags/description; if they clearly contradict the image, trust the image and ignore the misleading name.
特别规则（务必遵守）：
1) 摄影师：文件名或文件夹中常含摄影师名，可能是真名、昵称、网名或拼音（如「戴频」「老王」「Ansel」）。必须把它填入 photographer 字段，同时加入 tags、并在 desc 中点明（如「戴频 摄」）。务必不要遗漏。
2) 地名：若文件名或文件夹中出现地名，必须把它加入 tags 与 desc；但若该地名与下方「GPS定位地名」重复或同义，则省略以免重复。
Respond with ONLY a JSON object, no markdown fences, no preamble:
{"category":"主类别：①若画面主体是某一物种(鸟/兽/鱼/虫/花草等生物)，类别一律判定为「物种」；②否则若文件名或文件夹中含具体地点/事件名，则优先采用它（如 兰亭、阳澄湖、龙舟赛）；③否则用你识别的画面大类(2-4字，如 自然风光/人像/美食/建筑/街拍)。无论如何 tags 都要由你识别生成、不可省略","tags":["3到6个中文标签，可包含从文件名/文件夹推断出的地点/事件/项目等信息"],"desc":"一句不超过30字的中文画面描述（如有摄影师/地名需包含）","location":"拍摄地点（市/县级）：优先采用文件名/文件夹中的明确地名，否则结合画面地标推断到市县级；不要包含国家和省份，多级地名用-连接（如 苏州-甪直、绍兴-兰亭、盐城）；无法判断则留空","place_in_name":"文件名或文件夹中明确写出的、真实且具体的地名原文（如 石臼湖、阳澄湖、兰亭、甪直、某村/某镇/某山/某景点）。严格排除：方向性或泛指词（如 沿长江、江边、湖区）、项目/系列/主题/活动名、以及画面主体或景物描述（如 灌溉网络湿地、农田）。这些一律不要填进本字段。只填确实出现在文件名/文件夹里的真实地名，拿不准或没有则留空字符串","photographer":"摄影师的姓名或昵称：从文件名或文件夹中提取，可能是真名/昵称/网名/拼音（如 戴频、老王、Ansel）；无法判断则留空字符串","slug":"short-english-slug-for-filename"}"""


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
