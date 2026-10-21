# -*- coding: utf-8 -*-
"""生成 openapi.json（OpenAPI 3.0），覆盖全部接口，可直接导入 Apifox。"""
import json
import os

SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "学习通自动签到 · API",
        "version": "2.0.0",
        "description": (
            "学习通自动签到服务的开放接口。\n\n"
            "鉴权方式：基于 Cookie 的会话（Flask session）。\n"
            "先用 POST /api/auth/login 或 /api/auth/register 登录，拿到会话 Cookie 后，"
            "后续请求带上该 Cookie 即可；需要管理员权限的接口由服务端按账号 role 校验。\n\n"
            "后端模型：网站账号(SiteUser) → 拥有多个学习通账号(ChaoxingAccount) → 各自独立监控。\n"
            "仅自动完成【普通签到】，其余类型提醒用户手动完成。"
        ),
    },
    "servers": [
        {"url": "http://xxt.leich.cn", "description": "生产环境"},
        {"url": "http://127.0.0.1:9001", "description": "本地/服务器直连"},
    ],
    "components": {
        "securitySchemes": {
            "cookieAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": "登录后由服务端下发的会话 Cookie",
            }
        },
        "schemas": {
            "ApiError": {
                "type": "object",
                "properties": {"ok": {"type": "boolean", "example": False},
                               "msg": {"type": "string"}},
            },
            "SiteUser": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "role": {"type": "string", "enum": ["admin", "user"]},
                    "created_at": {"type": "string"},
                    "disabled": {"type": "boolean"},
                },
            },
            "Account": {
                "type": "object",
                "properties": {
                    "acct_id": {"type": "string"},
                    "owner": {"type": "string"},
                    "name": {"type": "string"},
                    "logged_in": {"type": "boolean"},
                    "monitoring": {"type": "boolean"},
                    "monitor_alive": {"type": "boolean"},
                    "courses": {"type": "integer"},
                    "records": {"type": "integer"},
                    "manual_today": {"type": "integer"},
                    "need_relogin": {"type": "boolean"},
                    "last_check": {"type": "number"},
                },
            },
            "Ticket": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "uid": {"type": "string"},
                    "subject": {"type": "string"},
                    "category": {"type": "string", "enum": ["bug", "feature", "question", "other"]},
                    "status": {"type": "string", "enum": ["open", "in_progress", "resolved", "closed"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "created_at": {"type": "string"},
                    "updated_at": {"type": "string"},
                    "reply_count": {"type": "integer"},
                },
            },
            "Announcement": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": ["info", "success", "warning", "error"]},
                    "enabled": {"type": "boolean"},
                    "created_at": {"type": "string"},
                    "updated_at": {"type": "string"},
                },
            },
        },
    },
    "security": [{"cookieAuth": []}],
    "paths": {},
}

P = SPEC["paths"]


def add(method, path, summary, tag, params=None, body=None, responses=None, need_auth=True):
    item = {
        "summary": summary,
        "tags": [tag],
        "responses": responses or {
            200: {"description": "成功"},
            400: {"description": "参数/业务错误", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}}},
        },
    }
    if not need_auth:
        item["security"] = []
    if params:
        item["parameters"] = params
    if body:
        item["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": body}},
        }
    P.setdefault(path, {})[method] = item


OK = {"200": {"description": "成功", "content": {"application/json": {"schema": {"type": "object"}}}}}

# ---------------- 鉴权 ----------------
add("post", "/api/auth/register", "注册并登录（需绑定QQ邮箱）", "鉴权",
    body={"type": "object", "required": ["username", "password", "email"],
          "properties": {"username": {"type": "string"}, "password": {"type": "string"},
                         "email": {"type": "string", "description": "QQ邮箱，用于接收签到通知"}}},
    need_auth=False)
add("post", "/api/auth/login", "登录", "鉴权",
    body={"type": "object", "required": ["username", "password"],
          "properties": {"username": {"type": "string"}, "password": {"type": "string"}}},
    need_auth=False)
add("post", "/api/auth/logout", "退出登录", "鉴权")
add("get", "/api/auth/me", "获取当前登录用户信息", "鉴权")
add("put", "/api/auth/profile", "更新个人资料（QQ邮箱/密码）", "鉴权",
    body={"type": "object",
          "properties": {"email": {"type": "string", "description": "新的QQ邮箱"},
                         "password": {"type": "string", "description": "新密码，留空则不修改"}}})

# ---------------- 我的账号 ----------------
add("get", "/api/accounts", "列出我的学习通账号", "我的账号")
add("post", "/api/qr/start", "生成扫码登录二维码", "我的账号")
add("get", "/api/qr/poll", "轮询扫码结果", "我的账号",
    params=[{"name": "qr_id", "in": "query", "required": True, "schema": {"type": "string"}}])
add("get", "/api/accounts/{acct_id}", "账号详情(配置+课程)", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("post", "/api/accounts/{acct_id}/monitor", "开启/停止监控", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    body={"type": "object", "properties": {"on": {"type": "boolean"}}})
add("post", "/api/accounts/{acct_id}/config", "更新账号配置", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    body={"type": "object", "properties": {
        "interval": {"type": "integer"}, "serverchan_key": {"type": "string"},
        "enabled_courses": {"type": "array", "items": {"type": "string"}},
        "monitor_on": {"type": "boolean"}}})
add("get", "/api/accounts/{acct_id}/courses", "课程列表", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("post", "/api/accounts/{acct_id}/courses/refresh", "刷新课程列表", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("get", "/api/accounts/{acct_id}/records", "签到记录", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("get", "/api/accounts/{acct_id}/status", "账号监控状态(轮询用)", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("post", "/api/accounts/{acct_id}/logout", "退出该学习通账号", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("post", "/api/accounts/{acct_id}/notify/test", "测试 Server 酱推送", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("delete", "/api/accounts/{acct_id}", "移除账号", "我的账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])

# ---------------- 工单(用户) ----------------
add("post", "/api/tickets", "提交工单", "工单",
    body={"type": "object", "required": ["subject", "content"],
          "properties": {"subject": {"type": "string"}, "content": {"type": "string"},
                         "category": {"type": "string", "enum": ["bug", "feature", "question", "other"]}}})
add("get", "/api/tickets", "我的工单列表", "工单")
add("get", "/api/tickets/{tid}", "工单详情", "工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}])
add("post", "/api/tickets/{tid}/reply", "回复工单", "工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}],
    body={"type": "object", "required": ["message"], "properties": {"message": {"type": "string"}}})

# ---------------- 后台-用户 ----------------
add("get", "/api/admin/stats", "后台概览统计", "后台-用户")
add("get", "/api/admin/users", "用户列表", "后台-用户")
add("post", "/api/admin/users", "创建用户", "后台-用户",
    body={"type": "object", "required": ["username", "password"],
          "properties": {"username": {"type": "string"}, "password": {"type": "string"},
                         "role": {"type": "string", "enum": ["user", "admin"]}}})
add("post", "/api/admin/users/{username}/disable", "禁用/启用用户", "后台-用户",
    params=[{"name": "username", "in": "path", "required": True, "schema": {"type": "string"}}],
    body={"type": "object", "properties": {"disabled": {"type": "boolean"}}})
add("delete", "/api/admin/users/{username}", "删除用户", "后台-用户",
    params=[{"name": "username", "in": "path", "required": True, "schema": {"type": "string"}}])

# ---------------- 后台-账号 ----------------
add("get", "/api/admin/accounts", "全部学习通账号", "后台-账号")
add("post", "/api/admin/accounts/{acct_id}/monitor", "后台控制监控", "后台-账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    body={"type": "object", "properties": {"on": {"type": "boolean"}}})
add("delete", "/api/admin/accounts/{acct_id}", "后台删除账号", "后台-账号",
    params=[{"name": "acct_id", "in": "path", "required": True, "schema": {"type": "string"}}])
add("get", "/api/admin/logs", "系统日志(轮询 after)", "后台-账号",
    params=[{"name": "after", "in": "query", "schema": {"type": "integer"}}])

# ---------------- 后台-工单 ----------------
add("get", "/api/admin/tickets", "全部工单", "后台-工单",
    params=[{"name": "status", "in": "query", "schema": {"type": "string"}}])
add("get", "/api/admin/tickets/{tid}", "工单详情(后台)", "后台-工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}])
add("post", "/api/admin/tickets/{tid}/reply", "管理员回复", "后台-工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}],
    body={"type": "object", "required": ["message"],
          "properties": {"message": {"type": "string"}, "close_after": {"type": "boolean"}}})
add("post", "/api/admin/tickets/{tid}/status", "更新工单状态/优先级", "后台-工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}],
    body={"type": "object", "properties": {"status": {"type": "string"}, "priority": {"type": "string"}}})
add("delete", "/api/admin/tickets/{tid}", "删除工单", "后台-工单",
    params=[{"name": "tid", "in": "path", "required": True, "schema": {"type": "integer"}}])

# ---------------- 通用 ----------------
add("get", "/api/ping", "健康检查", "通用", need_auth=False)

# ---------------- 公告(公开) ----------------
add("get", "/api/announcements", "获取顶部展示的公告列表", "公告", need_auth=False,
    responses={"200": {"description": "成功", "content": {"application/json": {"schema": {"type": "object", "properties": {
        "ok": {"type": "boolean"}, "announcements": {"type": "array", "items": {"$ref": "#/components/schemas/Announcement"}}}}}}}})

# ---------------- 后台-公告 ----------------
add("get", "/api/admin/announcements", "公告列表(含未启用)", "后台-公告")
add("post", "/api/admin/announcements", "新建公告", "后台-公告",
    body={"type": "object", "required": ["title", "content"],
          "properties": {"title": {"type": "string"}, "content": {"type": "string"},
                         "type": {"type": "string", "enum": ["info", "success", "warning", "error"]},
                         "enabled": {"type": "boolean"}}})
add("put", "/api/admin/announcements/{aid}", "编辑公告", "后台-公告",
    params=[{"name": "aid", "in": "path", "required": True, "schema": {"type": "integer"}}],
    body={"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"},
                                           "type": {"type": "string", "enum": ["info", "success", "warning", "error"]},
                                           "enabled": {"type": "boolean"}}})
add("delete", "/api/admin/announcements/{aid}", "删除公告", "后台-公告",
    params=[{"name": "aid", "in": "path", "required": True, "schema": {"type": "integer"}}])

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(SPEC, f, ensure_ascii=False, indent=2)
print("written:", out, "paths:", len(P))
