# -*- coding: utf-8 -*-
"""学习通自动签到 - Flask 服务（API 优先 + 站点账号 + 后台 + 工单）"""
import os
import time

from flask import Flask, request, jsonify, session, send_from_directory, abort, Response

import core
from core import MGR, TICKETS, ANNOUNCEMENTS, AnnouncementStore, SETTINGS, APP_RELEASES, SPLASH, get_secret_key, LOG, send_welcome_async, log
from core import MESSAGES, EMAIL_LOGS, EMAIL_TEMPLATES, email_page

ROOT = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.secret_key = get_secret_key()
app.json.ensure_ascii = False


def API_OK(**kw):
    return jsonify({"ok": True, **kw})


def API_ERR(msg, code=400):
    return jsonify({"ok": False, "msg": msg}), code


# ---------------- 鉴权辅助 ----------------

def current_user():
    uname = session.get("site_user")
    if not uname:
        return None
    return MGR.site_users.get(uname)


def require_login(fn):
    from functools import wraps
    @wraps(fn)
    def wrap(*a, **k):
        u = current_user()
        if not u or u.disabled:
            return API_ERR("请先登录", 401)
        return fn(*a, **k)
    return wrap


def require_admin(fn):
    from functools import wraps
    @wraps(fn)
    def wrap(*a, **k):
        u = current_user()
        if not u or u.disabled or u.role != "admin":
            return API_ERR("需要管理员权限", 403)
        return fn(*a, **k)
    return wrap


def _valid_latlng(lat, lng):
    try:
        la, ln = float(lat), float(lng)
        return -90 <= la <= 90 and -180 <= ln <= 180
    except (TypeError, ValueError):
        return False


def _loc_view(a):
    """位置模拟配置的对外视图（供网页端与 APP 读取）。"""
    return {
        "enabled": bool(a.config.get("loc_enabled")),
        "lat": a.config.get("loc_lat", "") or "",
        "lng": a.config.get("loc_lng", "") or "",
        "address": a.config.get("loc_addr", "") or "",
    }


def owner_account(acct_id):
    a = MGR.get_account(acct_id)
    if not a:
        abort(404)
    u = current_user()
    if u.role != "admin" and a.owner != u.username:
        abort(403)
    return a


# ---------------- 鉴权 API ----------------

@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json(silent=True) or {}
    if not SETTINGS.get("registration_open", True):
        return API_ERR("管理员已关闭新用户注册", 403)
    email = (data.get("email", "") or "").strip()
    if not email:
        return API_ERR("请填写 QQ 邮箱（用于接收签到通知）")
    ok, err = MGR.site_users.register(data.get("username", ""), data.get("password", ""), email=email)
    if not ok:
        return API_ERR(err)
    session["site_user"] = data["username"].strip()
    send_welcome_async(data["username"].strip())
    return API_OK(user=current_user().to_public())


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True) or {}
    u = MGR.site_users.authenticate(data.get("username", ""), data.get("password", ""))
    if not u:
        return API_ERR("用户名或密码错误", 401)
    if u.disabled:
        return API_ERR("该账号已被禁用", 403)
    session["site_user"] = u.username
    send_welcome_async(u.username)
    return API_OK(user=u.to_public())


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return API_OK()


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    u = current_user()
    if not u:
        return API_OK(logged_in=False)
    return API_OK(logged_in=True, user=u.to_public())


@app.route("/api/auth/profile", methods=["PUT"])
def auth_profile():
    u = current_user()
    if not u:
        return API_ERR("未登录", 401)
    data = request.get_json(silent=True) or {}
    email = data.get("email", None)
    new_pw = (data.get("password", "") or "").strip()
    if email is None and not new_pw:
        return API_ERR("没有需要更新的内容")
    ok, err = MGR.site_users.update_profile(u.username, email=email, new_password=new_pw or None)
    if not ok:
        return API_ERR(err)
    return API_OK(user=MGR.site_users.get(u.username).to_public())


# ---------------- 我的学习通账号 ----------------

@app.route("/api/accounts", methods=["GET"])
@require_login
def list_accounts():
    u = current_user()
    accts = MGR.accounts_by_owner(u.username)
    return API_OK(accounts=[a.summary() for a in accts])


@app.route("/api/qr/start", methods=["POST"])
@require_login
def qr_start():
    res, err = MGR.qr_start()
    if err:
        return API_ERR(err)
    return API_OK(**res)


@app.route("/api/qr/poll", methods=["GET"])
@require_login
def qr_poll():
    qid = request.args.get("qr_id", "")
    if not qid:
        return API_ERR("缺少 qr_id")
    u = current_user()
    res = MGR.qr_poll(qid, u.username)
    res.pop("client", None)
    return API_OK(**res)


@app.route("/api/accounts/<acct_id>", methods=["GET"])
@require_login
def account_detail(acct_id):
    a = owner_account(acct_id)
    return API_OK(account={**a.summary(), "config": a.config, "courses": a.courses()})


@app.route("/api/accounts/<acct_id>/monitor", methods=["POST"])
@require_login
def account_monitor(acct_id):
    a = owner_account(acct_id)
    data = request.get_json(silent=True) or {}
    if data.get("on"):
        a.start_monitor()
    else:
        a.stop_monitor()
    return API_OK(monitoring=a.monitoring)


@app.route("/api/accounts/<acct_id>/config", methods=["POST"])
@require_login
def account_config(acct_id):
    a = owner_account(acct_id)
    data = request.get_json(silent=True) or {}
    for key in ("interval", "serverchan_key", "enabled_courses", "monitor_on"):
        if key in data:
            a.config[key] = data[key]
    # 位置模拟签到配置（字段与 /api/accounts/<id>/location 一致）
    if "loc_enabled" in data:
        a.config["loc_enabled"] = bool(data["loc_enabled"])
    for key in ("loc_lat", "loc_lng", "loc_addr"):
        if key in data:
            a.config[key] = str(data.get(key) or "").strip()
    a.save_config()
    return API_OK(config=a.config)


@app.route("/api/accounts/<acct_id>/location", methods=["GET"])
@require_login
def account_location_get(acct_id):
    a = owner_account(acct_id)
    return API_OK(location=_loc_view(a))


@app.route("/api/accounts/<acct_id>/location", methods=["POST", "PUT"])
@require_login
def account_location_set(acct_id):
    a = owner_account(acct_id)
    data = request.get_json(silent=True) or {}
    # 先算出本次生效值并校验，合法后才写入，避免半途失败污染配置
    def _pick(*keys):
        for k in keys:
            if k in data:
                return str(data.get(k) or "").strip()
        return None
    new_lat = _pick("lat", "loc_lat")
    new_lng = _pick("lng", "loc_lng")
    new_enabled = bool(data["enabled"]) if "enabled" in data else bool(a.config.get("loc_enabled"))
    lat = new_lat if new_lat is not None else str(a.config.get("loc_lat", "") or "")
    lng = new_lng if new_lng is not None else str(a.config.get("loc_lng", "") or "")
    if new_enabled and not _valid_latlng(lat, lng):
        return API_ERR("位置模拟已启用，但经纬度为空或不合法（纬度 -90~90，经度 -180~180）")
    a.config["loc_enabled"] = new_enabled
    a.config["loc_lat"] = lat
    a.config["loc_lng"] = lng
    if "address" in data:
        a.config["loc_addr"] = str(data.get("address") or "").strip()
    a.save_config()
    return API_OK(location=_loc_view(a))


@app.route("/api/accounts/<acct_id>/courses", methods=["GET"])
@require_login
def account_courses(acct_id):
    a = owner_account(acct_id)
    return API_OK(courses=a.courses())


@app.route("/api/accounts/<acct_id>/courses/refresh", methods=["POST"])
@require_login
def account_courses_refresh(acct_id):
    a = owner_account(acct_id)
    try:
        courses = a.refresh_courses()
    except Exception as e:
        return API_ERR(f"刷新失败: {e}")
    return API_OK(courses=courses)


@app.route("/api/accounts/<acct_id>/check", methods=["POST"])
@require_login
def account_check(acct_id):
    """用户手动检测：先验证学习通登录态，再立即扫描一轮全部课程是否有签到。
    返回 login_ok / checked / found(新签到活动及处理结果) / msg。"""
    a = owner_account(acct_id)
    res = a.check_now()
    if not res.get("ok"):
        return API_ERR(res.get("msg") or "检查失败")
    return API_OK(login_ok=res.get("login_ok"), checked=res.get("checked"),
                  found=res.get("found") or [], msg=res.get("msg"))


@app.route("/api/accounts/<acct_id>/records", methods=["GET"])
@require_login
def account_records(acct_id):
    a = owner_account(acct_id)
    return API_OK(records=a.records)


@app.route("/api/accounts/<acct_id>/status", methods=["GET"])
@require_login
def account_status(acct_id):
    a = owner_account(acct_id)
    return API_OK(status=a.summary(), last_check=a.last_check,
                  rounds=a.monitor_rounds, errors=a.monitor_errors)


@app.route("/api/accounts/<acct_id>/logout", methods=["POST"])
@require_login
def account_logout(acct_id):
    a = owner_account(acct_id)
    a.logout()
    return API_OK()


@app.route("/api/accounts/<acct_id>/notify/test", methods=["POST"])
@require_login
def account_notify_test(acct_id):
    a = owner_account(acct_id)
    ok, msg = core.serverchan_send(a.config.get("serverchan_key", ""),
                                   "✅ 签到助手通知测试", f"账号 {a.name or a.acct_id} 通知正常")
    return API_OK(sent=ok, msg=msg)


@app.route("/api/accounts/<acct_id>", methods=["DELETE"])
@require_login
def account_delete(acct_id):
    a = owner_account(acct_id)
    MGR.remove_account(acct_id)
    return API_OK()


# ---------------- 站内消息中心（用户端） ----------------

@app.route("/api/messages", methods=["GET"])
@require_login
def messages_list():
    uname = current_user().username
    unread = request.args.get("unread") == "1"
    mtype = (request.args.get("type") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 200)
    except (TypeError, ValueError):
        limit = 100
    items = MESSAGES.list_for(uname, unread_only=unread, mtype=mtype, limit=limit)
    return API_OK(messages=items, unread=MESSAGES.unread_count(uname))


@app.route("/api/messages/unread-count", methods=["GET"])
@require_login
def messages_unread_count():
    return API_OK(unread=MESSAGES.unread_count(current_user().username))


@app.route("/api/messages/read-all", methods=["POST"])
@require_login
def messages_read_all():
    n = MESSAGES.mark_all_read(current_user().username)
    return API_OK(updated=n)


@app.route("/api/messages/read/clear", methods=["POST"])
@require_login
def messages_clear_read():
    n = MESSAGES.delete_read(current_user().username)
    return API_OK(deleted=n)


@app.route("/api/messages/<int:mid>/read", methods=["POST"])
@require_login
def messages_read(mid):
    if not MESSAGES.mark_read(mid, current_user().username):
        return API_ERR("消息不存在", 404)
    return API_OK(unread=MESSAGES.unread_count(current_user().username))


# ---------------- 工单 / 反馈（用户端） ----------------

@app.route("/api/tickets", methods=["POST"])
@require_login
def ticket_create():
    u = current_user()
    data = request.get_json(silent=True) or {}
    t, err = TICKETS.create(u.username, data.get("subject", ""), data.get("content", ""),
                            data.get("category", "other"))
    if not t:
        return API_ERR(err)
    return API_OK(ticket=TICKETS.summary(t))


@app.route("/api/tickets", methods=["GET"])
@require_login
def ticket_list():
    u = current_user()
    items = [TICKETS.summary(t) for t in TICKETS.list_by_uid(u.username)]
    return API_OK(tickets=items)


@app.route("/api/tickets/<int:tid>", methods=["GET"])
@require_login
def ticket_detail(tid):
    u = current_user()
    t = TICKETS.get(tid)
    if not t or t["uid"] != u.username:
        return API_ERR("工单不存在", 404)
    return API_OK(ticket=TICKETS.detail(t))


@app.route("/api/tickets/<int:tid>/reply", methods=["POST"])
@require_login
def ticket_reply(tid):
    u = current_user()
    t = TICKETS.get(tid)
    if not t or t["uid"] != u.username:
        return API_ERR("工单不存在", 404)
    data = request.get_json(silent=True) or {}
    ok, err = TICKETS.reply(tid, data.get("message", ""), u.username, "user")
    if not ok:
        return API_ERR(err)
    return API_OK(ticket=TICKETS.summary(t))


# ---------------- 后台 admin ----------------

@app.route("/api/admin/stats", methods=["GET"])
@require_admin
def admin_stats():
    site_users = MGR.site_users.list()
    accounts = MGR.all_accounts()
    online = sum(1 for a in accounts if a.logged_in())
    monitoring = sum(1 for a in accounts if a.monitoring)
    tk = TICKETS.list_all()
    sign = MGR.sign_stats()
    return API_OK(stats={
        "site_users": len(site_users),
        "accounts": len(accounts),
        "accounts_online": online,
        "accounts_monitoring": monitoring,
        "tickets_total": len(tk),
        "tickets_open": sum(1 for t in tk if t["status"] in ("open", "in_progress")),
        "announcements": len(ANNOUNCEMENTS.list_all()),
        "uptime": MGR.uptime_seconds(),
        **sign,
    })


@app.route("/api/admin/users", methods=["GET"])
@require_admin
def admin_users():
    users = MGR.site_users.list()
    enriched = []
    for u in users:
        accts = MGR.accounts_by_owner(u["username"])
        enriched.append({**u, "accounts": len(accts),
                         "online": sum(1 for a in accts if a.logged_in())})
    return API_OK(users=enriched, super=core.ADMIN_USERNAME)


@app.route("/api/admin/users", methods=["POST"])
@require_admin
def admin_user_create():
    data = request.get_json(silent=True) or {}
    role = "admin" if data.get("role") == "admin" else "user"
    email = (data.get("email", "") or "").strip()
    ok, err = MGR.site_users.register(data.get("username", ""), data.get("password", ""), role, email)
    if not ok:
        return API_ERR(err)
    return API_OK(user=MGR.site_users.get(data["username"].strip()).to_public())


@app.route("/api/admin/users/<username>/disable", methods=["POST"])
@require_admin
def admin_user_disable(username):
    if username == core.ADMIN_USERNAME:
        return API_ERR("不能禁用管理员账号")
    data = request.get_json(silent=True) or {}
    MGR.site_users.set_disabled(username, bool(data.get("disabled")))
    return API_OK()


@app.route("/api/admin/users/<username>", methods=["DELETE"])
@require_admin
def admin_user_delete(username):
    if username == core.ADMIN_USERNAME:
        return API_ERR("不能删除管理员账号")
    ok = MGR.site_users.delete(username)
    if not ok:
        return API_ERR("用户不存在", 404)
    for a in MGR.accounts_by_owner(username):
        MGR.remove_account(a.acct_id)
    return API_OK()


@app.route("/api/admin/accounts", methods=["GET"])
@require_admin
def admin_accounts():
    return API_OK(accounts=[a.summary() for a in MGR.all_accounts()])


@app.route("/api/admin/accounts/<acct_id>/monitor", methods=["POST"])
@require_admin
def admin_account_monitor(acct_id):
    a = MGR.get_account(acct_id)
    if not a:
        return API_ERR("账号不存在", 404)
    data = request.get_json(silent=True) or {}
    if data.get("on"):
        a.start_monitor()
    else:
        a.stop_monitor()
    return API_OK(monitoring=a.monitoring)


@app.route("/api/admin/accounts/<acct_id>", methods=["DELETE"])
@require_admin
def admin_account_delete(acct_id):
    ok = MGR.remove_account(acct_id)
    if not ok:
        return API_ERR("账号不存在", 404)
    return API_OK()


@app.route("/api/admin/accounts/<acct_id>/check", methods=["POST"])
@require_admin
def admin_account_check(acct_id):
    """管理员手动触发一次立即检测（不等监控轮询）"""
    a = MGR.get_account(acct_id)
    if not a:
        return API_ERR("账号不存在", 404)
    res = a.check_now()
    if not res.get("ok"):
        return API_ERR(res.get("msg") or "检查失败")
    return API_OK(login_ok=res.get("login_ok"), checked=res.get("checked"),
                  found=res.get("found") or [], msg=res.get("msg"))


@app.route("/api/admin/accounts/<acct_id>/logout", methods=["POST"])
@require_admin
def admin_account_logout(acct_id):
    """管理员强制下线某个学习通账号"""
    a = MGR.get_account(acct_id)
    if not a:
        return API_ERR("账号不存在", 404)
    a.logout()
    return API_OK()


@app.route("/api/admin/records", methods=["GET"])
@require_admin
def admin_records():
    """全局签到记录（可按用户/结果筛选）"""
    owner = request.args.get("owner") or None
    result = request.args.get("result") or None
    limit = min(int(request.args.get("limit", 200)), 500)
    rows = MGR.get_all_records(limit=limit, owner=owner, result=result)
    return API_OK(records=rows, sign_stats=MGR.sign_stats())


@app.route("/api/admin/users/<username>", methods=["PUT"])
@require_admin
def admin_user_update(username):
    """管理员编辑用户：邮箱 / 重置密码 / 角色"""
    data = request.get_json(silent=True) or {}
    email = data.get("email", None)
    new_pw = (data.get("password", "") or "").strip() or None
    role = data.get("role", None)
    if email is None and not new_pw and role is None:
        return API_ERR("没有需要更新的内容")
    ok, err = MGR.site_users.admin_update(username, email=email, new_password=new_pw, role=role)
    if not ok:
        return API_ERR(err)
    return API_OK(user=MGR.site_users.get(username.strip()).to_public())


@app.route("/api/admin/settings", methods=["GET"])
@require_admin
def admin_settings_get():
    return API_OK(settings=SETTINGS.all())


@app.route("/api/admin/settings", methods=["PUT"])
@require_admin
def admin_settings_update():
    data = request.get_json(silent=True) or {}
    fields = {k: v for k, v in data.items() if k in SETTINGS.DEFAULTS}
    if not fields:
        return API_ERR("没有可更新的设置项")
    return API_OK(settings=SETTINGS.update(**fields))


@app.route("/api/admin/logs", methods=["GET"])
@require_admin
def admin_logs():
    after = int(request.args.get("after", 0))
    uid = request.args.get("uid")
    return API_OK(logs=LOG.since(after, uid))


# ---------------- 工单后台管理 ----------------

@app.route("/api/admin/tickets", methods=["GET"])
@require_admin
def admin_ticket_list():
    status = request.args.get("status")
    items = [TICKETS.detail(t) for t in TICKETS.list_all(status=status)]
    return API_OK(tickets=items)


@app.route("/api/admin/tickets/<int:tid>", methods=["GET"])
@require_admin
def admin_ticket_detail(tid):
    t = TICKETS.get(tid)
    if not t:
        return API_ERR("工单不存在", 404)
    return API_OK(ticket=TICKETS.detail(t))


@app.route("/api/admin/tickets/<int:tid>/reply", methods=["POST"])
@require_admin
def admin_ticket_reply(tid):
    t = TICKETS.get(tid)
    if not t:
        return API_ERR("工单不存在", 404)
    u = current_user()
    data = request.get_json(silent=True) or {}
    ok, err = TICKETS.reply(tid, data.get("message", ""), u.username, "admin")
    if not ok:
        return API_ERR(err)
    # 站内消息通知工单作者
    try:
        MESSAGES.create(t["uid"], "ticket", f"工单 #{tid} 收到回复",
                        f"您的工单「{t.get('subject', '')}」收到了管理员回复：\n\n"
                        f"{data.get('message', '')}", ref_id=tid)
    except Exception:
        pass
    if data.get("close_after"):
        TICKETS.set_status(tid, "resolved")
    return API_OK(ticket=TICKETS.summary(t))


@app.route("/api/admin/tickets/<int:tid>/status", methods=["POST"])
@require_admin
def admin_ticket_status(tid):
    t = TICKETS.get(tid)
    if not t:
        return API_ERR("工单不存在", 404)
    data = request.get_json(silent=True) or {}
    ok, err = TICKETS.set_status(tid, data.get("status"), data.get("priority"))
    if not ok:
        return API_ERR(err)
    return API_OK(ticket=TICKETS.summary(t))


@app.route("/api/admin/tickets/<int:tid>", methods=["DELETE"])
@require_admin
def admin_ticket_delete(tid):
    ok = TICKETS.delete(tid)
    if not ok:
        return API_ERR("工单不存在", 404)
    return API_OK()


# ---------------- 公告后台管理 ----------------

@app.route("/api/admin/announcements", methods=["GET"])
@require_admin
def admin_announcements_list():
    items = [{
        **it, "type_label": AnnouncementStore.LABEL_TYPE.get(it["type"], it["type"]),
    } for it in ANNOUNCEMENTS.list_all()]
    return API_OK(announcements=items)


@app.route("/api/admin/announcements", methods=["POST"])
@require_admin
def admin_announcements_create():
    data = request.get_json(silent=True) or {}
    it, err = ANNOUNCEMENTS.create(
        data.get("title", ""), data.get("content", ""),
        data.get("type", "info"), data.get("enabled", True))
    if not it:
        return API_ERR(err)
    # 群发站内消息（消息中心），失败不影响公告本身
    try:
        usernames = [un for un, su in MGR.site_users.users.items() if not su.disabled]
        MESSAGES.create_many(usernames, "announcement", it["title"], it["content"],
                             ref_id=it["id"])
    except Exception:
        pass
    return API_OK(announcement=it)


@app.route("/api/admin/announcements/<int:aid>", methods=["PUT"])
@require_admin
def admin_announcements_update(aid):
    data = request.get_json(silent=True) or {}
    ok, err = ANNOUNCEMENTS.update(aid, **data)
    if not ok:
        return API_ERR(err, 404)
    return API_OK(announcement=ANNOUNCEMENTS.get(aid))


@app.route("/api/admin/announcements/<int:aid>", methods=["DELETE"])
@require_admin
def admin_announcements_delete(aid):
    ok = ANNOUNCEMENTS.delete(aid)
    if not ok:
        return API_ERR("公告不存在", 404)
    return API_OK()


# ---------------- 后台：邮件群发 ----------------

# 邮件群发任务注册表（进程内存；gunicorn 单 worker + 30s 超时，必须异步发送）
EMAIL_TASKS = {}
_EMAIL_TASK_SEQ = [0]


def _email_targets(to_mode, usernames):
    """解析收件人 -> [(username, email)]，自动去重并跳过禁用/无邮箱用户"""
    seen, out = set(), []
    if to_mode == "all":
        candidates = [(un, su) for un, su in MGR.site_users.users.items()]
    else:
        candidates = [(un, MGR.site_users.users.get(un)) for un in (usernames or [])]
    for un, su in candidates:
        if not su or su.disabled:
            continue
        email = (su.email or "").strip()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append((un, email))
    return out


@app.route("/api/admin/email/templates", methods=["GET"])
@require_admin
def admin_email_templates():
    return API_OK(templates=EMAIL_TEMPLATES)


@app.route("/api/admin/email/send", methods=["POST"])
@require_admin
def admin_email_send():
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    content = (data.get("content") or "").strip()
    to_mode = data.get("to_mode", "all")
    if to_mode not in ("all", "users"):
        return API_ERR("收件模式不正确")
    if not subject:
        return API_ERR("邮件主题不能为空")
    if not content:
        return API_ERR("邮件内容不能为空")
    targets = _email_targets(to_mode, data.get("usernames") or [])
    if not targets:
        return API_ERR("没有符合条件的收件人（需已绑定邮箱且未被禁用）")

    _EMAIL_TASK_SEQ[0] += 1
    tid = _EMAIL_TASK_SEQ[0]
    task = {"id": tid, "status": "running", "total": len(targets), "done": 0,
            "ok": 0, "fail": 0, "detail": [], "subject": subject,
            "created_at": core.now_iso()}
    EMAIL_TASKS[tid] = task
    # 后台线程无请求上下文，发送者需在请求内先取出
    me = current_user()
    sender = me.username if me else "admin"

    def _run():
        html = email_page(subject, content)
        for un, email in targets:
            try:
                ok, err = core.send_email(email, subject, html, content)
            except Exception as e:
                ok, err = False, str(e)
            task["done"] += 1
            if ok:
                task["ok"] += 1
            else:
                task["fail"] += 1
                task["detail"].append(f"{email}: {err}")
            time.sleep(1.0)
        task["status"] = "done"
        # 发送历史 + 同步生成站内消息（消息中心可见）
        try:
            EMAIL_LOGS.add(sender, to_mode, len(targets), subject,
                           task["ok"], task["fail"], "; ".join(task["detail"][:5]))
        except Exception:
            pass
        try:
            MESSAGES.create_many([un for un, _ in targets], "system", subject, content)
        except Exception:
            pass

    import threading
    threading.Thread(target=_run, daemon=True).start()
    log(f"启动邮件群发任务 #{tid}: {to_mode} {len(targets)} 人, 主题「{subject}」", "info")
    return API_OK(task_id=tid, total=len(targets))


@app.route("/api/admin/email/task/<int:tid>", methods=["GET"])
@require_admin
def admin_email_task(tid):
    t = EMAIL_TASKS.get(tid)
    if not t:
        return API_ERR("任务不存在", 404)
    return API_OK(task=t)


@app.route("/api/admin/email/logs", methods=["GET"])
@require_admin
def admin_email_logs():
    return API_OK(logs=EMAIL_LOGS.list_all(limit=50))


# ---------------- APP 版本（检测更新，公开） ----------------

@app.route("/api/app/version", methods=["GET"])
def app_version_check():
    """APP 检测更新（无需登录）。

    APP 启动时调用，可选带上自身版本：
      GET /api/app/version?version_code=3&version_name=1.0.3
    返回：
      latest            最新版本信息（含 download_url=apk_url）
      has_update        是否有新版本
      force_update      是否强制更新（新版本标记强制 或 当前版本低于最低支持版本）
      below_min_supported 当前版本是否已低于最低支持版本
    """
    res = APP_RELEASES.check(request.args.get("version_code"), request.args.get("version_name"))
    return API_OK(**res)


# ---------------- APP 闪屏（公开，无需登录） ----------------

@app.route("/api/app/splash", methods=["GET"])
def app_splash():
    """APP 闪屏配置（无需登录）。APP 启动时调用，配合闪屏页展示。

      GET /api/app/splash
    返回：
      enabled    是否展示闪屏（后台关闭或未配图片时为 false）
      image_url  闪屏图片链接（建议 1080x1920 竖图）
      duration   展示秒数（1~10，到时自动进入首页）
      jump_url   点击跳转链接（为空 = 点击不跳转）
    """
    d = SPLASH.all()
    image_url = str(d.get("image_url") or "").strip()
    return API_OK(
        enabled=bool(d.get("enabled")) and bool(image_url),
        image_url=image_url,
        duration=int(d.get("duration", 3) or 3),
        jump_url=str(d.get("jump_url") or "").strip(),
    )


# ---------------- APP 版本后台管理 ----------------

@app.route("/api/admin/app-releases", methods=["GET"])
@require_admin
def admin_app_releases_list():
    return API_OK(releases=APP_RELEASES.list_all())


@app.route("/api/admin/app-releases", methods=["POST"])
@require_admin
def admin_app_releases_create():
    data = request.get_json(silent=True) or {}
    it, err = APP_RELEASES.create(
        data.get("version_name", ""), data.get("version_code", 0),
        data.get("apk_url", ""), data.get("update_log", ""),
        data.get("force_update", False), data.get("min_supported_code", 0),
        data.get("enabled", True))
    if not it:
        return API_ERR(err)
    return API_OK(release=it)


@app.route("/api/admin/app-releases/<int:rid>", methods=["PUT"])
@require_admin
def admin_app_releases_update(rid):
    data = request.get_json(silent=True) or {}
    ok, err = APP_RELEASES.update(rid, **data)
    if not ok:
        return API_ERR(err, 404)
    return API_OK(release=APP_RELEASES.get(rid))


@app.route("/api/admin/app-releases/<int:rid>", methods=["DELETE"])
@require_admin
def admin_app_releases_delete(rid):
    ok = APP_RELEASES.delete(rid)
    if not ok:
        return API_ERR("版本不存在", 404)
    return API_OK()


# ---------------- APP 闪屏后台管理 ----------------

@app.route("/api/admin/splash", methods=["GET"])
@require_admin
def admin_splash_get():
    return API_OK(splash=SPLASH.all())


@app.route("/api/admin/splash", methods=["PUT"])
@require_admin
def admin_splash_update():
    data = request.get_json(silent=True) or {}
    fields = {k: v for k, v in data.items() if k in SPLASH.DEFAULTS}
    return API_OK(splash=SPLASH.update(**fields))


# ---------------- 通用 ----------------

@app.route("/api/ping", methods=["GET"])
def ping():
    return API_OK(pong=True, uptime=MGR.uptime_seconds())


@app.route("/openapi.json", methods=["GET"])
def openapi_spec():
    """公开返回 OpenAPI 规范，供 Apifox / 其他工具 URL 导入。"""
    p = os.path.join(ROOT, "openapi.json")
    if not os.path.exists(p):
        return API_ERR("openapi.json 不存在", 404)
    return send_from_directory(ROOT, "openapi.json", mimetype="application/json")


# ---------------- 公告（公开，无需登录） ----------------

@app.route("/api/announcements", methods=["GET"])
def announcements_public():
    items = ANNOUNCEMENTS.active()
    return API_OK(announcements=[{
        "id": it["id"], "title": it["title"], "content": it["content"], "type": it["type"],
    } for it in items])


# ---------------- 静态前端 ----------------

@app.route("/static/<path:p>")
def serve_static(p):
    return send_from_directory(os.path.join(ROOT, "static"), p)


@app.route("/help")
def serve_help():
    """使用教程（无需登录）"""
    try:
        return open(os.path.join(ROOT, "help.html"), encoding="utf-8").read()
    except OSError:
        abort(404)


@app.route("/")
def serve_landing():
    """网站主界面：产品介绍（网页版 / APP版）"""
    try:
        import html as _html
        html = open(os.path.join(ROOT, "landing.html"), encoding="utf-8").read()
        site_name = _html.escape(SETTINGS.get("site_name", "马上签") or "马上签")
        html = html.replace("<title>马上签</title>", f"<title>{site_name}</title>", 1)
        return html
    except OSError:
        abort(404)


@app.route("/app", defaults={"p": ""})
@app.route("/app/<path:p>")
def serve_user(p):
    if p.startswith("api") or p.startswith("static") or p.startswith("admin"):
        abort(404)
    try:
        import html as _html
        html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        site_name = _html.escape(SETTINGS.get("site_name", "马上签") or "马上签")
        html = html.replace("<title>马上签</title>", f"<title>{site_name}</title>", 1)
        return html
    except OSError:
        abort(404)


# ---------------- 协助签到（同学帮签，公开免登录） ----------------

_ip_hits = {}


def _rate_ok(ip, limit=20, window=60):
    now = time.time()
    hits = _ip_hits.get(ip, [])
    hits = [t for t in hits if now - t < window]
    if len(hits) >= limit:
        _ip_hits[ip] = hits
        return False
    hits.append(now)
    _ip_hits[ip] = hits
    return True


def _assist_account(token):
    acct_id = core.resolve_token(token)
    if not acct_id:
        return None
    return MGR.get_account(acct_id)


# ---- 协助签到（同学帮签）H5 / 接口 ----
def assist_page_html(token):
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>马上签 · 同学帮签</title>
<script src="https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js"></script>
<style>
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif; background:#f2f5fa; color:#1f2937; }
header { background:linear-gradient(135deg,#1677ff,#4096ff); color:#fff; padding:18px 16px; font-size:18px; font-weight:700; box-shadow:0 2px 8px rgba(22,119,255,.25); }
.wrap { max-width:560px; margin:0 auto; padding:16px; }
.empty { text-align:center; color:#8c95a3; padding:48px 12px; }
.card { background:#fff; border-radius:14px; padding:16px; margin-bottom:14px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.card h3 { margin:0 0 4px; font-size:16px; }
.card .meta { color:#6b7280; font-size:13px; margin-bottom:12px; }
.badge { display:inline-block; background:#e6f0ff; color:#1677ff; font-size:12px; padding:2px 8px; border-radius:6px; margin-left:6px; }
.btn { display:block; width:100%; border:0; border-radius:10px; background:#1677ff; color:#fff; font-size:16px; font-weight:600; padding:12px; margin-top:10px; }
.btn:active { background:#0e5fd8; }
.btn.ghost { background:#eef2f8; color:#475569; }
.row-btn { display:flex; gap:10px; } .row-btn .btn { margin-top:0; }
.grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; max-width:240px; margin:10px auto; }
.cell { aspect-ratio:1; border-radius:50%; background:#eef2f8; display:flex; align-items:center; justify-content:center; font-size:20px; color:#94a3b8; font-weight:700; user-select:none; }
.cell.on { background:#1677ff; color:#fff; }
.seq { text-align:center; font-size:15px; color:#1677ff; margin:8px 0; min-height:20px; font-weight:600; }
input[type=text],textarea { width:100%; border:1px solid #d9dee7; border-radius:10px; padding:10px; font-size:15px; font-family:inherit; }
.link { color:#1677ff; word-break:break-all; }
.toast { position:fixed; left:50%; top:30%; transform:translateX(-50%); background:rgba(0,0,0,.82); color:#fff; padding:12px 18px; border-radius:10px; font-size:15px; display:none; z-index:99; max-width:80%; text-align:center; }
.ok { color:#389e0d; } .bad { color:#cf1322; }
.cam { position:fixed; inset:0; background:#000; z-index:20; display:flex; flex-direction:column; overflow:hidden; }
.cam.hidden { display:none; }
.cam video { flex:1; width:100%; object-fit:contain; background:#000; }
.cam-bar { position:relative; z-index:2; display:flex; align-items:center; gap:8px; padding:12px; background:#111; }
.cam-btn { flex:1; border:0; border-radius:10px; background:#1677ff; color:#fff; font-size:15px; font-weight:600; padding:12px; }
.cam-btn.ghost { background:#333; color:#fff; flex:0 0 72px; padding:12px 6px; }
.cam-hint { flex:1; color:#fff; font-size:14px; text-align:center; }
.cam-hint.ok { color:#52c41a; font-weight:600; }
.cam-hint.bad { color:#ff7875; font-weight:600; }
.guide { position:fixed; inset:0; background:rgba(15,23,42,.75); z-index:60; display:flex; align-items:center; justify-content:center; padding:20px; }
.guide.hidden { display:none; }
.guide-card { background:#fff; border-radius:16px; padding:26px 22px; max-width:340px; width:100%; text-align:center; box-shadow:0 8px 40px rgba(0,0,0,.25); }
.guide-icon { font-size:42px; line-height:1; }
.guide-title { font-size:19px; font-weight:700; margin:10px 0 12px; }
.guide-reason { font-size:13px; color:#6b7280; line-height:1.7; margin-bottom:12px; }
.guide-steps { font-size:14px; color:#1f2937; line-height:2; text-align:left; background:#f2f5fa; border-radius:10px; padding:12px 14px; margin-bottom:6px; }
footer { text-align:center; color:#aab2bf; font-size:12px; padding:18px; }
</style></head>
<body>
<header>马上签 · 同学帮签</header>
<div class="wrap"><div id="box"><div class="empty">加载中…</div></div></div>
<div class="toast" id="toast"></div>
<div id="cam" class="cam hidden">
  <video id="video" playsinline autoplay muted></video>
  <div class="cam-bar">
    <button id="camCancel" class="cam-btn ghost">取消</button>
    <div id="camHint" class="cam-hint">对准二维码，自动识别</div>
    <button id="torchBtn" class="cam-btn ghost" style="display:none">🔦 开灯</button>
    <button id="zoomBtn" class="cam-btn ghost" style="display:none">🔍 放大</button>
  </div>
  <canvas id="cv" hidden></canvas>
</div>
<div id="guide" class="guide hidden">
  <div class="guide-card">
    <div class="guide-icon">🌐</div>
    <div class="guide-title">请使用浏览器打开</div>
    <div class="guide-reason" id="guideReason"></div>
    <div class="guide-steps" id="guideSteps"></div>
    <button class="btn" id="guideOpen">🌐 用浏览器打开</button>
    <button class="btn" id="guideCopy">📋 复制链接</button>
    <button class="btn ghost" id="guideTry">仍要尝试（手势 / 签到码不受影响）</button>
  </div>
</div>
<footer>协助链接仅供本账号完成当前签到使用</footer>
<script>
const TOKEN="__TOKEN__";
const UA=navigator.userAgent;
const IN_APP=/MicroMessenger|QQ\/[\d.]|Weibo|DingTalk|AlipayClient|aweme|NewsArticle|baiduboxapp|115La|SogouMSE/i.test(UA);
const IS_IOS=/iPad|iPhone|iPod/.test(UA)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
let stream=null,scanning=false,curAid=null,_seq={},lastEnc='',lastAt=0,qrLoop=null,qrPass=0,torchOn=false,zoomOn=false;
const $=id=>document.getElementById(id);
function toast(msg,ok){ const t=$('toast'); t.textContent=msg; t.className='toast'; if(ok!==undefined) t.classList.add(ok?'ok':'bad'); t.style.display='block'; setTimeout(()=>t.style.display='none',2200); }
function esc(s){ return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
// ---- 应用内 WebView 引导（微信 / QQ 等内置浏览器禁用摄像头）----
function showInAppGuide(reason){
  $('guideReason').innerHTML=reason||'微信 / QQ 等 App 的内置浏览器禁止调用摄像头，无法扫码。';
  $('guideSteps').innerHTML=IS_IOS
    ? '1. 点击底部工具栏的 <b>···</b><br>2. 选择「在 Safari 中打开」'
    : '1. 点击右上角 <b>···</b> 或 <b>⋮</b><br>2. 选择「在浏览器中打开」';
  $('guide').classList.remove('hidden');
}
function copyLink(){
  const url=location.href;
  const done=()=>{ $('guideCopy').textContent='✅ 已复制'; setTimeout(()=>$('guideCopy').textContent='📋 复制链接',2000);
    toast('链接已复制，请粘贴到浏览器地址栏打开',true); };
  const fallback=()=>{
    let box=$('manualCopy');
    if(!box){
      box=document.createElement('div'); box.id='manualCopy'; box.style.marginTop='10px';
      const tip=document.createElement('div');
      tip.style.cssText='font-size:12px;color:#6b7280;margin-bottom:6px;text-align:left';
      tip.textContent='自动复制失败，请长按选择下方链接复制：';
      const inp=document.createElement('input'); inp.type='text'; inp.value=url; inp.setAttribute('readonly','');
      inp.style.cssText='width:100%;border:1px solid #d9dee7;border-radius:10px;padding:10px;font-size:14px;font-family:inherit;background:#fff;';
      inp.onclick=function(){ this.select(); };
      box.appendChild(tip); box.appendChild(inp);
      $('guide').querySelector('.guide-card').appendChild(box);
    }
    toast('自动复制失败，请手动复制链接',false);
  };
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(url).then(done).catch(fallback); } else fallback();
}
function tryOpenBrowser(){
  // Android：intent  scheme 尝试拉起系统浏览器（微信多数版本会静默拦截，失败则用户用复制链接）
  if(!IS_IOS){
    try{
      const u=location.href, m=u.match(/^https?:\/\/([^\/]+)(\/.*)?$/);
      if(m) location.href='intent://'+m[1]+(m[2]||'')+'#Intent;scheme=https;package=com.android.browser;end;S.browser_fallback_url='+encodeURIComponent(u);
    }catch(e){}
  }
  copyLink();  // iOS 无程序化跳转能力，直接复制链接
}
$('guideOpen').onclick=tryOpenBrowser;
$('guideCopy').onclick=copyLink;
$('guideTry').onclick=()=>$('guide').classList.add('hidden');
if(IN_APP) showInAppGuide();
async function load(){
  const r=await fetch('/api/assist/'+TOKEN+'/pending'); const d=await r.json(); const box=$('box');
  if(!d.ok||!d.items||!d.items.length){ box.innerHTML='<div class="empty">当前没有需要帮忙的签到了 🙂<br>老师发二维码 / 手势签到后，这里会出现帮签入口。</div>'; return; }
  box.innerHTML=d.items.map(render).join('');
}
function render(it){
  if(it.kind==='qr'){
    return `<div class="card"><h3>${esc(it.course)}<span class="badge">二维码</span></h3>
      <div class="meta">${esc(it.activity)} · ${it.expires_in>0?Math.floor(it.expires_in/60)+' 分钟后过期':''}</div>
      <div style="font-size:13px;color:#6b7280;margin-bottom:6px">老师屏幕的二维码刷新很快。点下方按钮扫码，页面会自动校验二维码是否有效；失效时会提示你重扫最新的码。看不清可点「🔍 放大」（数字变焦，所有手机可用），教室暗可点「🔦 开灯」（需硬件支持）。</div>
      <button class="btn" onclick="openCam('${it.active_id}')">📷 扫码签到</button>
      <div id="qr_fb_${it.active_id}" style="display:none;margin-top:10px">
        <textarea id="qr_${it.active_id}" placeholder="扫码不可用？手动粘贴二维码链接或 enc 值" style="height:64px"></textarea>
        <button class="btn" onclick="submitQr('${it.active_id}')">提交并签到</button></div></div>`;
  }
  if(it.tname==='手势'){
    _seq[it.active_id]=_seq[it.active_id]||[];
    return `<div class="card"><h3>${esc(it.course)}<span class="badge">手势</span></h3>
      <div class="meta">${esc(it.activity)} · 抬头看一眼老师屏幕的手势，照着在下面九宫格里按顺序点出来</div>
      <div class="seq" id="seq_${it.active_id}">未选择</div>
      <div class="grid" id="grid_${it.active_id}">${[1,2,3,4,5,6,7,8,9].map(n=>`<div class="cell" data-n="${n}" onclick="gtap('${it.active_id}',${n})">${n}</div>`).join('')}</div>
      <div class="row-btn"><button class="btn ghost" onclick="greset('${it.active_id}')">重画</button><button class="btn" onclick="submitGesture('${it.active_id}')">确认并帮我签到</button></div></div>`;
  }
  return `<div class="card"><h3>${esc(it.course)}<span class="badge">签到码</span></h3>
    <div class="meta">${esc(it.activity)} · 输入老师公布的签到码</div>
    <input type="text" id="code_${it.active_id}" placeholder="4 位签到码" maxlength="12" inputmode="numeric">
    <button class="btn" onclick="submitCode('${it.active_id}')">提交并帮我签到</button></div>`;
}
async function openCam(aid){
  curAid=aid;
  if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){
    showInAppGuide('当前浏览器不支持调用摄像头，无法扫码。'); const fb=$('qr_fb_'+aid); if(fb) fb.style.display='block'; return;
  }
  // 高清采集：1080p 起步 + 连续对焦，遠距离投屏二维码的识别率关键
  let constraints={audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}}};
  try{
    const cams=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');
    const rear=cams.find(d=>/back|rear|environment|后置/i.test(d.label||''));
    if(rear) constraints.video.deviceId={exact:rear.deviceId};
  }catch(e){}
  try{ stream=await navigator.mediaDevices.getUserMedia(constraints); }
  catch(e){
    toast('无法打开摄像头：'+(e&&e.message||e),false);
    showInAppGuide(IN_APP?'微信 / QQ 等 App 的内置浏览器禁止调用摄像头，无法扫码。':'当前环境不允许使用摄像头，请检查权限或改用系统浏览器。');
    const fb=$('qr_fb_'+aid); if(fb) fb.style.display='block'; return;
  }
  const v=$('video'); v.srcObject=stream; try{ await v.play(); }catch(e){}
  // 连续对焦 + 手电筒/变焦能力探测（部分机型不支持，隐藏按钮即可）
  try{
    const t=stream.getVideoTracks()[0];
    const caps=(t.getCapabilities&&t.getCapabilities())||{};
    if(caps.focusMode&&caps.focusMode.includes('continuous')){
      try{ await t.applyConstraints({advanced:[{focusMode:'continuous'}]}); }catch(e){}
    }
    $('torchBtn').style.display=caps.torch?'block':'none';
    $('zoomBtn').style.display='block';   // 数字变焦：所有设备可用，常驻
  }catch(e){}
  $('cam').classList.remove('hidden'); $('camHint').textContent='对准老师屏幕的二维码，自动识别并校验'; $('camHint').className='cam-hint';
  startQr();
}
$('torchBtn').onclick=async()=>{
  if(!stream) return;
  try{ const t=stream.getVideoTracks()[0]; torchOn=!torchOn;
    await t.applyConstraints({advanced:[{torch:torchOn}]});
    $('torchBtn').textContent=torchOn?'🔦 关灯':'🔦 开灯';
  }catch(e){ toast('该设备不支持手电筒',false); }
};
$('zoomBtn').onclick=()=>{
  if(!stream) return;
  // 数字变焦：不依赖硬件 zoom 能力（iOS / 多数 WebView 不暴露），预览放大 2 倍，
  // 扫描区同步切到中心裁剪（见 startQr 的 crops），视觉与识别完全对齐
  zoomOn=!zoomOn;
  const v=$('video');
  v.style.transform=zoomOn?'scale(2)':'none';
  v.style.transformOrigin='center center';
  $('zoomBtn').textContent=zoomOn?'🔍 1x':'🔍 放大';
};
function stopCam(){ if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; } zoomOn=false; torchOn=false; const v=$('video'); if(v){ v.style.transform='none'; } $('cam').classList.add('hidden'); scanning=false; }
$('camCancel').onclick=()=>{ const fb=$('qr_fb_'+curAid); if(fb) fb.style.display='block'; stopCam(); };
function startQr(){
  if(!window.jsQR){ const fb=$('qr_fb_'+curAid); if(fb) fb.style.display='block'; toast('扫码组件未加载，请手动粘贴',false); stopCam(); return; }
  scanning=true; qrPass=0; const cv=$('cv'), v=$('video');
  const ctx=cv.getContext('2d',{willReadFrequently:true});
  // 三档视野逐帧轮换：全画幅 → 中心 60% → 中心 35%，等价逐级放大，
  // 远距离小二维码也能拿到足够的模块像素，避免"贴到老师脸上"才能扫
  const crops=()=>zoomOn
    ? [[v.videoWidth*.25,v.videoHeight*.25,v.videoWidth*.5,v.videoHeight*.5],
       [v.videoWidth*.35,v.videoHeight*.35,v.videoWidth*.3,v.videoHeight*.3],
       [v.videoWidth*.425,v.videoHeight*.425,v.videoWidth*.15,v.videoHeight*.15]]
    : [[0,0,v.videoWidth,v.videoHeight],
       [v.videoWidth*.2,v.videoHeight*.2,v.videoWidth*.6,v.videoHeight*.6],
       [v.videoWidth*.325,v.videoHeight*.325,v.videoWidth*.35,v.videoHeight*.35]];
  qrLoop=function(){
    if(!scanning) return;
    if(v.readyState>=2&&v.videoWidth){
      const c=crops()[qrPass%3]; qrPass++;
      const TARGET=560;
      const scale=Math.min(1.6,TARGET/c[2]);
      const sw=Math.max(1,Math.round(c[2]*scale)), sh=Math.max(1,Math.round(c[3]*scale));
      if(cv.width!==sw||cv.height!==sh){ cv.width=sw; cv.height=sh; }
      try{
        ctx.drawImage(v,c[0],c[1],c[2],c[3],0,0,sw,sh);
        const r=jsQR(ctx.getImageData(0,0,sw,sh).data,sw,sh);
        if(r&&r.data){ onScan(r.data); return; }
      }catch(e){}
    }
    requestAnimationFrame(qrLoop);
  };
  requestAnimationFrame(qrLoop);
}
function onScan(data){
  const m=(data||'').match(/enc=([^&\s"']+)/); const hint=$('camHint');
  if(!m){ hint.textContent='❌ 无效二维码：不是签到码，请对准老师屏幕'; hint.className='cam-hint bad';
    setTimeout(()=>{ if(scanning){ hint.textContent='对准老师屏幕的二维码，自动识别并校验'; hint.className='cam-hint'; if(qrLoop) requestAnimationFrame(qrLoop); } },1200); return; }
  const enc=m[1], now=Date.now();
  if(enc===lastEnc&&now-lastAt<3000){ setTimeout(()=>{ if(scanning&&qrLoop) requestAnimationFrame(qrLoop); },600); return; }
  lastEnc=enc; lastAt=now; scanning=false;
  hint.textContent='✅ 二维码有效，正在提交…'; hint.className='cam-hint ok';
  submitQr(curAid,data,true);
}
function gtap(aid,n){ const s=_seq[aid]||(_seq[aid]=[]); if(s[s.length-1]===n){ s.pop(); } else { s.push(n); } paint(aid); }
function greset(aid){ _seq[aid]=[]; paint(aid); }
function paint(aid){ const seq=_seq[aid]||[]; const el=$('seq_'+aid); if(el) el.textContent=seq.length?seq.join(' → '):'未选择';
  document.querySelectorAll('#grid_'+aid+' .cell').forEach(c=>c.classList.toggle('on',seq.includes(+c.dataset.n))); }
async function submitQr(aid,val,fromCam){ let v=(val||($('qr_'+aid)?$('qr_'+aid).value:'')||'').trim(); const m=v.match(/enc=([^&\s"']+)/); if(m) v=m[1];
  if(!v){ toast('未识别到二维码内容',false); if(fromCam) stopCam(); return; }
  let d; try{ d=await post('/api/assist/'+TOKEN+'/qr',{active_id:aid,value:v}); }catch(e){ toast('网络异常，请重试',false); if(fromCam) stopCam(); return; }
  if(fromCam&&!d.ok){ if(/过期|失效|无效|已使用|不存在|已结束|expired/i.test(d.msg||'')){ toast('❌ 二维码已失效（老师屏幕的码刷新很快），请扫最新的码',false);
    $('camHint').textContent='二维码已失效，请扫老师屏幕上最新的码'; $('camHint').className='cam-hint bad'; startQr(); } else { stopCam(); } } }
async function submitCode(aid){ const v=$('code_'+aid).value.trim(); if(!v){ toast('请输入签到码',false); return; } await post('/api/assist/'+TOKEN+'/gesture',{active_id:aid,value:v}); }
async function submitGesture(aid){ const v=(_seq[aid]||[]).join(''); if(!v){ toast('请先按顺序点出手势',false); return; } await post('/api/assist/'+TOKEN+'/gesture',{active_id:aid,value:v}); }
async function post(url,body){ const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const d=await r.json();
  if(d.ok){ if(!$('cam').classList.contains('hidden')) stopCam(); toast('✅ 已帮你签到成功'); setTimeout(load,1200); } else { toast('⚠️ '+(d.msg||'提交失败'),false); } return d; }
load();
</script>
</body></html>""".replace("__TOKEN__", token)


@app.route("/assist/<token>", methods=["GET"])
def assist_page(token):
    acct = _assist_account(token)
    if not acct:
        return Response("<h2 style='text-align:center;margin-top:40px;color:#888'>协助链接无效或已失效</h2>"
                        "<p style='text-align:center;color:#aaa'>请让账号主人在「马上签」账号详情页重新生成协助链接。</p>",
                        mimetype="text/html")
    return Response(assist_page_html(token), mimetype="text/html")


@app.route("/api/assist/<token>/pending", methods=["GET"])
def assist_pending(token):
    acct = _assist_account(token)
    if not acct:
        return API_ERR("协助链接无效或已失效", 404)
    return API_OK(items=acct.assist_pending_list())


@app.route("/api/assist/<token>/qr", methods=["POST"])
def assist_qr(token):
    ip = request.remote_addr
    if not _rate_ok(ip):
        return API_ERR("操作过于频繁，请稍后再试", 429)
    acct = _assist_account(token)
    if not acct:
        return API_ERR("协助链接无效或已失效", 404)
    data = request.get_json(silent=True) or {}
    aid = str(data.get("active_id", "")).strip()
    value = (data.get("value") or "").strip()
    if not aid or not value:
        return API_ERR("缺少 active_id 或 enc", 400)
    ok, detail = acct.assist_submit(aid, value)
    return API_OK(ok=ok, detail=detail) if ok else API_ERR(detail, 400)


@app.route("/api/assist/<token>/gesture", methods=["POST"])
def assist_gesture(token):
    ip = request.remote_addr
    if not _rate_ok(ip):
        return API_ERR("操作过于频繁，请稍后再试", 429)
    acct = _assist_account(token)
    if not acct:
        return API_ERR("协助链接无效或已失效", 404)
    data = request.get_json(silent=True) or {}
    aid = str(data.get("active_id", "")).strip()
    value = (data.get("value") or "").strip()
    if not aid or not value:
        return API_ERR("缺少 active_id 或 手势/签到码", 400)
    ok, detail = acct.assist_submit(aid, value)
    return API_OK(ok=ok, detail=detail) if ok else API_ERR(detail, 400)


@app.route("/api/accounts/<acct_id>/assist-token", methods=["GET", "POST"])
@require_login
def assist_token_reset(acct_id):
    a = owner_account(acct_id)
    data = request.get_json(silent=True) or {}
    # set_token_for 会自动移除该账号的旧 token 映射；reset=false 时若已有则复用
    if request.method == "POST" and (data.get("reset") or not core.get_token_for(a.acct_id)):
        token = core.set_token_for(a.acct_id)   # 重新生成（旧链接立即失效）
    else:
        token = core.get_token_for(a.acct_id) or core.set_token_for(a.acct_id)
    return API_OK(token=token, link=f"{core.SITE_BASE}/assist/{token}")


@app.route("/my-assist", methods=["GET"])
@require_login
def my_assist():
    u = current_user()
    accts = MGR.accounts_by_owner(u.username)
    cards = []
    for a in accts:
        token = core.get_token_for(a.acct_id) or core.set_token_for(a.acct_id)
        link = f"{core.SITE_BASE}/assist/{token}"
        cards.append(f"""<div class="card">
  <div class="name">{_esc(a.name or a.acct_id)}</div>
  <div class="row"><span class="lbl">待协助</span><b>{len(a.assist_pending_list())}</b> 个</div>
  <div class="link" id="lk_{a.acct_id}">{link}</div>
  <button class="btn" onclick="copy('{a.acct_id}')">复制协助链接</button>
</div>""")
    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>协助链接 · 马上签</title><style>
* { box-sizing:border-box; } body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif; background:#f2f5fa; color:#1f2937; }
header { background:linear-gradient(135deg,#1677ff,#4096ff); color:#fff; padding:16px; font-size:17px; font-weight:700; }
.wrap { max-width:560px; margin:0 auto; padding:14px; }
.card { background:#fff; border-radius:14px; padding:16px; margin-bottom:12px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.name { font-size:16px; font-weight:700; margin-bottom:8px; }
.row { color:#6b7280; font-size:14px; margin-bottom:8px; }
.link { word-break:break-all; background:#eef2f8; padding:10px; border-radius:8px; font-size:13px; color:#1677ff; margin-bottom:10px; }
.btn { width:100%; border:0; border-radius:10px; background:#1677ff; color:#fff; font-size:15px; font-weight:600; padding:11px; }
.empty { text-align:center; color:#8c95a3; padding:40px 12px; }
</style></head><body>
<header>协助链接（发给教室里的同学）</header>
<div class="wrap">__CARDS__</div>
<script>
function copy(id){ const t=document.getElementById('lk_'+id).textContent; navigator.clipboard.writeText(t).then(()=>alert('已复制，发给同学即可')); }
</script></body></html>"""
    body = html.replace("__CARDS__", "".join(cards) if cards else
                        '<div class="empty">你还没有添加学习通账号。</div>')
    return Response(body, mimetype="text/html")


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


@app.route("/<path:p>")
def serve_catchall(p):
    if p.startswith("api") or p.startswith("static") or p.startswith("admin") or p.startswith("app"):
        abort(404)
    try:
        import html as _html
        html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
        site_name = _html.escape(SETTINGS.get("site_name", "马上签") or "马上签")
        html = html.replace("<title>马上签</title>", f"<title>{site_name}</title>", 1)
        return html
    except OSError:
        abort(404)


@app.route("/admin", defaults={"p": ""})
@app.route("/admin/<path:p>")
def serve_admin(p):
    return send_from_directory(ROOT, "admin.html")


# ---------------- 启动 ----------------

def main():
    port = int(os.environ.get("PORT", "8765"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


core.boot()

if __name__ == "__main__":
    main()
