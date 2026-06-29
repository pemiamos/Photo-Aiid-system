"""共享视觉分析提示词。

Claude / 智谱 / Gemini / Ollama 四个引擎共用同一段 TAG_PROMPT，集中在此维护，
避免四处复制导致不一致。各引擎 `from engines.prompt import TAG_PROMPT` 使用。
"""

TAG_PROMPT = """Analyze this photo for a photo-indexing app. Reason in English internally for accuracy, then output Chinese labels.
You are also given the file's name and the folder path it lives in. These often carry human-authored context (event, place, date, project, client, subject). Treat them as strong hints: cross-check them against what you actually see in the image. When the filename/folder names a specific place, person, event or theme that is consistent with the image, fold that into the category/tags/description; if they clearly contradict the image, trust the image and ignore the misleading name.
特别规则（务必遵守）：
1) 摄影师：文件名或文件夹中常含摄影师名，可能是真名、昵称、网名或拼音（如「戴频」「老王」「Ansel」）。必须把它填入 photographer 字段，同时加入 tags、并在 desc 中点明（如「戴频 摄」）。务必不要遗漏。
2) 地名：若文件名或文件夹中出现地名，必须把它加入 tags 与 desc；但若该地名与下方「GPS定位地名」重复或同义，则省略以免重复。
Respond with ONLY a JSON object, no markdown fences, no preamble:
{"category":"主类别·二级子类，用「·」连接两级，使分类更细（如 自然风光·日落、人像·儿童、建筑·古建筑、街拍·夜市、美食·甜点、动物·昆虫）。主类判定规则：①若画面主体是某一物种(鸟/兽/鱼/虫/花草等生物)，主类一律为「物种」，子类填更具体的类群（如 物种·猛禽、物种·鸣禽、物种·两栖、物种·菊科）；②否则若文件名或文件夹中含具体地点/事件名，则主类优先采用它（如 兰亭、阳澄湖、龙舟赛），子类填更细的场景或主题；③否则主类用你识别的画面大类(2-4字，如 自然风光/人像/美食/建筑/街拍)，子类填该大类下更具体的细分。子类要具体、2-6字；确实无法细分时可只输出主类、省略「·子类」。无论如何 tags 都要由你识别生成、不可省略","tags":["3到6个中文标签，可包含从文件名/文件夹推断出的地点/事件/项目等信息"],"desc":"一句不超过30字的中文画面描述（如有摄影师/地名需包含）","location":"拍摄地点（市/县级）：优先采用文件名/文件夹中的明确地名，否则结合画面地标推断到市县级；不要包含国家和省份，多级地名用-连接（如 苏州-甪直、绍兴-兰亭、盐城）；无法判断则留空","place_in_name":"文件名或文件夹中明确写出的、真实且具体的地名原文（如 石臼湖、阳澄湖、兰亭、甪直、某村/某镇/某山/某景点）。严格排除：方向性或泛指词（如 沿长江、江边、湖区）、项目/系列/主题/活动名、以及画面主体或景物描述（如 灌溉网络湿地、农田）。这些一律不要填进本字段。只填确实出现在文件名/文件夹里的真实地名，拿不准或没有则留空字符串","photographer":"摄影师的姓名或昵称：从文件名或文件夹中提取，可能是真名/昵称/网名/拼音（如 戴频、老王、Ansel）；无法判断则留空字符串","slug":"short-english-slug-for-filename"}"""
