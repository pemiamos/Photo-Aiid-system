"""中文查询 → 英文查询的轻量词典（摄影场景）。

为什么需要它
------------
CLIP ViT-B/32 的文本塔是英文训练的，中文只能靠 byte-level BPE 的字节模式蹭到
一点语义。实测：

    纯中文查询   与英文基准 top10 重合  1%
    中英混合                           31%
    纯英文（词典替换）                  85%

关键结论是**中文必须整个丢掉**——"猫 cat" 能到 60%，但"猫在草地上 cat grass"
只到 20%，因为中文 token 把英文淹了。所以这里做的是「替换」而不是「补充」。

为什么不用翻译模型
------------------
opus-mt-zh-en 一类要 +300MB 模型、+200ms/查询，而摄影查询的词汇高度集中，
一张 150 条的词表就能覆盖绝大多数场景。零下载、零延迟。

代价：词表没收录的词会丢。表现为查询"什么都没命中"时保留原文——至少不比原来差。
"""
from __future__ import annotations

import re

# 中文键 → 英文值。值可以是短语；空字符串表示停用词（直接丢弃）。
# 匹配时按「键长度降序」，所以 "江边" 先于 "江"，"古建筑" 先于 "建筑"。
LEXICON: dict[str, str] = {
    # ── 自然 / 地理 ──
    "山脉": "mountain range", "山": "mountain", "雪山": "snow mountain",
    "河流": "river", "河": "river", "江边": "riverside", "江": "river",
    "湖泊": "lake", "湖": "lake", "海边": "seaside", "海": "sea",
    "水面": "water surface", "水下": "underwater", "水": "water",
    "瀑布": "waterfall", "溪流": "stream", "倒影": "reflection",
    "沙滩": "beach", "礁石": "rock", "岩石": "rock", "石头": "stone",
    "草地": "grass", "草原": "grassland", "森林": "forest", "树林": "woods",
    "树叶": "leaves", "落叶": "fallen leaves", "树": "tree", "竹子": "bamboo",
    "沙漠": "desert", "雪": "snow", "雨": "rain", "雾": "fog", "云": "clouds",
    "天空": "sky", "日落": "sunset", "日出": "sunrise", "晚霞": "sunset glow",
    "彩虹": "rainbow", "月光": "moonlight", "星空": "starry sky",
    # ── 动物 ──
    "猫": "cat", "狗": "dog", "鸟": "bird", "蝴蝶": "butterfly", "昆虫": "insect",
    "蜜蜂": "bee", "鱼": "fish", "马": "horse", "牛": "cattle", "羊": "sheep",
    "兔子": "rabbit", "松鼠": "squirrel", "鸭子": "duck", "天鹅": "swan",
    "野生动物": "wildlife",
    # ── 植物 ──
    "花卉": "flowers", "花朵": "flowers", "花": "flowers",
    "樱花": "cherry blossom", "荷花": "lotus", "向日葵": "sunflower",
    "玫瑰": "rose", "郁金香": "tulip", "苔藓": "moss", "植物": "plant",
    # ── 人物 ──
    "人像": "portrait", "人物": "person", "人": "person",
    "女人": "woman", "男人": "man", "女孩": "girl", "男孩": "boy",
    "孩子": "child", "儿童": "child", "老人": "elderly person",
    "情侣": "couple", "游客": "tourist", "摄影师": "photographer",
    "背影": "back view of a person", "侧脸": "profile of a face",
    "自拍": "selfie", "合影": "group photo", "肖像": "portrait", "人群": "crowd",
    # ── 建筑 ──
    "古建筑": "chinese temple architecture", "古塔": "chinese temple tower",
    "寺庙": "temple", "教堂": "church", "塔": "tower", "亭子": "pavilion",
    "牌坊": "memorial arch", "桥": "bridge", "桥梁": "bridge",
    "建筑": "building", "楼房": "building", "高楼": "skyscraper",
    "校园": "campus", "学校": "school", "工厂": "factory", "城堡": "castle",
    "屋顶": "roof", "墙": "wall", "石阶": "stone steps", "窗户": "window",
    # ── 街景 ──
    "街景": "street scene", "街道": "street", "马路": "road",
    "夜市": "night market", "招牌": "signboard", "路灯": "street lamp",
    "栏杆": "railing", "台阶": "steps", "广场": "square", "集市": "market",
    "夜景": "night view",
    # ── 交通 ──
    "汽车": "car", "车": "car", "自行车": "bicycle", "摩托": "motorcycle",
    "火车": "train", "地铁": "subway", "高铁": "high-speed train",
    "帆船": "sailboat", "船": "boat", "飞机": "airplane", "缆车": "cable car",
    # ── 生活 / 物品 ──
    "美食": "food", "食物": "food", "菜": "dish", "咖啡": "coffee",
    "茶杯": "tea cup", "餐具": "tableware", "书": "book", "书包": "backpack",
    "花盆": "flower pot", "家具": "furniture", "门": "door",
    # ── 文档 ──
    "文档": "document", "截图": "screenshot", "文件": "document",
    "表格": "spreadsheet", "文字": "text",
    # ── 风格 / 构图 ──
    "风景": "landscape", "风光": "landscape", "特写": "close-up",
    "远景": "wide shot", "全景": "panorama", "剪影": "silhouette",
    "逆光": "backlit", "虚化": "bokeh", "黑白": "black and white",
    # ── 停用词（丢）──
    "照片": "", "拍摄": "", "一个": "", "一张": "", "一些": "",
    "的": "", "在": "", "和": "", "与": "", "着": "", "了": "",
}

# 按长度降序，长词优先匹配（"古建筑" 先于 "建筑"，"江边" 先于 "江"）
_KEYS = sorted(LEXICON, key=len, reverse=True)

# 词典命中率低于此值就认为"没收录"，退回原文
MIN_HIT_RATIO = 0.34


def expand(query: str) -> tuple[str, list[tuple[str, str]], float]:
    """把中文查询替换成英文关键词。

    返回 (英文查询, 命中的词对, 字符覆盖率)。
    覆盖率低于 MIN_HIT_RATIO 时返回空英文串，调用方应回退原文。
    """
    if not query:
        return "", [], 0.0

    rest = query
    hits: list[tuple[str, str]] = []
    covered = 0
    for k in _KEYS:
        if k in rest:
            v = LEXICON[k]
            if v:
                hits.append((k, v))
            covered += len(k) * rest.count(k)
            rest = rest.replace(k, " ")
    # 去掉重复的英文值，保持原顺序
    seen: set[str] = set()
    words: list[str] = []
    for _, v in hits:
        if v not in seen:
            seen.add(v)
            words.append(v)
    en = " ".join(words)
    ratio = covered / max(len(query), 1)
    if not en or ratio < MIN_HIT_RATIO:
        return "", hits, ratio
    return en, hits, ratio


def has_cjk(s: str) -> bool:
    """查询里是否含中日韩字符。"""
    return bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", s or ""))