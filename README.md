# 马上签 · 学习通智能签到助手

> 马上签是一款面向大学生的超星学习通自动签到工具，通过服务端托管登录态并自动完成各类课程签到，适用于需要同时跟进多门课程、希望签到全程自动化的用户，帮助大家不再因遗漏签到影响平时成绩。
>
> **核心功能：**
>
> **一、全类型自动签到**
> 系统对普通签到、手势签到、签到码签到实现自动完成；位置签到支持预设坐标提交；二维码与拍照类签到实时推送提醒，确保及时处理，绝不漏签。
>
> **二、安全扫码绑定**
> 采用学习通官方扫码授权方式绑定账号，无需提供账号密码；支持多账号同时托管，各账号独立监控、互不影响。
>
> **三、同学协助签到**
> 针对二维码、手势、签到码三类签到，支持生成协助链接交由同课堂同学代为完成；扫码模块经 1080p 高清采集与连续对焦优化，远距离识别投屏二维码依然清晰稳定。
>
> **四、消息通知与记录**
> 签到结果、系统公告、工单回复统一汇入消息中心，重要动态同步推送 QQ 邮件，全部签到记录随时可查。
>
> **五、稳定运行保障**
> 采用自适应监控间隔、多账号错峰启动与限频自动冷却机制，配合守护进程自愈能力，保障服务长期稳定运行。
>
> 马上签所有账号数据仅用于本人签到管理，传输全程加密，安全合规。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10+-green.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-lightgrey.svg)

## 功能特性

- **多账号托管**：学习通扫码授权绑定，各账号独立监控线程、独立课程配置，互不影响
- **全类型签到**：普通 / 手势 / 签到码自动完成；位置签到预设坐标；二维码 / 拍照实时推送提醒
- **同学协助签到**：一键生成协助链接，同学扫码即可代为完成二维码 / 手势 / 签到码签到；微信 / QQ 内打开自动引导跳转浏览器，1080p 采集 + 连续对焦 + 数字变焦 + 手电筒
- **消息中心**：签到结果、系统公告、工单回复统一管理，QQ 邮件同步推送
- **管理后台**：用户管理、账号概览、签到记录、公告与工单、闪屏配置、系统设置
- **登录态持久化**：Cookie 本地保存，重启免登录（约 30 天，失效自动提示重登）
- **自适应监控**：按课程动态调整轮询间隔，错峰启动，限频自动冷却

## 项目结构

```
chaoxing-autosign/
├── app.py                  # Flask 主应用（Web 页面 + REST API + 协助签到）
├── core.py                 # 核心业务逻辑（账号管理、监控线程、签到执行、邮件通知）
├── browser_login.py        # 手机验证码登录辅助（可选，依赖 playwright）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板（复制为 .env 填写，.env 不入库）
├── gunicorn_conf.py.example # gunicorn 生产配置模板（复制为 gunicorn_conf.py 填写）
├── openapi.json            # OpenAPI 3.0 接口文档（可导入 Apifox）
├── generate_openapi.py     # openapi.json 生成脚本
├── apifox_push.py          # 接口文档推送 Apifox 脚本
├── index.html              # 用户端 H5 页面
├── admin.html              # 管理后台单文件页面
├── landing.html            # 官网落地页
├── help.html               # 使用教程页
├── static/                 # 静态资源（图标、字体）
├── web/
│   ├── user/               # 用户端 H5 源码（React + Vite）
│   └── admin/              # 管理后台源码（React + Ant Design + Vite）
├── 马上签-APP开发文档.md   # 完整开发文档
├── 马上签-APP对接文档.md   # 原生 APP 对接文档
└── 自动刷课-功能计划书.md   # 自动刷课功能规划
```

## 快速开始

```bash
# 1. 安装依赖（基础运行只需 flask + requests + gunicorn）
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：管理员账号密码、QQ 邮箱 SMTP（用于邮件通知）

# 3. 启动
python app.py                # 开发模式，默认 http://127.0.0.1:8765

# 生产模式：复制 gunicorn 配置模板，填入真实值后启动
cp gunicorn_conf.py.example gunicorn_conf.py
gunicorn -c gunicorn_conf.py app:app
```

启动后：

| 页面 | 地址 | 说明 |
| --- | --- | --- |
| 用户端 H5 | `/` | 扫码绑定学习通账号、查看签到状态与消息 |
| 管理后台 | `/admin` | 用户 / 账号 / 记录 / 公告 / 工单管理 |
| 使用教程 | `/help` | 图文使用指引 |
| 接口文档 | `/openapi.json` | OpenAPI 3.0 规范 |

> 生产部署建议使用 gunicorn + Nginx，并以环境变量注入所有敏感配置（`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `SMTP_USER` / `SMTP_PASS`），**切勿将密钥写进代码或提交到仓库**。

## 配置说明

所有配置通过环境变量提供，详见 [.env.example](.env.example)：

| 变量 | 说明 | 必填 |
| --- | --- | --- |
| `ADMIN_USERNAME` | 后台管理员用户名 | 是 |
| `ADMIN_PASSWORD` | 后台管理员密码 | 是 |
| `SMTP_HOST` / `SMTP_PORT` | QQ 邮箱 SMTP 服务器与端口 | 邮件通知开启时 |
| `SMTP_USER` / `SMTP_PASS` | 发件邮箱与授权码 | 邮件通知开启时 |
| `TICKET_NOTIFY_EMAIL` | 工单提醒收件邮箱，收到新工单/用户回复时自动发信，默认 `535919101@qq.com` | 否 |
| `PORT` | 服务端口，默认 `8765` | 否 |

## 开发

```bash
# 用户端 H5
cd web/user && pnpm install && pnpm dev                    # 开发
pnpm build && cp dist/index.html ../../index.html          # 构建同步

# 管理后台
cd web/admin && pnpm install && pnpm dev
pnpm build && cp dist/index.html ../../admin.html
```

## 安全与合规

- 采用学习通**官方扫码授权**绑定账号，不存储、不传输账号密码
- 所有账号数据仅用于本人签到管理，Cookie 等敏感数据本地保存，不经过第三方
- 本项目仅供个人学习接口编程与技术研究使用，**只签自己的课**
- 自动化操作可能违反平台服务条款，账号风险自负；请合理设置检测间隔（≥30 秒），避免高频请求

## 开源致谢

本项目为独立开发的开源项目，接口调研阶段参考了社区开源实现（如 `autopass-chaoxing-video` 的协议分析），在此致谢。

## License

[MIT License](LICENSE) © 2026 beimu
