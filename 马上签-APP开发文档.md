# 马上签 · APP 开发文档（API + UI）

> 版本：v2.5.0 ｜ 更新：2026-10-21 ｜ 适用：马上签 Android APP（服务端 API v2.5.0）
> 配套文档：《位置模拟签到-APP对接文档.md》《自动刷课-功能计划书.md》｜ OpenAPI 源：`http://xxt.leich.cn/openapi.json`
> v2.3 变更：新增「协助签到（同学帮签）」——二维码/手势/签到码三类改为进入待协助队列并推送协助链接，同学打开 `/assist/<token>` 提交 enc 或手势轨迹即可代签；账号 summary 新增 `assist_pending` / `assist_link` 字段
> v2.3.2 变更：扫码体验加固——二维码「扫完即验效」。老师投屏的二维码刷新很快，同学扫到的码提交时常常已经失效。本次更新后，协助签到页（`/assist/<token>`）的扫码流程会即时校验二维码并给出明确反馈：① 扫到有效签到码——绿色提示「二维码有效，正在提交…」，随即自动完成代签；② 扫到已失效的码——红色提示「二维码已失效（老师屏幕的码刷新很快），请扫最新的码」，并自动重新打开摄像头，同学对准最新码即可；③ 扫到的不是签到码——提示「请对准老师屏幕的二维码」，约 1 秒后自动继续识别。防护细节：同一个码 3 秒内不会重复提交，不会对着没刷新的旧码死循环；网络异常等非失效类失败会关闭摄像头，避免空转耗电；摄像头不可用或识别失败时，仍保留手动粘贴链接 / enc 的兜底提交方式。手势九宫格直选、签到码输入两条通道不受影响。
> v2.4.0 变更：新增 APP 闪屏配置——后台管理页「APP闪屏」可设置闪屏图片链接、展示秒数（1~10）、点击跳转链接与启用开关；APP 启动时拉取配置，展示到时间自动进入首页，点击闪屏可跳转配置的链接。新增公开接口 `/api/app/splash` 与管理接口 `GET/PUT /api/admin/splash`。
> v2.5.0 变更：协助签到扫码体验两项修复——① 内置浏览器引导：检测到微信 / QQ / 微博 / 钉钉 / 支付宝 / 抖音等 App 内置 WebView 打开协助链接时（这些环境普遍禁用摄像头），页面自动弹出「请使用浏览器打开」引导浮层，按 iOS / Android 分别给出「在 Safari 中打开 / 在浏览器中打开」步骤，并提供「🌐 用浏览器打开」（Android 尝试 intent 跳转系统浏览器，被微信拦截时静默失败；iOS 无程序化跳转能力，自动降级）、「📋 复制链接」（剪贴板 API + 卡片内嵌输入框降级）两个按钮；摄像头调用失败时会再次弹出引导。② 扫码画质增强：摄像头采集提升到 1080p（ideal 1920×1080）、自动优选后置摄像头（enumerateDevices + deviceId）、开启连续对焦（focusMode: continuous）；识别算法改为「全画幅 → 中心 60% → 中心 35%」三档视野逐帧轮换扫描（等价逐级放大），远距离投屏的小二维码也能拿到足够的模块像素，不再需要贴到老师脸上才能扫；新增「🔍 放大」按钮——采用**数字变焦**（预览 2 倍放大 + 扫描区同步切换中心裁剪，视觉与识别对齐），不依赖硬件 zoom 能力，iOS / 微信等所有环境均可用；「🔦 开灯」（手电筒）需硬件支持，设备不支持时自动隐藏。
> v2.2 变更：服务端上线三层防限频机制——监控间隔自适应（max(60, 课程数×2) 秒，用户配置只能调长）、±20% 抖动、连续 2 轮大面积受限自动冷却 15 分钟（看门狗到点自愈）；账号 summary 新增 `interval` / `freq_cooldown` 字段
> v2.1 变更：新增站内消息中心（公告/签到/工单/系统）与后台邮件群发（内置模板 + 任务轮询）

---

## 目录

- 一、系统概述
- 二、通用约定
- 三、API 参考
  - 3.1 鉴权模块
  - 3.2 学习通账号与扫码登录
  - 3.3 账号管理与监控
  - 3.4 位置模拟签到
  - 3.5 手动检测登录态与签到
  - 3.6 签到记录
  - 3.7 工单反馈
  - 3.8 APP 版本更新
  - 3.9 公告
  - 3.10 消息中心
  - 3.11 邮件群发（后台）
  - 3.12 后台管理 API（管理端可选）
- 四、核心数据结构
- 五、关键业务流程
- 六、UI 设计
- 七、技术选型建议
- 八、安全与合规

---

## 一、系统概述

马上签是一套「超星学习通自动签到」系统，由三端组成：

| 端 | 技术 | 职责 |
|---|---|---|
| 服务端 | Python Flask（`app.py` + `core.py`） | 登录态托管、监控轮询、自动签到、通知推送 |
| 网页端 | React 单文件应用（`/app`） | 完整功能操作台，本 APP 的 UI 蓝本 |
| **APP（本档主题）** | Android 原生 / Flutter / RN | 扫码登录、监控开关、位置选点、手动检测、记录查看 |

**核心分工原则**：

- 签到动作全部由**服务端监控线程**完成，APP **不自己调用学习通接口**。
- APP 只通过本文档的 REST API 与服务端交互。
- 学习通 Cookie 由服务端保管，APP 侧只持有**站点会话**（Session Cookie）。

签到类型与服务端处理策略：

| 学习通签到类型 | 服务端行为 |
|---|---|
| 普通签到 | 自动完成 |
| 位置签到 | 自动完成（需 APP 预设模拟坐标，见 3.4） |
| 二维码签到 | 提醒手动 |
| 手势 / 签到码 | 提醒手动 |
| 拍照签到 | 提醒手动 |

---

## 二、通用约定

| 项 | 值 |
|---|---|
| Base URL | `http://xxt.leich.cn` |
| 鉴权 | Session Cookie（登录后 Cookie 自动携带，APP 需开启 Cookie 持久化） |
| 请求格式 | `application/json`（GET 用 query） |
| 响应格式 | JSON |
| 字符集 | UTF-8 |

**通用响应包裹**：

```json
{ "ok": true,  ...业务字段 }
{ "ok": false, "msg": "错误原因" }
```

**HTTP 状态码**：业务错误一律返回 `200 + {"ok":false}` 或 `4xx + {"ok":false}`；APP 统一按 `ok` 字段判断成败即可，`msg` 可直接 toast 给用户。

**未登录**：返回 `401 {"ok":false,"msg":"请先登录"}`，APP 应跳转登录页。

**健康检查**（无需登录）：

```
GET /api/ping  →  { "ok": true }
```

---

## 三、API 参考

### 3.1 鉴权模块

#### 3.1.1 注册并登录

```
POST /api/auth/register
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | 是 | 用户名 |
| `password` | string | 是 | 密码 |
| `email` | string | 是 | QQ 邮箱（用于接收签到通知邮件） |

```json
// 成功
{ "ok": true, "user": { "username": "zhangsan", "role": "user",
  "created_at": "2026-10-19 10:00:00", "disabled": false, "email": "123@qq.com" } }
```

> 注册成功后自动登录（下发会话）。若管理员关闭了注册，返回 `403 {"ok":false,"msg":"管理员已关闭新用户注册"}`。

#### 3.1.2 登录

```
POST /api/auth/login
{ "username": "zhangsan", "password": "******" }
```

成功返回同上（`user` 对象）。失败返回 `401 {"ok":false,"msg":"用户名或密码错误"}`；被禁用返回 `403`。

#### 3.1.3 退出登录

```
POST /api/auth/logout  →  { "ok": true }
```

#### 3.1.4 获取当前用户

```
GET /api/auth/me
```

```json
// 已登录
{ "ok": true, "logged_in": true, "user": { ...同 3.1.1 user 对象 } }
// 未登录
{ "ok": true, "logged_in": false }
```

> APP 启动时调用此接口判断会话是否有效，决定进首页还是登录页。

#### 3.1.5 更新个人资料

```
PUT /api/auth/profile
{ "email": "新QQ邮箱", "password": "新密码" }   // 两个字段都可选，至少传一个
```

成功返回更新后的 `user` 对象。

---

### 3.2 学习通账号与扫码登录

#### 3.2.1 我的学习通账号列表

```
GET /api/accounts
```

```json
{
  "ok": true,
  "accounts": [
    {
      "acct_id": "418242009",
      "owner": "zhangsan",
      "name": "张三",
      "logged_in": true,
      "monitoring": false,
      "monitor_alive": false,
      "courses": 36,
      "records": 12,
      "manual_today": 0,
      "interval": 72,
      "freq_cooldown": 0,
      "need_relogin": false,
      "last_check": 1760000000.0
    }
  ]
}
```

`acct_id` 是后续所有账号级接口的路径参数，APP 需本地保存。字段含义见「四、核心数据结构」。

#### 3.2.2 生成扫码登录二维码

```
POST /api/qr/start
```

```json
{ "ok": true, "qr_id": "9f3c...", "qr": "data:image/png;base64,iVBORw0KGgo..." }
```

- `qr_id`：本次二维码会话 ID，轮询时传回。
- `qr`：base64 图片，APP 直接渲染（Android 可用 `Base64.decode` → `Bitmap`）。

#### 3.2.3 轮询扫码结果

```
GET /api/qr/poll?qr_id=9f3c...
```

建议 **2 秒轮询一次**。`status` 取值：

| status | 含义 | APP 动作 |
|---|---|---|
| `waiting` | 等待扫码 | 继续轮询 |
| `scanned` | 已扫码，待手机确认 | 提示「请在手机上确认」 |
| `confirmed` | 登录成功 | 停止轮询，刷新账号列表，提示成功 |
| `expired` | 二维码过期 | 自动重新 `POST /api/qr/start` 换新码 |
| `canceled` | 用户取消 | 重新生成二维码 |
| `failed` | 扫码成功但会话无效 | 提示重试 |

`scanned` 时附带 `nickname`；`confirmed` 时附带 `name`（学习通昵称）。

> 二维码有效期约数分钟，`expired` 后必须重新 start，不要复用旧 `qr_id`。

---

### 3.3 账号管理与监控

#### 3.3.1 账号详情（配置 + 课程）

```
GET /api/accounts/{acct_id}
```

```json
{
  "ok": true,
  "account": { ...summary 字段, "config": { ... }, "courses": [ ... ] }
}
```

`config` 字段：`interval`（轮询间隔秒，≥30 建议；实际生效值取 `max(60, 课程数×2, 用户配置)`，服务端防限频下限，v2.2）、`serverchan_key`（Server 酱 SendKey）、`enabled_courses`（启用监控的课程 key 列表，空数组=全部）、`monitor_on`、`need_relogin`、`loc_enabled` / `loc_lat` / `loc_lng` / `loc_addr`（位置模拟）。

#### 3.3.2 开启 / 停止监控

```
POST /api/accounts/{acct_id}/monitor
{ "on": true }        // true 开启，false 停止
→ { "ok": true, "monitoring": true }
```

#### 3.3.3 更新账号配置

```
POST /api/accounts/{acct_id}/config
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `interval` | int | 轮询间隔（秒），建议 ≥30；实际生效还要服从服务端防限频下限 `max(60, 课程数×2)`（v2.2） |
| `serverchan_key` | string | Server 酱 SendKey，可空 |
| `enabled_courses` | string[] | 启用监控的课程 `key` 列表；空数组表示全部 |
| `monitor_on` | bool | 配置项里的监控开关状态 |
| `loc_enabled` / `loc_lat` / `loc_lng` / `loc_addr` | — | 位置模拟（亦可走 3.4 专用接口） |

只传想改的字段即可（合并更新）。成功返回最新 `config`。

#### 3.3.4 课程列表 / 刷新

```
GET  /api/accounts/{acct_id}/courses            → { "ok": true, "courses": [...] }
POST /api/accounts/{acct_id}/courses/refresh    → { "ok": true, "courses": [...] }
```

课程对象：`{ "key": "课程ID:班级ID", "courseId", "classId", "chatid", "courseName", "className" }`。
学生新加入的课程不会立刻出现，下拉刷新即可从学习通重新拉取。

#### 3.3.5 账号监控状态（轮询用）

```
GET /api/accounts/{acct_id}/status
```

```json
{ "ok": true, "status": { ...summary 字段 }, "last_check": 1760000000.0, "rounds": 12, "errors": 0 }
```

APP 首页卡片建议每 10~30 秒轮询一次，实时反映「监控中 / 线程异常 / 未监控」「需重新登录」等状态。

#### 3.3.6 退出该学习通账号

```
POST /api/accounts/{acct_id}/logout  →  { "ok": true }
```

清除服务端 Cookie 并停止监控，账号卡片变为「未登录」，需重新扫码。

#### 3.3.7 测试 Server 酱推送

```
POST /api/accounts/{acct_id}/notify/test  →  { "ok": true, "sent": true, "msg": "..." }
```

#### 3.3.8 移除账号

```
DELETE /api/accounts/{acct_id}  →  { "ok": true }
```

删除该学习通账号及其记录（不影响站点账号）。

---

### 3.4 位置模拟签到

> 详细对接说明见《位置模拟签到-APP对接文档.md》，此处仅列接口要点。

**原理**：学习通位置签到（otherId=4）只校验提交的经纬度。服务端监控线程在位置签到出现时，自动提交 APP 预设的坐标。

#### 读取位置模拟配置

```
GET /api/accounts/{acct_id}/location
→ { "ok": true, "location": { "enabled": false, "lat": "", "lng": "", "address": "" } }
```

#### 设置位置模拟坐标（PUT，POST 等价）

```
PUT /api/accounts/{acct_id}/location
{ "enabled": true, "lat": "39.9092", "lng": "116.4074", "address": "综合楼301" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `enabled` | bool | 否 | 位置模拟开关；不传保持原值 |
| `lat` | string | 否 | 纬度 `-90 ~ 90`；不传保持原值 |
| `lng` | string | 否 | 经度 `-180 ~ 180`；不传保持原值 |
| `address` | string | 否 | 地址备注，可空 |

- 合并更新：只传想改的字段。
- `enabled=true` 时坐标必须合法，否则返回 `400` 且**不修改任何配置**。
- **坐标系**：高德/百度选点为 GCJ-02，手机 GPS 为 WGS-84；若提示「距离不符」，换另一种坐标系重试。

---

### 3.5 手动检测登录态与签到（v2 新增）

用户高频痛点：监控线程每 10 分钟才校验一次登录态，老师刚发的签到要等下一轮轮询。本接口让用户**立即**得到答案。

```
POST /api/accounts/{acct_id}/check
```

**同步执行**：先验证学习通登录态，再完整扫描一轮全部启用课程（数十门约需 10~60 秒，APP 需设置足够超时，建议 120 秒）。

成功：

```json
{
  "ok": true,
  "login_ok": true,
  "checked": 36,
  "found": [
    {
      "course": "高等数学(计科1班)",
      "activity": "第三讲 签到",
      "type": "普通/拍照",
      "result": "success",
      "detail": "签到成功"
    }
  ],
  "msg": "检查完成：已扫描 36 门课程，新签到 1 个"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `login_ok` | bool | 学习通登录态是否有效 |
| `checked` | int | 实际扫描的课程数 |
| `found` | array | 本次**新**检测到并已处理的签到活动（已处理过的不再出现） |
| `msg` | string | 面向用户的结论，可直接展示 |

`found[].result` 取值：`success`（自动签到成功）/ `fail`（自动签到失败，看 `detail`）/ `manual`（需手动完成，如二维码/拍照）。

失败场景（`ok:false`，HTTP 400）：

| 场景 | msg |
|---|---|
| 未绑定学习通账号 | `账号未登录，无法检查（请先扫码登录）` |
| 登录态已失效 | `学习通登录态已失效，请退出后重新扫码登录` |
| 上一次检查未结束 | `已有一次检查正在进行中，请稍候再试` |

> 登录态失效时服务端会自动置 `need_relogin=true` 并推送提醒，APP 应引导用户退出重新扫码。
> 检查成功且此前误报的 `need_relogin` 会被自动清除。

---

### 3.6 签到记录

```
GET /api/accounts/{acct_id}/records
→ { "ok": true, "records": [ { "time": "10-19 10:00:00", "course": "高等数学(计科1班)",
    "activity": "第三讲 签到", "type": "普通/拍照", "result": "success",
    "detail": "签到成功" } ] }
```

`result`：`success` / `fail` / `manual`。最新在前，单账号保留最近 200 条。

---

### 3.7 工单反馈

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/tickets` | POST | 提交工单，body：`{ "subject", "content", "category" }`，category ∈ `bug`/`feature`/`question`/`other` |
| `/api/tickets` | GET | 我的工单列表 |
| `/api/tickets/{tid}` | GET | 工单详情（含回复记录） |
| `/api/tickets/{tid}/reply` | POST | 回复工单，body：`{ "message" }` |

工单状态 `status`：`open` → `in_progress` → `resolved` / `closed`；优先级 `priority`：`low`/`normal`/`high`。

---

### 3.8 APP 版本更新

**公开接口，无需登录**，APP 启动时调用：

```
GET /api/app/version?version_code=3&version_name=1.0.3
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `version_code` | int | 当前 APP 版本序号（推荐带） |
| `version_name` | string | 当前版本号（无 code 时按此比较） |

返回：

```json
{
  "ok": true,
  "latest": {
    "version_name": "1.0.4", "version_code": 4,
    "download_url": "http://xxt.leich.cn/msq.apk",
    "update_log": "1. 新增手动检测\n2. 修复已知问题",
    "force_update": false, "min_supported_code": 0,
    "created_at": "2026-10-19 10:00:00"
  },
  "has_update": true,
  "force_update": false,
  "below_min_supported": false
}
```

- `has_update=true` 时弹更新窗，`download_url` 直接下载 APK。
- `force_update=true` 或 `below_min_supported=true` 时必须强制更新（遮罩不可跳过）。
- APK 也可直接固定下载 `http://xxt.leich.cn/msq.apk`。

---

### 3.9 公告

```
GET /api/announcements        → { "ok": true, "announcements": [ ... ] }   // 公开
```

公告对象：`{ "id", "title", "content", "type": "info|success|warning|error", "enabled", "created_at", "updated_at" }`。
APP 启动时拉取，以顶部横幅/弹窗展示（`type` 决定配色）。

---

### 3.10 消息中心（v2.1 新增）

站内消息按用户隔离，四类来源：**公告**（发布公告时群发）、**签到**（每次自动签到的结果）、**工单**（管理员回复时通知作者）、**系统**（邮件群发等系统通知）。

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/messages` | GET | 消息列表，query：`unread`（bool）、`type`（announcement/sign/ticket/system）、`limit`（默认 100），按 ID 倒序 |
| `/api/messages/unread-count` | GET | 未读数，侧边栏/底部 Tab 红点轮询（建议 30s） |
| `/api/messages/read-all` | POST | 全部标记已读 |
| `/api/messages/read/clear` | POST | 清空已读消息，返回 `removed` 条数 |
| `/api/messages/{mid}/read` | POST | 单条已读；消息不存在或不属于当前用户返回 `404` |

消息对象：

```json
{
  "id": 12, "type": "sign", "title": "签到成功：第三讲 签到",
  "content": "课程：高等数学(计科1班)\n活动：第三讲 签到\n类型：普通签到\n结果：签到成功\n时间：10-19 14:30:05",
  "ref_id": "", "read": false, "created_at": "2026-10-19 14:30:05"
}
```

- 每个用户最多保留最近 **300** 条，超出自动裁剪最旧的。
- `title` 规律：签到类为「签到成功/需手动签到/签到失败：活动名」；工单类为「工单 #{tid} 收到回复」；公告类为公告标题；系统类为邮件主题。
- 签到消息在签到结果写入时同步生成，失败不影响签到主流程。
- APP 侧建议：启动时与登录后各拉一次未读数；进入消息中心页拉列表；点击条目即调单条已读。

---

### 3.11 邮件群发（v2.1 新增，仅管理端）

通过 QQ 邮箱 SMTP 向站点用户发送品牌 HTML 邮件。**同步发送会被 30s 超时杀死**，故采用「创建任务 → 后台线程逐发（间隔 1s）→ 轮询进度」模式。

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/admin/email/templates` | GET | 内置模板列表（5 套，见下） |
| `/api/admin/email/send` | POST | 创建发送任务，立即返回 `task_id` |
| `/api/admin/email/task/{tid}` | GET | 轮询任务进度 |
| `/api/admin/email/logs` | GET | 发送历史（最近 50 条） |

**发送接口 body**：

```json
{
  "to_mode": "all",                 // all=全体用户；users=按 usernames 指定
  "usernames": ["zhangsan"],        // to_mode=users 时生效
  "subject": "【马上签】系统维护公告：建议重新登录",
  "content": "尊敬的用户，您好：\n\n正文纯文本，\\n 分段……"
}
```

- 收件人自动去重，跳过**已禁用**与**未绑定邮箱**的用户；无符合条件收件人返回 `400`。
- 任务对象：`{ "id", "status": "running|done", "total", "done", "ok", "fail", "detail": [...], "subject", "created_at" }`，`status=done` 即结束。
- 完成后写入发送历史（`sender`/`to_mode`/`to_count`/`subject`/`ok_count`/`fail_count`/`detail`/`created_at`），并给收件人生成一条**系统消息**。
- 正文为纯文本，服务端自动包装为马上签品牌 HTML（渐变红头条 + 段落 + 页脚），无需前端拼 HTML。

**内置模板**（`id` / 名称）：

| id | 名称 | 典型主题 |
|---|---|---|
| `maintenance` | 系统维护公告 | 【马上签】系统维护公告：建议重新登录 |
| `feature` | 新功能上线 | 【马上签】新功能上线通知 |
| `abnormal` | 账号异常提醒 | 【马上签】账号异常提醒 |
| `inactive` | 监控未开启提醒 | 【马上签】监控未开启提醒 |
| `custom` | 自定义 | （空，自行填写） |

---

### 3.12 后台管理 API（管理端可选）

仅 `role=admin` 的站点账号可调用，普通用户调用返回 `403`。APP 若要做管理端，可按需选用：

| 模块 | 接口 |
|---|---|
| 概览 | `GET /api/admin/stats` |
| 用户管理 | `GET/POST /api/admin/users`；`PUT/DELETE /api/admin/users/{username}`；`POST .../disable` |
| 账号管理 | `GET /api/admin/accounts`；`POST .../{acct_id}/monitor`；`POST .../{acct_id}/check`；`POST .../{acct_id}/logout`；`DELETE .../{acct_id}` |
| 记录 | `GET /api/admin/records?owner=&result=&limit=` |
| 日志 | `GET /api/admin/logs?after=` |
| 工单 | `GET /api/admin/tickets`；`POST .../{tid}/reply`；`POST .../{tid}/status`；`DELETE .../{tid}` |
| 设置 | `GET/PUT /api/admin/settings`（注册开关 / 邮件通知开关 / 站点名称） |
| APP 版本 | `GET/POST /api/admin/app-releases`；`PUT/DELETE .../{rid}` |
| 公告 | `GET/POST /api/admin/announcements`；`PUT/DELETE .../{aid}` |
| 邮件群发 | `GET /api/admin/email/templates`；`POST /api/admin/email/send`；`GET .../task/{tid}`；`GET /api/admin/email/logs` |

### 3.13 APP 闪屏配置（v2.4.0 新增）

后台管理页「APP 闪屏」配置站点级闪屏：图片链接、展示秒数、点击跳转链接、启用开关。

```
GET /api/app/splash        → 公开，APP 启动时调用
→ { "ok": true, "enabled": false, "image_url": "", "duration": 3, "jump_url": "" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 是否展示闪屏；后台关闭或未配图片链接时为 `false`（APP 直接进首页） |
| `image_url` | string | 闪屏图片链接（建议 1080×1920 竖图、JPG/PNG、<500KB） |
| `duration` | int | 展示秒数，1~10，到时 APP 自动进入首页 |
| `jump_url` | string | 点击闪屏的跳转链接（活动页 / 公告页等），为空 = 点击不跳转 |

管理接口（仅 `role=admin`，普通用户 `403`）：

```
GET /api/admin/splash   → { "ok": true, "splash": { "enabled", "image_url", "duration", "jump_url", "updated_at" } }
PUT /api/admin/splash   body: { "enabled": true, "image_url": "https://...", "duration": 3, "jump_url": "https://..." }
```

- `duration` 越界会自动钳制到 1~10；`updated_at` 由服务端维护，提交时忽略。
- APP 侧建议：启动时与 `/api/app/version` 一并调用；闪屏页倒计时 `duration` 秒后自动进首页；`jump_url` 非空时整图可点，跳转用系统浏览器或应用内 WebView。

---

## 四、核心数据结构

### Account（账号摘要，`/api/accounts`、`/status` 返回）

| 字段 | 类型 | 说明 |
|---|---|---|
| `acct_id` | string | 学习通账号唯一 ID（路径参数） |
| `owner` | string | 所属站点用户名 |
| `name` | string | 学习通昵称 |
| `logged_in` | bool | 是否已绑定学习通登录态 |
| `monitoring` | bool | 监控开关是否打开 |
| `monitor_alive` | bool | 监控线程是否存活（false 且 monitoring=true 即「线程异常」） |
| `courses` | int | 课程总数 |
| `records` | int | 签到记录条数 |
| `manual_today` | int | 今日需手动完成的数量 |
| `interval` | int | **当前生效的监控间隔（秒）**：服务端自适应计算 `max(60, 课程数×2)`，用户配置只能调长不能调短（防学习通限频，v2.2） |
| `freq_cooldown` | int | 限频自动冷却剩余秒数（v2.2）：>0 表示账号被学习通大面积限频，服务端已停机静默，到点自动恢复监控，APP 可展示「冷却中」 |
| `need_relogin` | bool | **true = 登录态已失效，需退出重新扫码**（卡片应醒目提示） |
| `last_check` | number | 最近一次检测的 Unix 时间戳（秒） |

### Record（签到记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| `time` | string | `MM-DD HH:mm:ss` |
| `course` | string | 课程名（含班级） |
| `activity` | string | 签到活动名 |
| `type` | string | 普通/拍照、二维码、手势、位置、签到码 |
| `result` | string | `success` / `fail` / `manual` |
| `detail` | string | 结果明细（如「签到成功」「返回: ...」） |

### SiteUser（站点用户）

`{ "username", "role": "admin|user", "created_at", "disabled", "email" }`

### Message（站内消息，v2.1 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 消息 ID（全局递增） |
| `type` | string | `announcement`（公告）/ `sign`（签到）/ `ticket`（工单）/ `system`（系统） |
| `title` | string | 标题 |
| `content` | string | 正文（`\n` 分段） |
| `ref_id` | string | 关联业务 ID（公告 ID / 工单 ID） |
| `read` | bool | 是否已读 |
| `created_at` | string | `YYYY-MM-DD HH:mm:ss` |

### EmailTemplate / EmailLog / EmailTask（邮件群发，v2.1 新增）

- `EmailTemplate`：`{ "id": "maintenance|feature|abnormal|inactive|custom", "name", "subject", "content" }`
- `EmailLog`：`{ "id", "sender", "to_mode": "all|users", "to_count", "subject", "ok_count", "fail_count", "detail", "created_at" }`
- `EmailTask`：`{ "id", "status": "running|done", "total", "done", "ok", "fail", "detail": [失败明细], "subject", "created_at" }`

---

## 五、关键业务流程

### 5.1 首次使用

```
启动 APP
  ├─ GET /api/app/version           检查更新（有新版先引导更新）
  ├─ GET /api/announcements         拉公告，弹窗展示（已读过的本地记住不再弹）
  ├─ GET /api/auth/me
  │    ├─ logged_in=false → 登录/注册页
  │    │     注册：POST /api/auth/register（username/password/QQ邮箱）
  │    │     登录：POST /api/auth/login
  └─ logged_in=true  → 首页
         ├─ GET /api/messages/unread-count   底部「消息中心」Tab 红点
         └─ GET /api/accounts → 空则引导「添加学习通账号」
```

### 5.2 添加学习通账号（扫码登录）

```
用户点「+ 添加账号」
  → POST /api/qr/start          渲染二维码（base64）
  → 每 2s GET /api/qr/poll?qr_id=
        waiting   → 等待
        scanned   → 提示「请在手机学习通上确认」
        confirmed → 成功，GET /api/accounts 刷新列表
        expired/canceled/failed → 重新 POST /api/qr/start
```

### 5.3 挂机监控

```
账号卡片「监控」开关 → POST /api/accounts/{id}/monitor {on:true}
首页轮询 GET /api/accounts/{id}/status（10~30s）
  monitoring && monitor_alive  → 「监控中」（实际轮询间隔以 summary.interval 为准，v2.2 起自适应）
  monitoring && !monitor_alive → 「线程异常」提示重启监控
  need_relogin                 → 红条「登录态已失效，请重新扫码」
老师发签到 → 服务端自动处理 → 记录写入 records + 邮件/Server 酱推送
```

v2.2 防限频机制（服务端自动，APP 只需正确展示状态）：

| 场景 | 服务端行为 | APP 展示建议 |
|---|---|---|
| 课程多 | 监控间隔自动拉长（`max(60, 课程数×2)` 秒 + ±20% 抖动） | 用 summary `interval` 字段显示「每 N 秒检测」 |
| 轻度受限（个别课程返回「请勿频繁操作」） | 自动加倍退避，不停机 | 无需特殊处理 |
| 大面积受限（≥50% 课程受限，连续 2 轮） | 自动停机冷却 15 分钟（`freq_cooldown` 倒计时） | 监控开关显示关 + 「限频冷却中，稍后自动恢复」 |
| 冷却到期 | 看门狗自动恢复监控（仅自动冷却的账号；手动停止不恢复） | 下次轮询即见 monitoring=true |
| 用户手动开启监控 | 立即解除冷却并启动 | 正常「监控中」 |

### 5.4 手动检测（不等轮询）

```
用户点「立即检查」→ POST /api/accounts/{id}/check（同步，超时设 120s）
  login_ok=false → 弹窗「登录态已失效」→ 引导退出重新扫码
  found 为空    → toast「已扫描 N 门课程，暂无新签到」
  found 非空    → 列表展示每个签到的处理结果（成功/失败/需手动）
```

### 5.5 位置模拟签到

```
账号详情 → 「位置模拟」
  GET  /location                回显开关与坐标
  地图选点（或拖动标记）→ 得到 lat/lng
  打开开关保存 → PUT /location {enabled:true, lat, lng, address}
之后出现位置签到，服务端自动用该坐标提交，结果进签到记录
```

### 5.6 协助签到（同学帮签，v2.3 新增）

> 适用场景：二维码签到（需扫老师投屏的码）、手势签到、签到码签到——这三类服务端无法本地自动完成，可让在教室的同学代签。

**原理**：服务端检测到这三类签到后，不再归为「需手动」，而是进入该账号的「待协助」队列，并向你推送一条带**协助链接**的通知（`https://xxt.leich.cn/assist/<token>`）。你把链接发给教室里的同学，同学打开后：

- **二维码**：点卡片里的「📷 扫码签到」按钮，页面直接调用手机摄像头（1080p 采集 + 连续对焦 + 自动优选后置摄像头），对着老师投屏的二维码扫一下即可（jsQR 实时识别、自动提取 enc 提交，不用手敲那串长链接）。识别采用「全画幅 → 中心 60% → 中心 35%」三档视野逐帧轮换，距离远也能扫到；码太小可点「🔍 放大」（数字变焦，所有手机可用），教室暗可点「🔦 开灯」（需硬件支持，不支持时按钮不显示）。老师屏幕的码刷新很快，所以**扫码后页面会立即校验并提示**：✅ 有效 → 直接提交；❌ 已失效 → 提示「请扫最新的码」并自动重新打开摄像头（同一码 3 秒内不重复提交，不会对着旧码死循环）；❌ 不是签到码 → 提示对准老师屏幕，继续扫。**注意**：如果同学是从微信 / QQ 等 App 里直接打开链接的，这些内置浏览器禁用摄像头，页面会自动弹出「请使用浏览器打开」引导（右上角 ··· → 在浏览器中打开，或复制链接到浏览器）；摄像头不可用或识别失败时，也可手动粘贴链接 / enc 提交兜底。
- **手势**：页面直接渲染九宫格——同学抬头看一眼老师屏幕上的手势，照着在九宫格里按顺序点出来（如「Z」= `1235789`）提交即可，**不需要摄像头**。
- **签到码**：直接输入老师公布的 4 位签到码提交。

提交成功后你会收到「同学已协助签到成功」推送，记录入库。链接按账号生成、可随时重置（旧链接立即失效），页面不暴露任何账号 / 手机号信息。

```
账号详情 → 「协助链接」按钮（或访问 /my-assist）
  GET  /api/accounts/{acct_id}/assist-token     获取当前链接
  POST /api/accounts/{acct_id}/assist-token     生成/重置（reset:true 使旧链失效）
把返回的 link 发给同学
  同学打开 /assist/<token> → 待协助列表（二维码/手势/签到码）
  POST /api/assist/<token>/qr       {active_id, value(enc 或含 enc 的链接)}
  POST /api/assist/<token>/gesture  {active_id, value(手势数字串/签到码)}
服务端用该账号会话提交 → 推送「协助成功」→ 记录进签到记录
```

**前端建议**：账号详情页增加「协助链接」入口，点击复制 `link`；待协助数可展示在账号卡片角标（`summary.assist_pending`）。

---

## 六、UI 设计

> 网页端（`https://xxt.leich.cn/app`）是功能与接口蓝本，UI 布局不照搬网页：APP 按原生移动端规范设计，参考微信 / 抖音等大厂实践（底部 Tab + 顶部导航栏 + 卡片流 + 分组列表 + 底部弹窗），整体白底、主色 `#1677ff`。

### 6.1 设计规范

| 项 | 规范 |
|---|---|
| 主色 | `#1677ff`（白蓝主题），按下态 `#0958d9`，成功 `#52c41a`，警示 `#faad14`，错误 `#ff4d4f`，删除/退出用 `#ff4d4f` |
| 导航栏 | 白底，左返回箭头，中部标题 17sp，右侧图标操作；首页 Tab 用大标题式（微信风） |
| 底部 Tab | 白底 + 细分隔线；图标 + 10sp 文字，选中 `#1677ff`、未选 `#8c8c8c`；未读红点/数字 `#ff4d4f` |
| 卡片 | 白底、圆角 12px、页面左右边距 12px，卡片间用间距分隔（不用重阴影） |
| 分组列表 | 微信设置风：组标题 12sp 灰色，项高 52dp，右侧箭头 / 开关 / 值文本；开关主色 `#1677ff` |
| 按钮 | 主按钮实心蓝、圆角 8dp、高 44dp；次按钮描边或文字蓝；危险操作红色 |
| 弹窗 | 居中 Dialog（更新 / 二次确认）；底部 BottomSheet（操作菜单 / 检测结果） |
| 字体 | 系统默认；导航标题 17~18sp，正文 14~15sp，辅助 12~13sp |
| 反馈 | 轻结果用 Toast/Snackbar；破坏性操作用二次确认 Dialog |
| 列表交互 | 下拉刷新；记录 / 消息列表上拉加载更多 |
| 空状态 | 插图 + 「暂无数据」文案 + 主行动按钮（如「添加学习通账号」） |

### 6.2 信息架构

```
马上签 APP
├── 启动流程
│   ├── 冷启动 → 并行拉取 GET /api/app/version（更新检测，见 6.11）与 GET /api/app/splash（闪屏配置，见 3.13）
│   ├── GET /api/announcements 拉公告 → 顶部横幅 / 弹窗（本地记住已读）
│   └── 未登录 → 登录 / 注册页；已登录 → 首页
├── 主框架：底部 3 Tab（微信式，白底，选中 #1677ff）
│   ├── Tab1 首页
│   │   ├── 顶部：欢迎语 + 在线 / 监控状态总览
│   │   ├── 账号卡片列表（每张卡片见 6.3）
│   │   └── 右下角悬浮「＋」→ 添加学习通账号（扫码登录弹窗，见 6.4）
│   ├── Tab2 消息（未读红点，见 6.9）
│   └── Tab3 我的（个人中心，见 6.7）
│       ├── 个人资料 / 我的工单 / 协助链接管理
│       ├── 设置（见 6.10）/ 关于马上签（见 6.12）
│       └── 管理后台入口（仅 admin，见 6.8）
├── 二级页面（顶部导航栏 + 右滑转场）
│   ├── 账号详情：监控配置 Tab / 签到记录 Tab（记录仅本账号）
│   ├── 位置模拟页（见 6.5）/ 手动检测结果（见 6.6）
│   ├── 工单：列表 → 详情（对话气泡回复 + 底部输入框）
│   └── 设置页（见 6.10）/ 关于页（见 6.12）/ 版本更新弹窗（见 6.11）
└── 全局
    ├── 登录态失效：任意接口返回未登录 → 弹窗提醒 → 回登录页
    └── 网络异常：Snackbar「网络异常，请稍后重试」+ 重试入口
```

### 6.3 账号卡片（列表项）

```
┌────────────────────────────────────────┐
│ [头字母] 张三            [已登录/需重新登录] │
│ [监控中/未监控/线程异常] [今日需手动 N]      │
│ 课程 36    记录 12                       │
│────────────────────────────────────────│
│ [监控 ●—○]              查看记录  立即检查 │
└────────────────────────────────────────┘
```

- 右上角状态标签：`已登录`（绿）/ `需重新登录`（红）/ `未登录`（灰）。
- `need_relogin=true` 时卡片内嵌黄色警告条：「登录态已过期，请退出后重新扫码」。
- 「立即检查」点击后按钮转圈，完成后 toast 结果；若有新签到，卡片内展开结果列表（课程 · 活动名（类型） + 结果标签）。

### 6.4 扫码登录弹窗

- 居中二维码（建议 ≥220dp，白底留静区）。
- 二维码下方状态文案：`等待扫码…` → `已扫描，请在手机上确认登录…` → `登录成功！`。
- 失效自动刷新（用户无感）；提供「取消」按钮。

### 6.5 位置模拟页

```
┌────────────────────────────────────────┐
│ 位置模拟签到                    [开关]    │
├────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ │
│ │            （地图，可拖动/点击选点）   │ │
│ │                  ● 蓝色标记          │ │
│ └────────────────────────────────────┘ │
│ 纬度  [ 39.909200    ]                 │
│ 经度  [ 116.407400   ]   [用当前定位填充] │
│ 地址备注 [ 综合楼301            ]        │
│                        [ 保存 ]         │
└────────────────────────────────────────┘
```

- 地图用高德 SDK（或 Mapbox + 高德瓦片），初始视图：有坐标则定位到坐标（zoom 16），否则全国（zoom 10）。
- 标记可拖动；点击地图任意处移动标记；标记、输入框、外部赋值三向同步。
- 「用当前定位填充」走系统定位权限，拿到 WGS-84 坐标填入输入框。
- 保存前校验：开关打开时经纬度必须合法（纬度 -90~90，经度 -180~180）。
- 页内附提示文案：「高德/百度选点为 GCJ-02，手机定位为 WGS-84；提示距离不符时请换另一种坐标系重试。」

### 6.6 手动检测结果展示

```json
found: [
  { "course": "高等数学(计科1班)", "activity": "第三讲 签到",
    "type": "普通/拍照", "result": "success", "detail": "签到成功" }
]
```

建议以底部弹窗（BottomSheet）或卡片内嵌列表展示：

```
本次检测到 1 个新签到：
• [高等数学(计科1班)] 第三讲 签到（普通/拍照） [签到成功]
• [大学英语] 随堂测验（位置）              [签到失败] 返回: 超出签到范围
```

`result` 配色：`success` 绿、`fail` 红、`manual` 橙。

### 6.7 我的（个人中心）

微信「我」式布局：头像头部卡 + 数据统计行 + 分组列表，收在底部 Tab3。

```
┌────────────────────────────────────────┐
│ 我的                                    │  ← 顶部大标题（微信风）
├────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ │
│ │ [头像]  张三                       › │ │  ← 点击进「个人资料」
│ │        @zhangsan · 普通用户         │ │
│ ├────────────────────────────────────┤ │
│ │  账号 3   │  监控中 2   │  今日成功 5 │ │  ← 统计行，可点击跳对应列表
│ └────────────────────────────────────┘ │
├────────────────────────────────────────┤
│ 我的服务                                │
│  我的工单                             › │
│  协助链接管理                         › │
│  管理后台（仅管理员可见）              › │
├────────────────────────────────────────┤
│  设置                                 › │
│  关于马上签                    有新版本 › │
├────────────────────────────────────────┤
│              退出登录                    │
└────────────────────────────────────────┘
```

- 头部卡片：头像（默认字母头像）、昵称、`@用户名` + 角色标签（admin 显示「管理员」徽标）；整卡点击 → 个人资料页（`PUT /api/auth/profile` 改邮箱 / 密码）。
- 统计行数据由 `GET /api/accounts` 汇总；「今日成功」点击 → 跳全部账号的近期成功记录（逐账号拉取后合并展示）。
- 「我的工单」：列表（状态标签 + 标题 + 时间）→ 详情（对话气泡式回复记录 + 底部输入框）。
- 「协助链接管理」：展示 / 重置各账号的协助链接（`/my-assist` 的 APP 化）。
- 「管理后台」仅 admin 角色可见（见 6.8）。
- 「关于马上签」行右侧显示「有新版本」红字（启动检测到 `has_update` 时），点击进入关于页（见 6.12）。
- 「退出登录」红色文字居中，点击弹二次确认 Dialog，确认后 `POST /api/auth/logout` 并回登录页。

### 6.8 管理端（可选，仅 admin 角色可见入口）

用户管理（列表/创建/禁用/编辑/删除）、全部账号一览（含强制监控/强制下线/手动检测）、全局记录（按用户/结果筛选）、工单处理（回复/改状态/优先级）、系统设置、APP 版本发布、公告管理、**邮件群发**（选模板 → 编辑主题正文 → 选收件人 → 预览 → 发送，进度轮询 + 发送历史）。移动端用列表 + 底部操作表单（BottomSheet）承载，不内嵌网页。

### 6.9 消息中心（v2.1 新增）

```
┌────────────────────────────────────────┐
│ 消息中心                    [全部已读]   │
├────────────────────────────────────────┤
│ [全部|未读|公告|签到|工单|系统]   ← 筛选  │
├────────────────────────────────────────┤
│ 🔴 签到成功：第三讲 签到        10-19   │
│    高等数学(计科1班) · 普通签到          │
│ 🟠 需手动签到：随堂测验          10-19   │
│    大学英语 · 位置签到                   │
│ 🔵 公告：新功能上线通知          10-18   │
│    消息中心与邮件群发已上线……            │
└────────────────────────────────────────┘
```

- 底部 Tab 图标带未读红点（数字），30s 轮询 `GET /api/messages/unread-count`。
- 顶部筛选 chips：全部 / 未读 / 公告 / 签到 / 工单 / 系统。
- 列表项：类型图标（签到成功=绿、需手动=橙、失败=红、公告=蓝、工单=紫、系统=灰）+ 标题 + 摘要 + 时间；未读加粗或左侧红点。
- 点击条目 → `POST /api/messages/{mid}/read` 标记已读并本地更新。
- 「全部已读」一键 `POST /api/messages/read-all`；「清空已读」二次确认后 `POST /api/messages/read/clear`。
- 下拉刷新重新拉列表；空状态插图 + 「暂无消息」。

### 6.10 设置页

入口：「我的 → 设置」。微信设置式分组列表（白底、组标题灰色、右侧箭头 / 开关 / 值）。

```
┌────────────────────────────────────────┐
│ ← 设置                                  │
├────────────────────────────────────────┤
│ 账号与安全                               │
│  修改资料（邮箱）                     › │
│  修改密码                            › │
├────────────────────────────────────────┤
│ 消息通知                                 │
│  签到结果通知                      [开关] │
│  公告弹窗                          [开关] │
├────────────────────────────────────────┤
│ 通用                                     │
│  清理缓存            12.6MB          › │
│  当前版本 2.3.2            有新版本  › │
├────────────────────────────────────────┤
│ 关于                                     │
│  关于马上签                        › │
│  用户协议 / 隐私政策                › │
│  官方网站                         › │
└────────────────────────────────────────┘
```

- 修改资料 / 密码：跳子页或底部弹窗表单，调 `PUT /api/auth/profile`。
- 通知类开关为**本地偏好**（SharedPreferences / DataStore），只控制本机行为，不同步服务端。
- 清理缓存：显示缓存大小，二次确认后清空并 toast「已清理」。
- 「当前版本」行：启动检测到新版本时右侧显示红色「有新版本」，点击直接弹更新窗（见 6.11）。
- 「用户协议 / 隐私政策」用 WebView 加载 H5；「官方网站」跳系统浏览器打开 `https://xxt.leich.cn`。

### 6.11 版本更新

接口：`GET /api/app/version`（见 3.8）。双入口：① 冷启动静默检测；② 设置页「当前版本」/ 关于页「检查更新」手动触发。

**更新弹窗**（居中 Dialog，`has_update=true` 即弹；`force_update=true` 或 `below_min_supported=true` 时遮罩不可关闭、隐藏「稍后提醒」）：

```
┌────────────────────────────────┐
│          发现新版本 2.3.2         │
│  ────────────────────────────── │
│  更新内容：                       │
│  1. 扫码后即时校验二维码有效性      │
│  2. 失效自动提示重扫               │
│  …（update_log 原样展示，支持换行） │
│  安装包大小 12.4MB                │
│  ────────────────────────────── │
│   [ 官网下载 ]   [ 直接下载 ]      │
│            稍后提醒                │
└────────────────────────────────┘
```

- **官网下载**：跳系统浏览器打开 `download_url`（或固定 `http://xxt.leich.cn/msq.apk`），交给用户手动下载安装。
- **直接下载**：APP 内下载，点「直接下载」后弹窗内按钮区变为**实时进度条**：

```
┌────────────────────────────────┐
│          正在下载 2.3.2 …        │
│  ████████████░░░░░░░░  68%      │
│  8.4MB / 12.4MB · 1.2MB/s       │
│            [ 取消 ]              │
└────────────────────────────────┘
```

  - 进度条、已下载 / 总大小、网速实时刷新；可随时取消。
  - 下载完成：通知栏提示「下载完成，点击安装」，点击跳系统安装器（Android 8+ 需提前请求「安装未知应用」权限；APK 放 `getExternalFilesDir` 私有目录，无需存储权限）。
- 「稍后提醒」：记录时间，24 小时内不再自动弹；强制更新时隐藏。
- 手动检查无更新：toast「已是最新版本」。

### 6.12 APP 介绍（关于页）

入口：「我的 → 关于马上签」。微信「关于」页风格：Logo + 名称 + 版本 + 功能简介 + 入口列表。

```
┌────────────────────────────────────────┐
│ ← 关于马上签                            │
├────────────────────────────────────────┤
│              ┌──────┐                  │
│              │ logo │                  │
│              └──────┘                  │
│              马上签                     │
│         版本 2.3.2（build 32）          │
│      学习通自动签到 · 同学互助代签        │
├────────────────────────────────────────┤
│  功能介绍                             › │
│  检查更新              已是最新版本    › │
│  用户协议                           › │
│  隐私政策                           › │
│  官方网站                         › │
│  意见反馈（工单）                   › │
├────────────────────────────────────────┤
│    学习通自动签到服务 · 非官方衍生         │
│    © 2026 马上签团队                    │
└────────────────────────────────────────┘
```

- 「功能介绍」二级页：图文列表介绍四大能力——① 挂机自动签到（普通签到自动完成，异常类型提醒手动）② 协助签到（同学帮签：扫码 / 九宫格手势 / 签到码）③ 位置模拟签到 ④ 消息中心与推送（Server 酱 / 站内消息）。
- 「检查更新」：行右侧显示状态（「检查中…」→「已是最新版本」/「发现新版本」），点击走 6.11 同一套弹窗逻辑。
- 「用户协议 / 隐私政策」WebView 加载 H5；「官方网站」跳浏览器；「意见反馈」跳工单新建页（`POST /api/tickets`）。
- 底部固定版权与「非官方衍生」声明（合规要求，见第八章）。

---

## 七、技术选型建议

| 方案 | 适用 | 要点 |
|---|---|---|
| **Flutter**（推荐） | 新项目、双端预留 | 一套代码；地图用 `flutter_map`（高德瓦片）或高德插件；HTTP 用 `dio` + `CookieManager` 自动带会话 |
| React Native | 前端团队转型 | Expo + `react-native-maps`；与网页端同生态 |
| 原生 Android | 只要安卓、追求体验 | Kotlin + Retrofit/OkHttp（`CookieJar` 持久化会话）+ 高德 SDK |

通用工程建议：

1. **会话保持**：HTTP 客户端启用 Cookie 持久化（OkHttp `PersistentCookieJar` / dio `CookieManager`），否则每次冷启动都掉登录。
2. **超时**：普通接口 15s；`/check` 与 `/courses/refresh` 设 120s。
3. **轮询节制**：`/status` 10~30s；二维码轮询 2s；APP 退后台时暂停轮询，回前台恢复。
4. **版本更新**：启动时 `/api/app/version`；`force_update` 用不可关闭的 Dialog；弹窗内提供「官网下载」与「直接下载」两种方式，应用内下载用系统 DownloadManager 或 OkHttp 直下并展示实时进度条，完成后跳系统安装器（见 6.11）。
5. **本地缓存**：账号列表、记录做本地缓存，下拉刷新；`need_relogin` 置位时立即从服务端状态反映，不做本地猜测。

---

## 八、安全与合规

1. **不要在前端/APP 内保存学习通账号密码**——本站只有扫码登录，服务端保管 Cookie。
2. **HTTPS**：当前服务端为 HTTP，正式发布建议上 HTTPS 后再投放。
3. **频率自律**：监控间隔 ≥30 秒；不要并行多次调 `/check`（服务端有并发保护，会返回「已有一次检查正在进行中」）。
4. **合规**：本工具仅供个人学习交流，只签自己的课；自动化操作可能违反平台服务条款，账号风险自负。
5. **隐私**：QQ 邮箱仅用于签到通知；APP 不要采集与本功能无关的信息。

---

## 附：接口速查表

| 功能 | 方法 | 路径 | 登录 |
|---|---|---|---|
| 健康检查 | GET | `/api/ping` | 否 |
| 版本检测 | GET | `/api/app/version` | 否 |
| 闪屏配置 | GET | `/api/app/splash` | 否 |
| 公告 | GET | `/api/announcements` | 否 |
| APK 下载 | GET | `/msq.apk` | 否 |
| 注册 | POST | `/api/auth/register` | 否 |
| 登录 | POST | `/api/auth/login` | 否 |
| 退出登录 | POST | `/api/auth/logout` | 是 |
| 当前用户 | GET | `/api/auth/me` | 否 |
| 更新资料 | PUT | `/api/auth/profile` | 是 |
| 账号列表 | GET | `/api/accounts` | 是 |
| 账号详情 | GET | `/api/accounts/{acct_id}` | 是 |
| 移除账号 | DELETE | `/api/accounts/{acct_id}` | 是 |
| 生成二维码 | POST | `/api/qr/start` | 是 |
| 轮询扫码 | GET | `/api/qr/poll?qr_id=` | 是 |
| 监控开关 | POST | `/api/accounts/{acct_id}/monitor` | 是 |
| 更新配置 | POST | `/api/accounts/{acct_id}/config` | 是 |
| 课程列表 | GET | `/api/accounts/{acct_id}/courses` | 是 |
| 刷新课程 | POST | `/api/accounts/{acct_id}/courses/refresh` | 是 |
| **手动检测** | POST | `/api/accounts/{acct_id}/check` | 是 |
| 签到记录 | GET | `/api/accounts/{acct_id}/records` | 是 |
| 监控状态 | GET | `/api/accounts/{acct_id}/status` | 是 |
| 退出学习通 | POST | `/api/accounts/{acct_id}/logout` | 是 |
| 测试推送 | POST | `/api/accounts/{acct_id}/notify/test` | 是 |
| 位置配置读 | GET | `/api/accounts/{acct_id}/location` | 是 |
| 位置配置写 | PUT/POST | `/api/accounts/{acct_id}/location` | 是 |
| 提交工单 | POST | `/api/tickets` | 是 |
| 我的工单 | GET | `/api/tickets` | 是 |
| 工单详情 | GET | `/api/tickets/{tid}` | 是 |
| 回复工单 | POST | `/api/tickets/{tid}/reply` | 是 |
| **消息列表** | GET | `/api/messages?unread=&type=&limit=` | 是 |
| **未读消息数** | GET | `/api/messages/unread-count` | 是 |
| **全部已读** | POST | `/api/messages/read-all` | 是 |
| **清空已读** | POST | `/api/messages/read/clear` | 是 |
| **单条已读** | POST | `/api/messages/{mid}/read` | 是 |
| 邮件模板 | GET | `/api/admin/email/templates` | 管理员 |
| 闪屏配置 | GET/PUT | `/api/admin/splash` | 管理员 |
| 邮件群发 | POST | `/api/admin/email/send` | 管理员 |
| **协助链接页** | GET | `/my-assist` | 是 |
| 获取协助链接 | GET | `/api/accounts/{acct_id}/assist-token` | 是 |
| 重置协助链接 | POST | `/api/accounts/{acct_id}/assist-token` | 是 |
| **同学帮签页** | GET | `/assist/<token>` | 否（公开） |
| 待协助列表 | GET | `/api/assist/<token>/pending` | 否（公开） |
| 提交二维码 | POST | `/api/assist/<token>/qr` | 否（公开） |
| 提交手势/签到码 | POST | `/api/assist/<token>/gesture` | 否（公开） |
| 群发进度 | GET | `/api/admin/email/task/{tid}` | 管理员 |
| 发送历史 | GET | `/api/admin/email/logs` | 管理员 |
