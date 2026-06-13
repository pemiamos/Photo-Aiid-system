"""
Offline reverse geocoding for Photo-Aiid-system.

China: nearest-neighbour over an offline district-centroid dataset (DataV
GeoAtlas) → city·county in Chinese, e.g. "苏州市 · 吴中区".
Elsewhere: the bundled `reverse_geocoder` (GeoNames) → romanized name plus a
Chinese country label.
"""

import json
import logging
import math
import os
import re

logger = logging.getLogger(__name__)

# Province / autonomous-region bare names. Direct-administered municipalities
# (北京/上海/天津/重庆) are intentionally NOT here — they double as the city.
_STRIP_PROVINCES = [
    "黑龙江", "内蒙古", "广西", "西藏", "新疆", "宁夏", "河北", "山西", "辽宁",
    "吉林", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北",
    "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
]


def normalize_location(loc: str) -> str:
    """Normalize a place name: drop country/province prefixes, join levels with
    '-'. Keeps city·county (e.g. '上海市-黄浦区', '盐城市')."""
    if not loc:
        return ""
    s = re.sub(r"[·,，/、\s]+", "-", loc.strip())
    # Drop a leading country.
    for c in ("中华人民共和国", "中国"):
        if s.startswith(c):
            s = s[len(c):].lstrip("-")
    # Drop a leading province name in any common form.
    for prov in _STRIP_PROVINCES:
        for form in (prov + "省", prov + "自治区", prov):
            if s.startswith(form):
                s = s[len(form):].lstrip("-")
                break
        else:
            continue
        break
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cn_districts.json")

# If the nearest Chinese district centroid is farther than this, treat the
# coordinate as outside mainland China and fall back to reverse_geocoder.
_CN_MAX_KM = 120.0

# Lazily-built China district index.
_cn_loaded = False
_cn_lats = None      # numpy array
_cn_lngs = None      # numpy array
_cn_names: list[str] = []

# Common country codes -> Chinese (for non-China results).
_COUNTRY_CN = {
    "JP": "日本", "KR": "韩国", "US": "美国", "GB": "英国", "FR": "法国",
    "DE": "德国", "IT": "意大利", "ES": "西班牙", "TH": "泰国", "SG": "新加坡",
    "MY": "马来西亚", "AU": "澳大利亚", "CA": "加拿大", "RU": "俄罗斯",
    "IN": "印度", "VN": "越南", "ID": "印度尼西亚", "NZ": "新西兰", "CH": "瑞士",
    "HK": "香港", "MO": "澳门", "TW": "台湾",
}


def _load_cn_index():
    global _cn_loaded, _cn_lats, _cn_lngs, _cn_names
    if _cn_loaded:
        return
    _cn_loaded = True
    try:
        import numpy as np
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        by_code = {x["adcode"]: x for x in data}
        lats, lngs, names = [], [], []
        for x in data:
            if x.get("level") not in ("district", "city"):
                continue
            if x.get("lat") is None or x.get("lng") is None:
                continue
            self_name = x["name"]
            if x["level"] == "district":
                parent = by_code.get(x.get("parent"), {}).get("name", "")
                display = f"{parent}-{self_name}" if parent and parent not in self_name else self_name
            else:
                display = self_name
            lats.append(x["lat"])
            lngs.append(x["lng"])
            names.append(display)
        _cn_lats = np.array(lats)
        _cn_lngs = np.array(lngs)
        _cn_names = names
        logger.info(f"Loaded {len(names)} China district centroids for geocoding")
    except Exception as e:
        logger.warning(f"Could not load China district dataset: {e}")
        _cn_names = []


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest_cn(lat, lon):
    """Return (display_name, distance_km) for the nearest China district."""
    _load_cn_index()
    if not _cn_names:
        return "", None
    import numpy as np
    # Cheap squared-degree metric to pick the candidate, then exact haversine.
    coslat = math.cos(math.radians(lat))
    d2 = (_cn_lats - lat) ** 2 + ((_cn_lngs - lon) * coslat) ** 2
    idx = int(np.argmin(d2))
    dist = _haversine_km(lat, lon, float(_cn_lats[idx]), float(_cn_lngs[idx]))
    return _cn_names[idx], dist


def _rg_fallback(lat, lon) -> str:
    """Non-China: romanized place name + Chinese country label."""
    try:
        import reverse_geocoder as rg
        results = rg.search([(float(lat), float(lon))], mode=1, verbose=False)
        if not results:
            return ""
        r = results[0]
        name = (r.get("name") or "").strip()
        admin1 = (r.get("admin1") or "").strip()
        cc = (r.get("cc") or "").strip()
        parts = [p for p in (admin1, name) if p]
        loc = "-".join(parts)
        country = _COUNTRY_CN.get(cc, cc)
        if country and loc:
            return f"{country}-{loc}"
        return loc or country
    except Exception as e:
        logger.warning(f"reverse_geocoder fallback failed for ({lat}, {lon}): {e}")
        return ""


def reverse_geocode(lat, lon) -> str:
    """Return a readable place name for a coordinate, or "" if unavailable."""
    if lat is None or lon is None:
        return ""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return ""
    # Try China district dataset first (gives Chinese city·county names).
    name_cn, dist = _nearest_cn(lat, lon)
    if name_cn and dist is not None and dist <= _CN_MAX_KM:
        return name_cn
    # Otherwise resolve as a non-China location.
    return _rg_fallback(lat, lon)
