"""
AI Engine registry for Photo-Aiid-system.

Engines are loaded lazily. CLIP is optional and will not be registered
if sentence-transformers is not installed.
"""

from engines.base import BaseEngine
from engines.claude_engine import ClaudeEngine
from engines.ollama_engine import OllamaEngine
from engines.gemini_engine import GeminiEngine
from engines.zhipu_engine import ZhipuEngine

# Registry: name -> engine class
ENGINE_REGISTRY: dict[str, type[BaseEngine]] = {
    "claude": ClaudeEngine,
    "ollama": OllamaEngine,
    "gemini": GeminiEngine,
    "zhipu": ZhipuEngine,
}

# Try to register CLIP (optional dependency)
try:
    from engines.clip_engine import CLIPEngine
    ENGINE_REGISTRY["clip"] = CLIPEngine
except ImportError:
    pass  # sentence-transformers not installed – skip


def get_engine(name: str, **kwargs) -> BaseEngine:
    """Instantiate an engine by name."""
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(ENGINE_REGISTRY.keys())
        raise ValueError(f"Unknown engine '{name}'. Available: {available}")
    return cls(**kwargs)


def list_engines() -> list[dict]:
    """Return available engines with metadata."""
    result = []
    for name, cls in ENGINE_REGISTRY.items():
        result.append({
            "name": name,
            "description": cls.__doc__ or name,
            "available": True,
        })
    # Always list CLIP even if unavailable
    if "clip" not in ENGINE_REGISTRY:
        result.append({
            "name": "clip",
            "description": "CLIP local inference (requires sentence-transformers)",
            "available": False,
        })
    return result
