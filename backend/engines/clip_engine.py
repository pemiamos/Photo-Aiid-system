"""
CLIP local engine for Photo-Aiid-system (OPTIONAL).

Uses sentence-transformers with clip-ViT-B-32 to classify images against
predefined Chinese category prompts. This engine is completely optional –
if sentence-transformers/torch are not installed, the engine simply won't
be registered and the system still works with Claude/Ollama.
"""

from __future__ import annotations

import io
from engines.base import BaseEngine, AnalysisResult

# These imports may fail – that's expected. The __init__.py catches ImportError.
from sentence_transformers import SentenceTransformer
from PIL import Image
import numpy as np

# Predefined categories and their English CLIP prompts
CATEGORIES = {
    "自然风光": "a photo of natural scenery, mountains, sea, or sky",
    "人像": "a portrait of a person, people, or human faces",
    "宠物动物": "a photo of a cat, dog, bird, or other animals",
    "美食图片": "a photo of delicious food, drinks, or meals",
    "城市建筑": "a photo of city buildings, streets, or architecture",
    "电子截图": "a screenshot of a website or computer software",
    "文档表格": "a photo of a document, paper with text, or table",
    "街拍": "a candid street photo of daily life scenes",
}

# Sub-tags for each category to generate richer tag sets
CATEGORY_SUBTAGS = {
    "自然风光": ["山脉", "海洋", "天空", "日落", "森林", "湖泊", "花田"],
    "人像": ["肖像", "合照", "自拍", "全身照", "特写"],
    "宠物动物": ["猫", "狗", "鸟", "野生动物", "水族"],
    "美食图片": ["中餐", "西餐", "甜点", "饮品", "烘焙"],
    "城市建筑": ["高楼", "街道", "桥梁", "古建筑", "夜景"],
    "电子截图": ["网页", "代码", "社交媒体", "聊天记录", "应用界面"],
    "文档表格": ["文件", "笔记", "表格", "书籍", "海报"],
    "街拍": ["行人", "市集", "交通", "橱窗", "咖啡厅"],
}


class CLIPEngine(BaseEngine):
    """CLIP local inference via sentence-transformers (clip-ViT-B-32)."""

    _model: SentenceTransformer | None = None
    _text_embeddings: np.ndarray | None = None

    def __init__(self, model_name: str = "clip-ViT-B-32", **kwargs):
        self.model_name = model_name

    def _ensure_model(self):
        """Lazy-load the CLIP model and pre-compute text embeddings."""
        if CLIPEngine._model is None:
            CLIPEngine._model = SentenceTransformer(self.model_name)
            prompts = list(CATEGORIES.values())
            CLIPEngine._text_embeddings = CLIPEngine._model.encode(
                prompts, convert_to_numpy=True, normalize_embeddings=True
            )

    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
        extra_context: str = "",
    ) -> AnalysisResult:
        self._ensure_model()
        model = CLIPEngine._model
        text_embs = CLIPEngine._text_embeddings

        # Decode image
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Get image embedding
        img_emb = model.encode(
            [image], convert_to_numpy=True, normalize_embeddings=True
        )

        # Cosine similarity (embeddings are already normalized)
        scores = (img_emb @ text_embs.T)[0]

        # Get top category
        cat_names = list(CATEGORIES.keys())
        top_idx = int(np.argmax(scores))
        category = cat_names[top_idx]
        confidence = float(scores[top_idx])

        # Generate tags from top-2 categories + subtags
        sorted_indices = np.argsort(scores)[::-1]
        tags = [category]
        for idx in sorted_indices[:2]:
            cat = cat_names[idx]
            subtags = CATEGORY_SUBTAGS.get(cat, [])
            if subtags:
                tags.extend(subtags[:2])
        # Deduplicate while preserving order
        seen = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)

        # Generate slug from category
        slug_map = {
            "自然风光": "nature",
            "人像": "portrait",
            "宠物动物": "animal",
            "美食图片": "food",
            "城市建筑": "architecture",
            "电子截图": "screenshot",
            "文档表格": "document",
            "街拍": "street",
        }
        slug = slug_map.get(category, "photo")

        return AnalysisResult(
            category=category,
            tags=unique_tags[:6],
            description=f"{category}类照片",
            slug=slug,
            engine="clip",
            raw_response=f"scores: {dict(zip(cat_names, [f'{s:.3f}' for s in scores]))}",
        )

    async def test_connection(self) -> dict:
        try:
            self._ensure_model()
            return {"ok": True, "message": f"CLIP model '{self.model_name}' loaded successfully"}
        except Exception as e:
            return {"ok": False, "message": f"CLIP load error: {e}"}
