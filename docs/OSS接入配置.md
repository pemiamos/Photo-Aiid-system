# 阿里云 OSS 直传接入配置

> 配置齐全后，摄影师上传页自动切换为「浏览器直传 OSS（STS 临时凭证 + 分片/断点续传）」，
> 文件不经过你的后端服务器；任一配置缺失则自动回退本地直存模式，原型照常可跑。

---

## 1. 工作原理

```
摄影师浏览器 ──① POST /api/intake/sts（带投稿码）──> 后端
后端 ──AssumeRole（限定到 {bucket}/{书}/{投稿码-姓名}/*）──> 阿里云 STS
后端 ──返回临时凭证（1 小时、仅可写该前缀）──> 浏览器
摄影师浏览器 ──② ali-oss multipartUpload 分片直传──> OSS 桶
摄影师浏览器 ──③ POST /api/intake/record 登记元数据──> 后端（写 SQLite）
```

- 后端**只发凭证、记元数据**，大文件不过后端，1 核 1G 机器即可扛上百人。
- 临时凭证用 RAM Policy **限定到该摄影师自己的前缀**，越权写入会被 OSS 拒绝；后端 `/record` 再次校验 `object_key` 落在该前缀内。

---

## 2. 阿里云侧准备（一次性）

### 2.1 创建 OSS 桶
- 控制台创建桶，如 `photo-intake`，地域如华东1（杭州）`oss-cn-hangzhou`。
- 记下**地域 ID**（ali-oss 用带 `oss-` 前缀的形式：`oss-cn-hangzhou`）。

### 2.2 配置桶的 CORS（关键，否则浏览器直传被拦）
桶 → 权限管理 → 跨域设置，新增规则：
- 来源 Sources：上传页所在域名，如 `https://你的域名`（本机调试可加 `http://127.0.0.1:8000`）
- 允许 Methods：`POST, PUT, GET`
- 允许 Headers：`*`
- 暴露 Headers：`ETag, x-oss-request-id`
- 缓存时间：`600`

### 2.3 创建 RAM 角色（被扮演的角色）
- RAM → 角色 → 创建角色，可信实体选「阿里云账号」（本账号）。
- 给该角色授予对**该桶的写权限**（可用系统策略 `AliyunOSSFullAccess`，或自定义只读写 `photo-intake`）。
- 记下角色 ARN：`acs:ram::账号ID:role/角色名`。

### 2.4 创建发凭证用的 RAM 用户
- RAM → 用户 → 创建用户，开启「编程访问」，拿到 AK/SK。
- 给该用户授予 `AliyunSTSAssumeRoleAccess`（允许调用 STS AssumeRole）。
- **这对 AK/SK 只放在你的服务器环境变量里，绝不进前端、绝不进安装包。**

---

## 3. 后端环境变量

启动后端前设置（缺一即回退本地模式）：

```bash
export OSS_REGION="oss-cn-hangzhou"                 # 带 oss- 前缀
export OSS_BUCKET="photo-intake"
export OSS_ACCESS_KEY_ID="RAM用户的AK"
export OSS_ACCESS_KEY_SECRET="RAM用户的SK"
export OSS_STS_ROLE_ARN="acs:ram::账号ID:role/角色名"
# 可选：export OSS_STS_DURATION="3600"   # 临时凭证有效期（秒）
```

启动后访问 `GET /api/intake/oss-config`：
- 返回 `{"mode":"oss",...}` → 已切到直传。
- 返回 `{"mode":"local"}` → 仍是本地模式，检查上面 5 个变量。

---

## 4. 验证清单
1. `/api/intake/oss-config` 返回 `mode=oss`。
2. 打开 `/intake?code=A01`，拉入照片、标注、提交。
3. 浏览器开发者工具 Network 中应看到请求直接打到 `https://{bucket}.{region}.aliyuncs.com`（不是你的后端）。
4. OSS 控制台桶内出现 `2026-sanxia/A01-张伟/{标注}/文件名`。
5. `/intake/admin` 看板该摄影师张数 +N。

常见报错：
- 浏览器报 CORS 错 → 2.2 没配好。
- `STS 获取临时凭证失败` → 2.3/2.4 的角色 ARN、AssumeRole 权限或 AK/SK 有误。
- 上传 403 → RAM 角色对桶无写权限，或前缀越权。

---

## 5. 生产化待办（上线前）
- [ ] 管理接口 `/api/intake/admin/*` 加管理员鉴权（当前原型未鉴权）。
- [ ] 上传页走 HTTPS + 正式域名，并把域名加入 OSS CORS。
- [ ] 截稿后用 `rclone` 把整本搬到 Cloudflare R2 归档（见 PRD 第 3.3）。
- [ ] AK/SK 用最小权限子账号，定期轮换。
