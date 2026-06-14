"""
Abstract base class for all AI engines.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Standard result from any engine."""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    slug: str = ""
    location: str = ""
    place_in_name: str = ""  # 文件名/文件夹中明确写出的地名原文
    photographer: str = ""
    engine: str = ""
    raw_response: str = ""


class BaseEngine(ABC):
    """Base class that all engines must implement."""

    @abstractmethod
    async def analyze(
        self,
        image_bytes: bytes,
        file_name: str = "",
        folder_path: str = "",
        extra_context: str = "",
    ) -> AnalysisResult:
        """
        Analyze an image and return structured result.

        Args:
            image_bytes: JPEG/PNG thumbnail bytes
            file_name: Original filename (context hint)
            folder_path: Folder path (context hint)
            extra_context: Additional free-form context (e.g. adjacent filenames)
        """
        ...

    async def test_connection(self) -> dict:
        """Test if the engine is reachable / functional."""
        return {"ok": True, "message": "Engine available"}
