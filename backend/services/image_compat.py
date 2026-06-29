"""Pillow 大图与 HEIC/HEIF 解码兼容设置。

只要在用到 PIL 之前 `import services.image_compat` 一次即生效：

- **解除超大图像的 DecompressionBomb 限制**：本工具处理的是用户本地照片，
  不存在恶意构造的「解压炸弹」风险；而 Pillow 默认上限（约 8900 万像素）会让
  上亿像素的大图在解码时抛异常，导致缩略图与 AI 分析「双双失败」。
- **注册 HEIC/HEIF 解码**：iPhone 默认格式，缺少 pillow-heif 插件时 PIL 根本
  打不开 `.heic`，照片会卡在「待分析」且无缩略图。插件缺失时静默跳过。
"""

from PIL import Image

# None 表示不限制像素数，超大图也能正常解码。
Image.MAX_IMAGE_PIXELS = None

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # pragma: no cover - 插件缺失时降级
    HEIF_SUPPORTED = False
