## Photo-Aiid-system - 设计文档

文件名: `docs/plans/2026-04-22-photo-studio-design.md`
https://kollab.im/task/046a9f02-426c-4255-bf65-27c9ae5569e4
---

### 1. 概述

产品名称: Photo-Aiid-system（AI 照片智能管理系统）

目标用户: 职业摄影师 / 工作室

核心价值:

- 本地 AI 快速识别照片主题，自动打标
- 基于原文件命名智能生成关键词索引目录
- 多维度批量编辑（EXIF、水印、重命名、分类）
- 云端同步支持多设备、多人协作

---

### 2. 技术架构

|层级|技术选型|说明|
|---|---|---|
|UI 层|SwiftUI|原生 macOS 体验|
|数据层|SwiftData|类型安全、原生集成|
|AI 识别|Vision + Core ML|本地优先，云端兜底|
|同步服务|CloudKit|Apple 原生、端到端加密|
|存储|本地文件 + CloudKit|原文件本地，元数据云端|

---

### 3. 核心数据模型

```
PhotoAsset
├── id: UUID
├── fileName: String (原文件名)
├── filePath: String (本地路径)
├── fileSize: Int64
├── createdAt: Date
├── exifData: EXIFInfo
├── tags: [Tag] (AI + 手动)
├── keywords: [String] (关键词索引)
├── project: Project? (所属项目)
└── cloudStatus: SyncStatus

Project
├── id: UUID
├── name: String
├── client: String? (客户名)
├── createdAt: Date
├── photos: [PhotoAsset]
└── status: ProjectStatus

Tag
├── id: UUID
├── name: String
├── category: TagCategory (主题/场景/人物/地点)
└── source: TagSource (AI/Manual/System)

GlobalTagLibrary
├── tags: [Tag] (跨项目统一)
└── aliases: [String: String] (同义词映射)
```

---

### 4. 核心功能模块

#### 4.1 照片导入与识别

```
导入流程:
1. 用户拖入照片文件夹
2. 系统读取 EXIF 元数据
3. Vision.framework 本地识别:
   - 物体识别 (VNClassifyImageRequest)
   - 场景识别 (VNRecognizeAnimalsRequest)
   - 人脸检测 (VNDetectFaceRectanglesRequest)
4. 识别结果 → 自动打标
5. 解析原文件名提取关键词:
   - 模板: {日期}_{地点}_{主题}_{摄影师}.jpg
   - 规则引擎匹配
6. CloudKit 同步元数据
```

#### 4.2 关键词索引目录

|索引类型|生成方式|存储位置|
|---|---|---|
|文件级|AI 识别 + 文件名解析|CloudKit|
|项目级|按 Project 聚合|CloudKit|
|全局标签库|用户自定义 + AI 学习|CloudKit|

目录结构示例:

```
📁 2024- Wedding_Alice
├── 📁 Original
│   ├── IMG_001.jpg
│   └── IMG_002.jpg
├── 📁 Edited
├── 📁 Keywords
│   ├── IMG_001.keywords.json
│   └── index.json
└── 📁 Export
```

#### 4.3 批量编辑

|功能|说明|
|---|---|
|EXIF 编辑|批量修改日期、版权、GPS、相机信息|
|水印|预设模板：文字/图片水印，可批量应用|
|重命名|模板变量：`{project}_{date}_{seq}_{original}`|
|标签操作|批量添加/移除/替换标签|

#### 4.4 云端协作

- CloudKit 私有数据库存储元数据
- 原文件存储在本地，通过 `CKAsset` 引用
- 支持多用户实时同步标签/项目状态
- 冲突解决：最后写入优先 + 版本历史

---

### 5. UI 设计方向

```
┌─────────────────────────────────────────────────────────────┐
│  Photo-Aiid-system                                              [👤]
├─────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────────────────────────────────────────┐ │
│ │ Projects│ │  📷 Photo Grid / List View                  │ │
│ │         │ │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐            │ │
│ │ □ Wedding│ │  │ img │ │ img │ │ img │ │ img │            │ │
│ │ □ Product│ │  │ tag │ │ tag │ │ tag │ │ tag │            │ │
│ │ □ Portrait│ │  └─────┘ └─────┘ └─────┘ └─────┘            │ │
│ │         │ │                                             │ │
│ │─────────│ │  [🔍 Search]  [⚡ AI Auto-tag]  [✏️ Batch]  │ │
│ │ Tags    │ │                                             │ │
│ │ 🏔️ 风景 │ └─────────────────────────────────────────────┘ │
│ │ 👤 人像 │ ┌─────────────────────────────────────────────┐ │
│ │ 🍽️ 美食 │ │  Photo Detail / Batch Edit Panel           │ │
│ └─────────┘ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

设计风格: Apple 原生风格，参考 Finder + Photos

---

### 6. 技术亮点

|功能|实现方式|
|---|---|
|AI 主题识别|Vision + Core ML，本地推理|
|批量处理|Swift Concurrency (async/await) + Actor|
|索引检索|SwiftData predicate + CloudKit query|
|离线优先|CloudKit + local cache 双写|
|性能优化|LazyVGrid + 缩略图缓存|

---

### 7. 项目里程碑

|阶段|目标|优先级|
|---|---|---|
|v1.0|本地照片导入 + Vision 识别 + 基础标签|P0|
|v1.1|批量编辑（EXIF、重命名）|P0|
|v1.2|项目管理与文件级索引|P1|
|v1.3|CloudKit 同步基础版|P1|
|v2.0|全局标签库 + 多人协作|P2|

---

设计方案到此完成。