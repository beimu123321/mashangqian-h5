# -*- coding: utf-8 -*-
"""
学习通（超星）自动签到 - 核心模块（多用户站点版 + 工单反馈）

两层模型:
  SiteUser（网站账号，需登录 / 开放注册 + 预置管理员）
    └─ 拥有 N 个 ChaoxingAccount（学习通账号，扫码登录）
          └─ 独立登录态 / 配置 / 监控线程；仅自动完成【普通签到】

另含:
  Ticket（用户反馈 / 工单系统，用户提交、管理员处理）

协议（2026 实测）:
  登录     passport2.chaoxing.com  二维码: cloudscanlogin -> createqr -> getauthstatus
  课程     mooc1-api.chaoxing.com/mycourse/backclazzdata?rss=1
  活动检测 mobilelearn.chaoxing.com/v2/apis/active/student/activelist
           status==1 且 otherId in [0,5] 且开始 2 小时内
           otherId: 0=普通/拍照 2=二维码 3=手势 4=位置 5=签到码
  预签到   newsign/preSign -> pptSign/analysis(抠 code) -> pptSign/analysis2
  提交     pptSign/stuSignajax（普通: latitude=-1&longitude=-1&fid=<真实fid>&name=<姓名>）
"""
import base64
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import smtplib
import threading
import time
import urllib.parse
import uuid as _uuid
from collections import deque
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import requests

BASE = "https://mobilelearn.chaoxing.com"
UA = ("Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220829.002; wv) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/107.0.0.0 Mobile Safari/537.36")

SIGN_TYPES = {0: "普通/拍照", 2: "二维码", 3: "手势", 4: "位置", 5: "签到码"}

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
LEGACY_USERS_DIR = os.path.join(DATA_DIR, "users")
SITE_USERS_FILE = os.path.join(DATA_DIR, "site_users.json")
TICKETS_FILE = os.path.join(DATA_DIR, "tickets.json")
ANNOUNCEMENTS_FILE = os.path.join(DATA_DIR, "announcements.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")
ASSIST_TOKENS_FILE = os.path.join(DATA_DIR, "assist_tokens.json")
# 协助签到链接的对外域名（同学访问前缀）；可用环境变量覆盖
SITE_BASE = os.environ.get("SITE_BASE", "https://xxt.leich.cn").rstrip("/")
_assist_tokens = None


def _load_assist_tokens():
    global _assist_tokens
    if _assist_tokens is None:
        _assist_tokens = load_json(ASSIST_TOKENS_FILE, {})
    return _assist_tokens


def save_assist_tokens():
    save_json(ASSIST_TOKENS_FILE, _load_assist_tokens())


def get_token_for(acct_id):
    toks = _load_assist_tokens()
    for t, a in toks.items():
        if str(a) == str(acct_id):
            return t
    return None


def set_token_for(acct_id, token=None):
    toks = _load_assist_tokens()
    toks = {t: a for t, a in toks.items() if str(a) != str(acct_id)}
    token = token or secrets.token_hex(16)
    toks[token] = str(acct_id)
    global _assist_tokens
    _assist_tokens = toks
    save_assist_tokens()
    return token


def resolve_token(token):
    return _load_assist_tokens().get(token)
EMAIL_LOGS_FILE = os.path.join(DATA_DIR, "email_logs.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
APP_RELEASES_FILE = os.path.join(DATA_DIR, "app_releases.json")
SPLASH_FILE = os.path.join(DATA_DIR, "splash.json")
SECRET_FILE = os.path.join(DATA_DIR, "secret.key")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
# 后台管理员密码：请通过环境变量 ADMIN_PASSWORD 提供，不要写死在代码里
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# ---- QQ 邮箱通知（SMTP）----
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
# 邮件授权码：请通过环境变量 SMTP_PASS 提供，不要写死在代码里
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# 工单提醒收件邮箱：收到新工单或用户回复时，自动发送邮件提醒到此邮箱
# 可用环境变量 TICKET_NOTIFY_EMAIL 覆盖（生产环境在 gunicorn_conf.py 的 raw_env 中注入）
TICKET_NOTIFY_EMAIL = os.environ.get("TICKET_NOTIFY_EMAIL", "535919101@qq.com")

# 手动「立即检查」冷却时间（秒）：防止用户连点扫描触发学习通风控
MANUAL_CHECK_COOLDOWN = 60

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(s):
    return bool(EMAIL_RE.match((s or "").strip()))

DEFAULT_CONFIG = {
    "interval": 45,
    "serverchan_key": "",
    "enabled_courses": [],
    "monitor_on": True,
    "need_relogin": False,
    # 限频自动冷却：被学习通大面积限频时停机静默，到此时间戳（Unix 秒）后由看门狗自动恢复
    "freq_cooldown_until": 0,
    "owner": "",
    # 位置模拟签到（otherId=4 位置签到时提交指定坐标，实现“位置模拟”）
    "loc_enabled": False,
    "loc_lat": "",
    "loc_lng": "",
    "loc_addr": "",
}


def now_str():
    return datetime.now().strftime("%m-%d %H:%M:%S")


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 100000)
    return dk.hex(), salt


def get_secret_key():
    if os.path.exists(SECRET_FILE):
        try:
            with open(SECRET_FILE, "rb") as f:
                return f.read()
        except Exception:
            pass
    k = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    with open(SECRET_FILE, "wb") as f:
        f.write(k)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except Exception:
        pass
    return k


# ---------------- 日志 ----------------

class Logger:
    def __init__(self):
        self.buf = deque(maxlen=3000)
        self.lock = threading.Lock()
        self.seq = 0

    def log(self, msg, level="info", uid=None):
        with self.lock:
            self.seq += 1
            item = {"seq": self.seq, "time": now_str(), "msg": str(msg),
                    "level": level, "uid": uid or ""}
            self.buf.append(item)
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(os.path.join(DATA_DIR, "app.log"), "a", encoding="utf-8") as f:
                f.write(f"[{item['time']}]{'[' + str(uid) + ']' if uid else ''} {msg}\n")
        except Exception:
            pass

    def since(self, after_seq, uid=None):
        with self.lock:
            if uid:
                return [x for x in self.buf if x["seq"] > after_seq and x["uid"] in (uid, "")]
            return [x for x in self.buf if x["seq"] > after_seq]


LOG = Logger()


def log(msg, level="info", uid=None):
    LOG.log(msg, level, uid)


# ---------------- 学习通客户端 ----------------

class CxClient:
    """一个实例 = 一个已登录会话"""

    def __init__(self, cookies=None):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        if cookies:
            for c in cookies:
                try:
                    self.s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".chaoxing.com"))
                except Exception:
                    pass
        self.uid = self.s.cookies.get("_uid", "")
        self.fid = self.s.cookies.get("fid", "-1") or "-1"
        self.name = ""

    def cookies_list(self):
        return [{"name": c.name, "value": c.value, "domain": c.domain} for c in self.s.cookies]

    def check_valid(self):
        try:
            r = self.s.get("https://passport2.chaoxing.com/mooc/accountManage", timeout=15)
            m = re.search(r'class="fr colorBlue"[^>]*>\s*([^<\s]+)\s*</p>', r.text)
            if m:
                self.name = m.group(1).strip()
                return True
            if "accountManage" in r.url and "用户登录" not in r.text and "login" not in r.url.lower():
                return True
        except Exception as e:
            log(f"验证登录态出错: {e}", "warn", self.uid)
        return False

    def _refresh_ids(self):
        self.uid = self.s.cookies.get("_uid", "") or self.uid
        self.fid = self.s.cookies.get("fid", "") or self.fid or "-1"

    @staticmethod
    def qr_create():
        s = requests.Session()
        s.headers["User-Agent"] = UA
        tip = urllib.parse.quote("电脑端登录确认")
        r = s.get("https://passport2.chaoxing.com/cloudscanlogin"
                  f"?mobiletip={tip}&pcrefer={urllib.parse.quote('http://i.chaoxing.com')}", timeout=15)
        m_uuid = (re.search(r'id\s*=\s*"uuid"[^>]*value="([^"]*)"', r.text) or
                  re.search(r'value="([^"]*)"[^>]*id\s*=\s*"uuid"', r.text))
        m_enc = (re.search(r'id\s*=\s*"enc"[^>]*value="([^"]*)"', r.text) or
                 re.search(r'value="([^"]*)"[^>]*id\s*=\s*"enc"', r.text))
        if not m_uuid or not m_enc:
            raise RuntimeError("获取登录二维码失败（页面结构可能已变化）")
        uuid, enc = m_uuid.group(1), m_enc.group(1)
        img = s.get(f"https://passport2.chaoxing.com/createqr?uuid={uuid}&xxtrefer=&type=1"
                    f"&clientid=&mobiletip={tip}", timeout=15)
        return {"session": s, "uuid": uuid, "enc": enc,
                "qr_base64": base64.b64encode(img.content).decode()}

    @staticmethod
    def qr_poll(ctx):
        s, uuid, enc = ctx["session"], ctx["uuid"], ctx["enc"]
        try:
            r = s.post("https://passport2.chaoxing.com/getauthstatus",
                       data={"enc": enc, "uuid": uuid}, timeout=15)
            d = r.json()
        except Exception:
            return {"status": "waiting"}
        if d.get("status") is True:
            client = CxClient(cookies=[{"name": c.name, "value": c.value, "domain": c.domain}
                                       for c in s.cookies])
            client._refresh_ids()
            ok = client.check_valid()
            if not ok or not client.uid:
                return {"status": "failed", "msg": "扫码成功但会话无效，请重试"}
            return {"status": "confirmed", "client": client, "name": client.name}
        mes = d.get("mes", "")
        if "已扫" in mes:
            return {"status": "scanned", "nickname": d.get("nickname", "")}
        if "失效" in mes or d.get("type") == "2":
            return {"status": "expired"}
        if "取消" in mes or d.get("type") == "6":
            return {"status": "canceled"}
        return {"status": "waiting"}

    def get_courses(self):
        r = self.s.get("https://mooc1-api.chaoxing.com/mycourse/backclazzdata?rss=1", timeout=20)
        courses, seen = [], set()
        for ch in r.json().get("channelList", []):
            content = ch.get("content", {}) or {}
            cid = content.get("id")
            if cid is None or "course" not in content:
                continue
            chatid = content.get("chatid", "")
            cls_name = content.get("name", "")
            for c in (content.get("course", {}) or {}).get("data", []):
                key = (str(c["id"]), str(cid))
                if key in seen:
                    continue
                seen.add(key)
                courses.append({"key": f"{key[0]}:{key[1]}", "courseId": key[0],
                                "classId": key[1], "chatid": str(chatid),
                                "courseName": c.get("name", ""), "className": cls_name})
        return courses

    def check_activity(self, course):
        url = (f"{BASE}/v2/apis/active/student/activelist?fid=0"
               f"&courseId={course['courseId']}&classId={course['classId']}"
               f"&_={int(time.time() * 1000)}")
        try:
            data = self.s.get(url, timeout=15).json()
        except Exception:
            return "FREQ"
        # 学习通限频时返回 HTTP 200 + {"result":0,"errorMsg":"请勿频繁操作"}，
        # 必须与「无签到活动」区分，否则监控会静默漏检（用户看不到任何反应）
        if not isinstance(data, dict) or data.get("result") == 0 or data.get("errorMsg"):
            return "FREQ"
        lst = (data.get("data") or {}).get("activeList") or []
        if not lst:
            return None
        now = time.time()
        for a in lst:
            try:
                other_id = int(a.get("otherId", -1))
            except (TypeError, ValueError):
                other_id = -1
            if a.get("status") != 1 or not (0 <= other_id <= 5):
                continue
            start_ms = a.get("startTime", 0) or 0
            if start_ms and now - start_ms / 1000 > 7200:
                continue
            return {"activeId": str(a["id"]), "name": a.get("nameOne", "") or a.get("name", ""),
                    "otherId": other_id, "startTime": start_ms,
                    "courseId": course["courseId"], "classId": course["classId"],
                    "courseName": course["courseName"], "className": course["className"]}
        return None

    def pre_sign(self, act):
        try:
            self.s.get(f"{BASE}/newsign/preSign?courseId={act['courseId']}&classId={act['classId']}"
                       f"&activePrimaryId={act['activeId']}&general=1&sys=1&ls=1&appType=15"
                       f"&&tid=&uid={self.uid}&ut=s", timeout=15)
            r = self.s.get(f"{BASE}/pptSign/analysis?vs=1&DB_STRATEGY=RANDOM&aid={act['activeId']}",
                           timeout=15)
            m = re.search(r"code='\+'([^']*)", r.text)
            if m:
                self.s.get(f"{BASE}/pptSign/analysis2?DB_STRATEGY=RANDOM&code={m.group(1)}",
                           timeout=15)
        except Exception as e:
            log(f"预签到步骤异常(继续提交): {e}", "warn", self.uid)
        time.sleep(0.5)

    def is_photo_sign(self, active_id):
        try:
            r = self.s.get(f"{BASE}/v2/apis/active/getPPTActiveInfo?activeId={active_id}", timeout=15)
            return (r.json().get("data") or {}).get("ifphoto") == 1
        except Exception:
            return False

    def sign_general(self, act, loc=None):
        # 位置签到(otherId=4)启用模拟坐标时，提交指定经纬度与地址；其余类型维持 latitude/longitude=-1
        lat, lng, addr = "-1", "-1", ""
        if act.get("otherId") == 4 and loc:
            lat = (loc.get("lat") or "").strip() or "-1"
            lng = (loc.get("lng") or "").strip() or "-1"
            addr = (loc.get("addr") or "").strip()
        url = (f"{BASE}/pptSign/stuSignajax?activeId={act['activeId']}&uid={self.uid}&clientip="
               f"&latitude={lat}&longitude={lng}&appType=15&fid={self.fid}"
               f"&name={urllib.parse.quote(self.name or '')}")
        if addr:
            url += "&address=" + urllib.parse.quote(addr)
        return self.s.get(url, timeout=15).text

    def check_sign_code(self, act, code):
        # 手势/签到码 提交前的服务端强校验：未校验直接提交会被 90002 拒绝
        self.pre_sign(act)
        try:
            r = self.s.get(f"{BASE}/pptSign/checkSignCode?activeId={act['activeId']}"
                           f"&signCode={urllib.parse.quote(str(code))}&fid={self.fid}&uid={self.uid}",
                           timeout=15)
            return r.text
        except Exception as e:
            return f"校验请求异常: {e}"

    def sign_qr(self, act, enc):
        # 二维码签到：enc 取自二维码 URL（动态刷新，需取最新值）
        self.pre_sign(act)
        loc_json = urllib.parse.quote('{"result":"1","address":""}')
        url = (f"{BASE}/pptSign/stuSignajax?activeId={act['activeId']}&uid={self.uid}&clientip="
               f"&latitude=-1&longitude=-1&appType=15&fid={self.fid}"
               f"&name={urllib.parse.quote(self.name or '')}"
               f"&enc={urllib.parse.quote(str(enc))}&location={loc_json}")
        try:
            return self.s.get(url, timeout=15).text
        except Exception as e:
            return f"二维码签到请求异常: {e}"

    def sign_code(self, act, code):
        # 手势/签到码：先 checkSignCode 校验，再带 signCode 提交
        self.check_sign_code(act, code)
        url = (f"{BASE}/pptSign/stuSignajax?activeId={act['activeId']}&uid={self.uid}&clientip="
               f"&latitude=-1&longitude=-1&appType=15&fid={self.fid}"
               f"&name={urllib.parse.quote(self.name or '')}"
               f"&signCode={urllib.parse.quote(str(code))}")
        try:
            return self.s.get(url, timeout=15).text
        except Exception as e:
            return f"手势/签到码提交异常: {e}"


# ---------------- Server 酱 ----------------

def serverchan_send(key, title, desp):
    if not key:
        return False, "未配置 SendKey"
    try:
        r = requests.get(f"https://sctapi.ftqq.com/{key}.send",
                         params={"title": title, "desp": desp}, timeout=15)
        d = r.json()
        return d.get("code") == 0, d.get("message", "")
    except Exception as e:
        return False, str(e)


def _html_to_text(html):
    t = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    t = re.sub(r"</tr>", "\n", t, flags=re.I)
    t = re.sub(r"</td>", "  ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _email_shell(title, badge, badge_color, body_html):
    """品牌化 HTML 邮件外壳（马上签 · 白蓝主题，表格布局兼容各邮件客户端）。"""
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head>"
        "<body style=\"margin:0;padding:0;background:#eef3fa;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"background:#eef3fa;padding:32px 12px;\">"
        "<tr><td align=\"center\">"
        "<table role=\"presentation\" width=\"480\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"max-width:480px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;"
        "box-shadow:0 8px 28px rgba(22,119,255,0.12);\">"

        # 头部品牌区
        "<tr><td style=\"background:linear-gradient(135deg,#1677ff 0%,#4096ff 100%);padding:26px 28px;\">"
        "<div style=\"font-size:23px;font-weight:800;color:#ffffff;letter-spacing:2px;\">马上签</div>"
        "<div style=\"font-size:12px;color:#dceaff;margin-top:5px;letter-spacing:.5px;\">"
        "超星学习通 · 自动签到提醒</div>"
        "</td></tr>"

        # 标题 + 状态徽标
        "<tr><td style=\"padding:26px 28px 6px 28px;\">"
        f"<span style=\"display:inline-block;background:{badge_color};color:#ffffff;font-size:12px;"
        "font-weight:600;padding:4px 14px;border-radius:20px;letter-spacing:.5px;\">"
        f"{badge}</span>"
        f"<div style=\"font-size:19px;font-weight:700;color:#1f2937;margin-top:14px;line-height:1.4;\">{title}</div>"
        "</td></tr>"

        # 正文
        f"<tr><td style=\"padding:8px 28px 24px 28px;\">{body_html}</td></tr>"

        # 页脚
        "<tr><td style=\"background:#f7f9fc;padding:16px 28px;border-top:1px solid #edf1f7;\">"
        "<div style=\"font-size:12px;color:#9aa5b4;line-height:1.8;\">"
        "本邮件由「马上签」自动发送，请勿直接回复。<br/>"
        "© 2026 马上签 · 仅供学习交流使用</div>"
        "</td></tr>"

        "</table></td></tr></table></body></html>"
    )


def _kv_table(rows):
    ktd = ("<td style=\"padding:9px 0;font-size:13px;color:#8a94a6;width:80px;"
           "vertical-align:top;border-bottom:1px solid #f2f5f9;\">")
    vtd = ("<td style=\"padding:9px 0;font-size:14px;color:#1f2937;font-weight:600;"
           "border-bottom:1px solid #f2f5f9;\">")
    trs = "".join(
        "<tr>" + ktd + (str(k) if k not in (None, "") else "-") + "</td>"
        + vtd + (str(v) if v not in (None, "") else "-") + "</td></tr>"
        for k, v in rows)
    return ("<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
            "style=\"border-collapse:collapse;\">" + trs + "</table>")


def _note(text, color):
    return (f"<div style=\"margin-top:16px;font-size:13px;color:{color};line-height:1.6;\">{text}</div>")


def tpl_sign_success(course, activity, when):
    body = _kv_table([("科目", course), ("活动", activity), ("时间", when)])
    body += _note("✅ 已为你自动完成签到，无需其他操作。", "#389e0d")
    return _email_shell("签到成功提醒", "签到成功", "#52c41a", body)


def tpl_sign_fail(course, activity, when, detail):
    body = _kv_table([("科目", course), ("活动", activity), ("时间", when), ("返回", detail)])
    body += _note("⚠️ 自动签到未成功，请尽快打开学习通 App 手动完成签到！", "#cf1322")
    return _email_shell("自动签到失败", "需要处理", "#ff4d4f", body)


def tpl_manual(type_name, course, activity, when, tip):
    body = _kv_table([("课程", course), ("活动", activity), ("时间", when)])
    body += _note(tip, "#ad6800")
    return _email_shell(f"检测到{type_name}签到", "需手动完成", "#faad14", body)


def tpl_assist(tname, course, activity, link, when):
    if tname == "二维码":
        tip = ("把老师投屏的二维码用手机相机 / 微信「扫一扫」识别，复制那串链接"
               "（或其中的 enc 参数），打开下面的协助链接粘贴提交即可。")
    else:
        tip = ("打开下面的协助链接，在九宫格上画出老师投屏的手势轨迹"
               "（或输入老师公布的签到码），提交即可帮你完成签到。")
    body = _kv_table([("课程", course), ("活动", activity), ("类型", tname), ("时间", when)])
    body += _note(tip, "#1677ff")
    body += (f'<p style="margin:14px 0 4px"><a href="{link}" '
             f'style="display:inline-block;background:#1677ff;color:#fff;'
             f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">'
             f'打开协助链接</a></p>'
             f'<p style="margin:6px 0 0;word-break:break-all;color:#555;font-size:13px">{link}</p>')
    return _email_shell(f"可让同学协助的{tname}签到", "同学帮签", "#1677ff", body)


def tpl_assist_success(course, activity, tname, when):
    body = _kv_table([("课程", course), ("活动", activity), ("类型", tname), ("时间", when)])
    body += _note("✅ 同学已通过协助链接帮你完成签到。", "#389e0d")
    return _email_shell("同学协助签到成功", "签到成功", "#52c41a", body)


def tpl_relogin(account, reason):
    body = _kv_table([("学习通账号", account), ("暂停原因", reason)])
    body += _note("请打开「马上签」页面重新扫码登录，登录后监控会自动恢复。", "#1f2937")
    return _email_shell("监控已暂停 · 请重新登录", "需要重新登录", "#ff4d4f", body)


def tpl_welcome(username):
    body = _kv_table([("用户名", username), ("登录时间", now_str())])
    body += _note("你已成功登录「马上签」。添加学习通账号并开启监控后，"
                  "签到成功 / 失败 / 需手动等结果都会实时通知到此邮箱。", "#1f2937")
    return _email_shell("欢迎使用马上签", "登录成功", "#1677ff", body)


def send_welcome_async(username):
    """登录/注册成功后，后台异步发送欢迎邮件（不阻塞登录请求）。"""
    def _go():
        try:
            u = MGR.site_users.get(username)
            email = getattr(u, "email", "") if u else ""
            if not email:
                return
            ok, err = send_email(email, "🎉 欢迎使用马上签", tpl_welcome(username))
            if not ok:
                log(f"欢迎邮件发送失败[{email}]: {err}", "warn", username)
        except Exception as e:
            log(f"欢迎邮件发送异常: {e}", "warn", username)
    threading.Thread(target=_go, daemon=True).start()


def send_email(to_addr, subject, html_body, text_body=""):
    """通过 QQ 邮箱 SMTP(SSL 465) 发送 HTML 通知邮件（含纯文本兜底）。"""
    to_addr = (to_addr or "").strip()
    if not to_addr:
        return False, "未提供收件邮箱"
    if not SMTP_USER or not SMTP_PASS:
        return False, "未配置 SMTP 账号"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject or "马上签通知", "utf-8")
        msg["From"] = formataddr(("马上签", SMTP_USER))
        msg["To"] = to_addr
        msg.attach(MIMEText(text_body or _html_to_text(html_body), "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [to_addr], msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_notify(username, subject, html, text="", serverchan_key=""):
    """统一通知入口：优先发 QQ 邮件给账号所有者，Server 酱作为可选补充。"""
    try:
        if not SETTINGS.get("email_notify", True):
            return
    except Exception:
        pass
    email = ""
    try:
        u = MGR.site_users.get(username)
        email = getattr(u, "email", "") or ""
    except Exception:
        pass
    if email:
        ok, err = send_email(email, subject, html, text)
        if not ok:
            log(f"QQ邮件通知失败[{email}]: {err}", "warn", username)
    if serverchan_key:
        serverchan_send(serverchan_key, subject, text or _html_to_text(html))
    if not email and not serverchan_key:
        log(f"未绑定QQ邮箱，跳过通知: {subject}", "warn", username)


def send_ticket_notify(subject, content):
    """工单事件邮件提醒：异步发送到 TICKET_NOTIFY_EMAIL，失败仅记日志，不影响工单主流程。"""
    subject = " ".join(str(subject or "").split())[:120] or "马上签工单提醒"

    def _go():
        try:
            ok, err = send_email(TICKET_NOTIFY_EMAIL, f"【马上签】{subject}",
                                 email_page("工单提醒", content))
            if not ok:
                log(f"工单提醒邮件发送失败[{TICKET_NOTIFY_EMAIL}]: {err}", "warn")
            else:
                log(f"工单提醒邮件已发送[{TICKET_NOTIFY_EMAIL}]: {subject}", "info")
        except Exception as e:
            log(f"工单提醒邮件发送异常: {e}", "warn")
    threading.Thread(target=_go, daemon=True).start()


# ---------------- 单条学习通账号 ----------------

def email_page(title, content):
    """把纯文本正文包装成马上签品牌 HTML 邮件（按 \\n 分段）"""
    import html as _html
    body = "".join(
        '<p style="margin:0 0 14px;font-size:14px;line-height:1.8;color:#4a4f59;">%s</p>'
        % (_html.escape(line) if line.strip() else "&nbsp;")
        for line in (content or "").split("\n"))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f5f6fa;font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:32px 20px;">
  <div style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);">
    <div style="background:linear-gradient(135deg,#e7452a,#ff7a45);padding:28px 32px;">
      <div style="color:#fff;font-size:22px;font-weight:600;">马上签 · 系统通知</div>
      <div style="color:rgba(255,255,255,.85);font-size:13px;margin-top:6px;">超星学习通自动签到</div>
    </div>
    <div style="padding:28px 32px;">
      <h2 style="margin:0 0 16px;font-size:18px;color:#1f2329;">{_html.escape(title or "系统通知")}</h2>
      {body}
    </div>
    <div style="padding:16px 32px;background:#fafbfc;border-top:1px solid #f0f0f0;font-size:12px;color:#9aa0ab;line-height:1.7;">
      本邮件由系统自动发送，请勿直接回复。如有疑问请访问
      <a href="https://xxt.leich.cn" style="color:#e7452a;text-decoration:none;">xxt.leich.cn</a> 查看站内公告。
    </div>
  </div>
</div>
</body>
</html>"""


# 后台邮件群发内置模板（id / 名称 / 主题 / 正文，正文为纯文本，\\n 分段）
EMAIL_TEMPLATES = [
    {
        "id": "maintenance",
        "name": "系统维护公告",
        "subject": "【马上签】系统维护公告：建议重新登录",
        "content": "尊敬的用户，您好：\n\n为给大家带来更完善的签到体验，我们正在对服务器进行升级维护，期间可能出现短暂不稳定。\n\n若您遇到登录异常、页面打不开或签到监控不及时等情况，请退出当前账号后重新登录一次，即可恢复正常使用。\n\n给您带来不便深表歉意，感谢您的理解与支持！\n\n—— 马上签团队",
    },
    {
        "id": "feature",
        "name": "新功能上线",
        "subject": "【马上签】新功能上线通知",
        "content": "尊敬的用户，您好：\n\n我们很高兴地通知您，马上签已完成新一轮功能更新：\n\n· 消息中心：签到结果、公告、工单回复一站查看\n· 立即检查：一键手动检测是否有新签到\n· 位置模拟签到：支持配置常用签到坐标\n\n欢迎登录 https://xxt.leich.cn 体验，如有问题请通过站内工单反馈。\n\n—— 马上签团队",
    },
    {
        "id": "abnormal",
        "name": "账号异常提醒",
        "subject": "【马上签】账号异常提醒",
        "content": "尊敬的用户，您好：\n\n我们检测到您的账号存在异常（学习通登录态可能已过期），自动签到监控已暂停。\n\n请尽快登录 https://xxt.leich.cn，在「我的账号」中退出该学习通账号并重新扫码登录，以恢复自动签到。\n\n—— 马上签团队",
    },
    {
        "id": "inactive",
        "name": "监控未开启提醒",
        "subject": "【马上签】提醒：签到监控未开启",
        "content": "尊敬的用户，您好：\n\n我们注意到您的部分学习通账号未开启自动签到监控，课程有签到时将无法自动完成。\n\n请登录 https://xxt.leich.cn，在「我的账号」中打开对应账号的监控开关。\n\n—— 马上签团队",
    },
    {
        "id": "custom",
        "name": "自定义",
        "subject": "",
        "content": "",
    },
]


def _sign_message(rec):
    """把签到记录转换成消息中心的 (标题, 正文)"""
    result = rec.get("result", "")
    activity = rec.get("activity", "") or "签到活动"
    course = rec.get("course", "") or "未知课程"
    if result == "success":
        title = f"签到成功：{activity}"
    elif result == "manual":
        title = f"需手动签到：{activity}"
    else:
        title = f"签到失败：{activity}"
    content = (f"课程：{course}\n活动：{activity}\n类型：{rec.get('type', '')}\n"
               f"结果：{rec.get('detail', '')}\n时间：{rec.get('time', '')}")
    return title, content


class ChaoxingAccount:
    """一个学习通账号 = 一个 ChaoxingAccount（独立登录态 / 配置 / 监控线程）"""

    def __init__(self, acct_id, owner=""):
        self.acct_id = str(acct_id)
        self.owner = owner
        self.lock = threading.RLock()
        self.client = None
        self.name = ""
        self.fid = ""
        self.dir = os.path.join(ACCOUNTS_DIR, self.acct_id)
        cfg = load_json(self.cfg_path, {})
        cfg.setdefault("owner", owner)
        self.config = dict(DEFAULT_CONFIG, **cfg)
        self.records = load_json(self.rec_path, [])
        self.processed = set(load_json(self.st_path, {}).get("processed", []))
        self.monitoring = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
        self.last_check = 0.0
        self.last_manual_check = 0.0   # 上次手动「立即检查」的时间戳（冷却用）
        self.monitor_rounds = 0
        self.monitor_errors = 0
        self.checking = False
        self._courses_cache = []
        self.assist_pending = {}   # activeId -> 待协助签到（二维码/手势/签到码）

    @property
    def cfg_path(self): return os.path.join(self.dir, "config.json")
    @property
    def rec_path(self): return os.path.join(self.dir, "records.json")
    @property
    def st_path(self):  return os.path.join(self.dir, "state.json")
    @property
    def ck_path(self):  return os.path.join(self.dir, "cookies.json")

    def save_config(self):
        self.config["owner"] = self.owner
        save_json(self.cfg_path, self.config)

    def logged_in(self):
        return self.client is not None

    # ---- 登录 ----
    def adopt_client(self, client):
        with self.lock:
            self.client = client
            self.name = client.name or ""
            self.fid = client.fid or ""
            self.config["need_relogin"] = False
            self.save_config()
            save_json(self.ck_path, client.cookies_list())
        log(f"登录成功: {self.name or self.acct_id} (owner={self.owner}, fid={self.fid})",
            "info", self.owner)
        try:
            self.refresh_courses()
            log(f"已获取课程列表, 共 {len(self.courses())} 门", "info", self.owner)
        except Exception as e:
            log(f"获取课程列表失败: {e}", "warn", self.owner)

    def restore_login(self):
        cookies = load_json(self.ck_path, [])
        if not cookies:
            return False
        client = CxClient(cookies)
        if client.check_valid():
            client._refresh_ids()
            self.adopt_client(client)
            log("已从本地恢复登录态", "info", self.owner)
            return True
        log("本地 cookie 已失效, 需重新登录", "warn", self.owner)
        try:
            os.remove(self.ck_path)
        except OSError:
            pass
        return False

    def logout(self):
        with self.lock:
            self.stop_monitor(persist=True)
            self.client = None
            self.name = ""
            try:
                os.remove(self.ck_path)
            except OSError:
                pass
        log("已退出登录", "info", self.owner)

    # ---- 课程 ----
    def courses(self):
        return self._courses_cache

    def refresh_courses(self):
        with self.lock:
            client = self.client
        if not client:
            return []
        courses = client.get_courses()
        self._courses_cache = courses
        return courses

    def enabled_courses(self):
        courses = self.courses()
        enabled = self.config.get("enabled_courses") or []
        if not enabled:
            return courses
        allow = set(enabled)
        return [c for c in courses if c["key"] in allow]

    # ---- 记录 ----
    def add_record(self, rec):
        with self.lock:
            rec["time"] = now_str()
            self.records.insert(0, rec)
            self.records = self.records[:200]
            save_json(self.rec_path, self.records)
        # 同步生成站内消息（消息中心展示）；失败不影响签到主流程
        try:
            MESSAGES.create(self.owner, "sign", *_sign_message(rec))
        except Exception:
            pass

    def remember_processed(self, active_id):
        with self.lock:
            self.processed.add(str(active_id))
            if len(self.processed) > 500:
                self.processed = set(sorted(self.processed)[-500:])
            save_json(self.st_path, {"processed": list(self.processed)})

    # ---- 协助签到（同学帮签）----
    def enqueue_assist(self, act, tname, course_label):
        aid = str(act["activeId"])
        with self.lock:
            self.assist_pending[aid] = {
                "act": {"activeId": aid, "courseId": act.get("courseId"),
                        "classId": act.get("classId"), "name": act.get("name"),
                        "courseName": act.get("courseName"), "className": act.get("className"),
                        "otherId": act.get("otherId")},
                "type": act.get("otherId"), "tname": tname,
                "course": course_label, "activity": act.get("name", ""),
                "expires": time.time() + 1800,   # 待协助保留 30 分钟
            }

    def assist_pending_list(self):
        now = time.time()
        out = []
        for aid, p in list(self.assist_pending.items()):
            if p.get("expires", 0) <= now:
                with self.lock:
                    self.assist_pending.pop(aid, None)
                continue
            out.append({
                "active_id": aid, "tname": p["tname"], "type": p["type"],
                "course": p["course"], "activity": p["activity"],
                "expires_in": int(p["expires"] - now),
                "kind": "qr" if p["type"] == 2 else "code",
            })
        return out

    def assist_submit(self, active_id, value):
        """同学通过协助链接提交 enc（二维码）或手势/签到码（手势/签到码）。"""
        aid = str(active_id)
        with self.lock:
            ap = self.assist_pending.get(aid)
        if not ap:
            return False, "该签到不在待协助列表中（可能已过期或已完成）"
        if not self.client:
            return False, "账号未登录，无法代签"
        value = (value or "").strip()
        if not value:
            return False, "未提供 enc / 手势轨迹"
        act = ap["act"]
        try:
            if ap["type"] == 2:
                resp = self.client.sign_qr(act, value)
            else:
                resp = self.client.sign_code(act, value)
        except Exception as e:
            resp = f"请求异常: {e}"
        low = resp.lower()
        ok = ("success" in low) or ("您已签到过了" in resp) or ("已签到" in resp) or ("签到成功" in resp)
        detail = "签到成功" if ok else f"返回: {resp[:120]}"
        self.add_record({"course": ap["course"], "activity": ap["activity"], "type": ap["tname"],
                         "result": "success" if ok else "fail", "detail": detail})
        self.remember_processed(aid)
        with self.lock:
            self.assist_pending.pop(aid, None)
        if ok:
            send_notify(self.owner, "🤝 同学已协助签到成功",
                        tpl_assist_success(ap["course"], ap["activity"], ap["tname"], now_str()),
                        serverchan_key=self.config.get("serverchan_key", ""))
        return ok, detail

    # ---- 监控 ----
    def effective_interval(self):
        """监控间隔自适应：课程越多间隔越长，降低被学习通限频的概率。
        公式：max(60, 课程数×2)；用户配置只能调更长，不能短于该安全下限
        （历史上 40 门课 × 20s 的高密度轮询正是触发账号级限频的直接原因）。"""
        n = len(self.enabled_courses())
        auto = max(60, n * 2)
        try:
            user = int(self.config.get("interval", 45))
        except (TypeError, ValueError):
            user = 45
        return max(auto, user)

    def start_monitor(self):
        with self.lock:
            if self.monitoring:
                return
            if not self.client:
                log("尚未登录, 无法开始监控", "warn", self.owner)
                return
            self.monitoring = True
            self.config["monitor_on"] = True
            self.config["freq_cooldown_until"] = 0   # 显式开启 = 解除自动冷却
            self.config["need_relogin"] = False
            self.save_config()
            self.stop_event.clear()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
        log(f"监控已开启, 每 {self.effective_interval()} 秒检测一次 "
            f"({len(self.enabled_courses())} 门课程)", "info", self.owner)

    def stop_monitor(self, persist=True):
        with self.lock:
            if persist:
                self.config["monitor_on"] = False
                self.save_config()
            if not self.monitoring:
                return
            self.monitoring = False
            self.stop_event.set()
        log("监控已停止", "info", self.owner)

    def monitor_thread_alive(self):
        t = self.monitor_thread
        return bool(t and t.is_alive())

    def _monitor_loop(self):
        freq_streak = 0        # 连续「有任何课程受限」的轮数（轻度退避用）
        heavy_streak = 0       # 连续「大面积受限」的轮数（触发自动冷却）
        last_valid_check = 0.0
        last_course_refresh = 0.0
        round_no = 0
        while not self.stop_event.is_set():
            round_no += 1
            self.monitor_rounds = round_no
            try:
                now = time.time()
                # 定期自动刷新课程列表，使学生新加入的课程也能被监控到
                if now - last_course_refresh > 600:
                    last_course_refresh = now
                    try:
                        n = len(self.refresh_courses())
                        if round_no > 1:
                            log(f"已自动刷新课程列表, 共 {n} 门", "info", self.owner)
                    except Exception as e:
                        log(f"刷新课程列表失败: {e}", "warn", self.owner)
                if now - last_valid_check > 600:
                    last_valid_check = now
                    client = self.client
                    if client is None:
                        log("登录态已丢失, 监控暂停, 请重新登录", "error", self.owner)
                        self._alert_login_expired("登录态丢失")
                        return
                    try:
                        alive = client.check_valid()
                    except Exception as e:
                        alive = False
                        log(f"校验登录态出错(网络抖动): {e}", "warn", self.owner)
                    if not alive:
                        log("登录态已失效(Cookie 过期), 监控暂停, 请重新扫码登录",
                            "error", self.owner)
                        self._alert_login_expired("登录态过期")
                        return

                courses = self.enabled_courses()
                if not courses and (round_no == 1 or round_no % 20 == 0):
                    log("没有可监控的课程, 请在面板勾选课程或点刷新列表", "warn", self.owner)
                # 课程越多请求越密：>20 门时加大课间间隔，降低被学习通限频的概率
                course_sleep = 0.8 if len(courses) <= 20 else 1.5
                freq_this_round = False
                freq_count = 0
                for c in courses:
                    if self.stop_event.is_set():
                        return
                    try:
                        act = self.client.check_activity(c)
                        self.last_check = time.time()
                        if act == "FREQ":
                            freq_this_round = True
                            freq_count += 1
                            continue
                        if act and str(act["activeId"]) not in self.processed:
                            self._handle_activity(act)
                    except Exception as e:
                        log(f"检测课程 [{c.get('courseName','')}] 出错: "
                            f"{type(e).__name__}: {e}", "warn", self.owner)
                    time.sleep(course_sleep)

                if freq_this_round:
                    freq_streak += 1
                    if freq_streak >= 3:
                        log(f"接口被限频(请勿频繁操作): 本轮 {freq_count}/{len(courses)} 门课程受限, "
                            f"已自动降低检测频率", "warn", self.owner)
                else:
                    freq_streak = 0

                # 大面积受限（>=50% 且至少 2 门）：连续 2 轮即进入自动冷却，
                # 停机静默 15 分钟让学习通解除账号级限频，到点由看门狗自动恢复
                if freq_this_round and freq_count >= max(2, int(len(courses) * 0.5)):
                    heavy_streak += 1
                else:
                    heavy_streak = 0
                if heavy_streak >= 2:
                    with self.lock:
                        self.config["monitor_on"] = False
                        self.config["freq_cooldown_until"] = time.time() + 900
                        self.save_config()
                        self.monitoring = False
                        self.stop_event.set()
                    log(f"连续 {heavy_streak} 轮大面积被限频（本轮 {freq_count}/{len(courses)} 门受限），"
                        f"已停机进入自动冷却，15 分钟后自动恢复监控", "warn", self.owner)
                    return

                if round_no % 10 == 0:
                    log(f"监控心跳正常 (第 {round_no} 轮)", "info", self.owner)

                # 间隔自适应 + 轻度退避 + ±20% 抖动（防止多账号轮询周期同步）
                wait = self.effective_interval()
                if freq_streak >= 3:
                    wait = min(wait * 2, 300)
                wait *= random.uniform(0.8, 1.2)
                for _ in range(int(wait * 10)):
                    if self.stop_event.is_set():
                        return
                    time.sleep(0.1)
            except Exception as e:
                log(f"监控主循环异常, 5 秒后自动恢复: {type(e).__name__}: {e}",
                    "error", self.owner)
                self.monitor_errors += 1
                for _ in range(50):
                    if self.stop_event.is_set():
                        return
                    time.sleep(0.1)

    def _alert_login_expired(self, reason):
        with self.lock:
            self.monitoring = False
            self.config["monitor_on"] = True
            self.config["need_relogin"] = True
            self.save_config()
        send_notify(self.owner,
                    "⚠️ 学习通签到监控已暂停 - 请重新登录",
                    tpl_relogin(self.name or self.acct_id,
                                f"{reason}（Cookie 通常 30 天过期）"),
                    serverchan_key=self.config.get("serverchan_key", ""))

    def check_now(self):
        """用户/管理员手动触发一轮完整检测：先验证学习通登录态，再扫描全部启用课程。
        同一账号两次手动检查之间至少间隔 MANUAL_CHECK_COOLDOWN 秒（防连点触发限频）。
        同步执行并返回结构化结果 dict:
          {"ok": bool,            # 本次检查是否顺利跑完
           "login_ok": bool,      # 学习通登录态是否有效
           "checked": int,        # 实际扫描的课程数
           "found": [ {...} ],    # 本次新检测到并处理的签到活动（含处理结果）
           "need_relogin": bool,  # 是否需要重新登录
           "retry_after": int,    # 冷却剩余秒数（被限频时）/ 下次可检查间隔（成功时）
           "msg": str}            # 面向用户的结论
        found 项字段: course / activity / type / result / detail
        """
        if self.checking:
            return {"ok": False, "login_ok": None, "checked": 0, "found": [],
                    "msg": "已有一次检查正在进行中，请稍候再试"}
        since = time.time() - self.last_manual_check
        if 0 < since < MANUAL_CHECK_COOLDOWN:
            wait = int(MANUAL_CHECK_COOLDOWN - since) + 1
            return {"ok": False, "login_ok": None, "checked": 0, "found": [],
                    "need_relogin": False, "retry_after": wait,
                    "msg": f"检查太频繁啦，请 {wait} 秒后再试"
                           f"（频繁刷新可能触发学习通风控）"}
        if self.client is None:
            return {"ok": False, "login_ok": False, "checked": 0, "found": [],
                    "need_relogin": True, "msg": "账号未登录，无法检查（请先扫码登录）"}
        self.last_manual_check = time.time()
        self.checking = True
        try:
            # 1) 先验证学习通登录态（Cookie 可能已过期，监控线程每 10 分钟才查一次）
            try:
                alive = self.client.check_valid()
            except Exception as e:
                alive = False
                log(f"手动检查: 校验登录态出错(网络抖动): {e}", "warn", self.owner)
            if not alive:
                self._alert_login_expired("登录态已失效")
                return {"ok": False, "login_ok": False, "checked": 0, "found": [],
                        "need_relogin": True,
                        "msg": "学习通登录态已失效，请退出后重新扫码登录"}
            with self.lock:
                if self.config.get("need_relogin"):
                    self.config["need_relogin"] = False
                    self.save_config()

            # 2) 扫描全部启用课程（不受监控线程 stop_event 影响，做完整一轮）
            courses = self.enabled_courses()
            if not courses:
                try:
                    self.refresh_courses()
                    courses = self.enabled_courses()
                except Exception:
                    pass
            found, acts_found = [], 0
            freq_courses = 0
            for c in courses:
                try:
                    act = self.client.check_activity(c)
                    self.last_check = time.time()
                    if act == "FREQ":
                        freq_courses += 1
                        continue
                    if act and str(act["activeId"]) not in self.processed:
                        before_ids = {id(r) for r in self.records}
                        self._handle_activity(act)
                        for r in self.records:
                            if id(r) not in before_ids:
                                found.append({"course": r.get("course", ""),
                                              "activity": r.get("activity", ""),
                                              "type": r.get("type", ""),
                                              "result": r.get("result", ""),
                                              "detail": r.get("detail", "")})
                        acts_found += 1
                except Exception as e:
                    log(f"手动检查课程 [{c.get('courseName','')}] 出错: "
                        f"{type(e).__name__}: {e}", "warn", self.owner)
                time.sleep(0.5)
            if acts_found:
                msg = f"检查完成：已扫描 {len(courses)} 门课程，新签到 {acts_found} 个"
            elif courses and freq_courses == len(courses):
                log("手动检查: 学习通接口全部返回限频(请勿频繁操作)", "warn", self.owner)
                return {"ok": False, "login_ok": True, "checked": len(courses), "found": [],
                        "need_relogin": False,
                        "msg": "学习通接口被限频（请勿频繁操作），本次未能检测，请 10 分钟后再试"}
            elif freq_courses:
                msg = (f"检查完成：已扫描 {len(courses)} 门课程，暂无新签到"
                       f"（其中 {freq_courses} 门被限频未检测）")
            else:
                msg = f"检查完成：已扫描 {len(courses)} 门课程，暂无新签到"
            log(f"手动检查完成, 共检测 {len(courses)} 门课程, 新活动 {acts_found} 个",
                "info", self.owner)
            return {"ok": True, "login_ok": True, "checked": len(courses),
                    "found": found, "need_relogin": False, "msg": msg,
                    "retry_after": MANUAL_CHECK_COOLDOWN}
        finally:
            self.checking = False

    def _handle_activity(self, act):
        if str(act["activeId"]) in self.processed:
            return
        other_id = act["otherId"]
        tname = SIGN_TYPES.get(other_id, "未知")
        course_label = act["courseName"] + (f"({act['className']})" if act["className"] else "")
        log(f"检测到签到活动: [{tname}] {act['name']} @ {course_label}", "alert", self.owner)

        # 二维码 / 手势 / 签到码：无法本地自动完成，进入「待协助」队列，由同学扫码/画手势帮忙
        if other_id in (2, 3, 5):
            aid = str(act["activeId"])
            with self.lock:
                existing = self.assist_pending.get(aid)
            if existing and existing.get("expires", 0) > time.time():
                return  # 已通知过，等待同学协助，避免每轮重复推送
            token = get_token_for(self.acct_id) or set_token_for(self.acct_id)
            self.enqueue_assist(act, tname, course_label)
            link = f"{SITE_BASE}/assist/{token}"
            log(f"[待协助] {tname} 签到已入队，协助链接 {link}", "alert", self.owner)
            send_notify(self.owner, f"🤝 检测到{tname}签到，可让同学协助",
                        tpl_assist(tname, course_label, act["name"], link, now_str()),
                        serverchan_key=self.config.get("serverchan_key", ""))
            return

        # 普通签到可能要求拍照 -> 归为手动
        if other_id == 0 and self.client.is_photo_sign(act["activeId"]):
            log("该普通签到要求拍照, 归为需手动完成", "alert", self.owner)
            self.add_record({"course": course_label, "activity": act["name"], "type": "拍照",
                             "result": "manual", "detail": "拍照签到需手动完成，已推送提醒"})
            self.remember_processed(act["activeId"])
            send_notify(self.owner, "📸 学习通拍照签到 - 请手动完成",
                        tpl_manual("拍照", course_label, act["name"], now_str(),
                                   "拍照签到需相机完成，请打开学习通 App 手动签到。"),
                        serverchan_key=self.config.get("serverchan_key", ""))
            return

        # 自动签到（普通 / 手势 / 位置 / 签到码）
        loc = None
        if self.config.get("loc_enabled"):
            loc = {"lat": str(self.config.get("loc_lat") or "").strip(),
                   "lng": str(self.config.get("loc_lng") or "").strip(),
                   "addr": str(self.config.get("loc_addr") or "").strip()}
        self.client.pre_sign(act)
        try:
            resp = self.client.sign_general(act, loc=loc)
        except Exception as e:
            resp = f"请求异常: {e}"
        low = resp.lower()
        already = ("您已签到过了" in resp) or ("已签到" in resp)
        ok = ("success" in low) or already or ("签到成功" in resp)
        if "success" in low or "签到成功" in resp:
            detail = "签到成功"
        elif already:
            detail = "已签到(重复或已手动完成)"
        else:
            detail = f"返回: {resp[:120]}"
        log(f"自动签到{'成功' if ok else '失败'}: {'' if ok else resp[:80]}",
            "info" if ok else "error", self.owner)
        self.add_record({"course": course_label, "activity": act["name"], "type": tname,
                         "result": "success" if ok else "fail", "detail": detail})
        self.remember_processed(act["activeId"])
        if ok:
            send_notify(self.owner, "✅ 学习通自动签到成功",
                        tpl_sign_success(course_label, act["name"], now_str()),
                        serverchan_key=self.config.get("serverchan_key", ""))
        else:
            send_notify(self.owner, "❌ 学习通自动签到失败",
                        tpl_sign_fail(course_label, act["name"], now_str(), resp[:200]),
                        serverchan_key=self.config.get("serverchan_key", ""))

    def summary(self):
        today = datetime.now().strftime("%m-%d")
        manual_today = sum(1 for r in self.records
                           if r.get("result") == "manual" and str(r.get("time", "")).startswith(today))
        cd_until = self.config.get("freq_cooldown_until", 0) or 0
        cd_left = max(0, int(cd_until - time.time())) if cd_until > time.time() else 0
        return {"acct_id": self.acct_id, "owner": self.owner, "name": self.name,
                "logged_in": self.client is not None, "monitoring": self.monitoring,
                "monitor_alive": self.monitor_thread_alive(), "last_check": self.last_check,
                "rounds": self.monitor_rounds, "errors": self.monitor_errors,
                "courses": len(self.courses()), "records": len(self.records),
                "manual_today": manual_today,
                "interval": self.effective_interval(),
                "freq_cooldown": cd_left,
                "assist_pending": len([p for p in self.assist_pending.values()
                                       if p.get("expires", 0) > time.time()]),
                "assist_link": f"{SITE_BASE}/assist/{get_token_for(self.acct_id) or ''}",
                "need_relogin": bool(self.config.get("need_relogin", False))}


# ---------------- 网站账号（站点登录层） ----------------

class SiteUser:
    def __init__(self, username, pw_hash, salt, role="user", created_at=None, disabled=False, email=""):
        self.username = username
        self.pw_hash = pw_hash
        self.salt = salt
        self.role = role if role in ("admin", "user") else "user"
        self.created_at = created_at or now_iso()
        self.disabled = bool(disabled)
        self.email = (email or "").strip()

    def check_password(self, pw):
        dk, _ = hash_password(pw, self.salt)
        return dk == self.pw_hash

    def to_dict(self):
        return {"username": self.username, "pw_hash": self.pw_hash, "salt": self.salt,
                "role": self.role, "created_at": self.created_at, "disabled": self.disabled,
                "email": self.email}

    def to_public(self):
        return {"username": self.username, "role": self.role, "created_at": self.created_at,
                "disabled": self.disabled, "email": self.email}


class SiteUserStore:
    def __init__(self):
        self.path = SITE_USERS_FILE
        self.lock = threading.RLock()
        self.users = {}
        self._load()

    def _load(self):
        data = load_json(self.path, {})
        for u in data.get("users", []):
            try:
                self.users[u["username"]] = SiteUser(
                    u["username"], u["pw_hash"], u["salt"],
                    u.get("role", "user"), u.get("created_at"), u.get("disabled", False),
                    u.get("email", ""))
            except Exception:
                pass

    def _save(self):
        save_json(self.path, {"users": [u.to_dict() for u in self.users.values()]})

    def ensure_admin(self):
        with self.lock:
            if ADMIN_USERNAME not in self.users:
                h, s = hash_password(ADMIN_PASSWORD)
                self.users[ADMIN_USERNAME] = SiteUser(ADMIN_USERNAME, h, s, "admin", email=SMTP_USER)
                self._save()
                log(f"已创建管理员账号 {ADMIN_USERNAME}", "info")
            else:
                u = self.users[ADMIN_USERNAME]
                changed = False
                if not u.check_password(ADMIN_PASSWORD):
                    h, s = hash_password(ADMIN_PASSWORD)
                    u.pw_hash, u.salt = h, s
                    changed = True
                if not u.email:
                    u.email = SMTP_USER
                    changed = True
                if changed:
                    self._save()
                    log("已重置管理员账号密码", "info")

    def register(self, username, password, role="user", email=""):
        username = (username or "").strip()
        email = (email or "").strip()
        if not username or not password:
            return False, "用户名和密码不能为空"
        if len(username) < 2 or len(username) > 32:
            return False, "用户名长度需为 2-32"
        if not username.isalnum() and "_" not in username and "-" not in username:
            return False, "用户名只能包含字母、数字、_ 或 -"
        if email and not is_valid_email(email):
            return False, "邮箱格式不正确"
        with self.lock:
            if username in self.users:
                return False, "该用户名已存在"
            h, s = hash_password(password)
            self.users[username] = SiteUser(username, h, s, role, email=email)
            self._save()
        return True, ""

    def update_profile(self, username, email=None, new_password=None):
        with self.lock:
            u = self.users.get((username or "").strip())
            if not u:
                return False, "用户不存在"
            if email is not None:
                email = (email or "").strip()
                if email and not is_valid_email(email):
                    return False, "邮箱格式不正确"
                u.email = email
            if new_password:
                if len(new_password) < 6:
                    return False, "新密码至少 6 位"
                h, s = hash_password(new_password)
                u.pw_hash, u.salt = h, s
            self._save()
        return True, ""

    def admin_update(self, username, email=None, new_password=None, role=None):
        """管理员编辑用户：邮箱 / 重置密码 / 角色"""
        with self.lock:
            u = self.users.get((username or "").strip())
            if not u:
                return False, "用户不存在"
            if email is not None:
                email = (email or "").strip()
                if email and not is_valid_email(email):
                    return False, "邮箱格式不正确"
                u.email = email
            if new_password:
                if len(new_password) < 6:
                    return False, "密码至少 6 位"
                h, s = hash_password(new_password)
                u.pw_hash, u.salt = h, s
            if role is not None:
                if role not in ("admin", "user"):
                    return False, "角色只能是 admin 或 user"
                if u.username == ADMIN_USERNAME and role != "admin":
                    return False, "不能取消内置管理员的管理员角色"
                u.role = role
            self._save()
        return True, ""

    def authenticate(self, username, password):
        u = self.users.get((username or "").strip())
        if not u or u.disabled:
            return None
        if u.check_password(password):
            return u
        return None

    def get(self, username):
        return self.users.get((username or "").strip())

    def list(self):
        return [u.to_public() for u in self.users.values()]

    def set_disabled(self, username, disabled):
        with self.lock:
            u = self.users.get(username)
            if not u:
                return False
            u.disabled = bool(disabled)
            self._save()
        return True

    def delete(self, username):
        with self.lock:
            if username == ADMIN_USERNAME:
                return False
            self.users.pop(username, None)
            self._save()
        return True


# ---------------- 工单 / 反馈系统 ----------------

class TicketStore:
    STATUS_OPEN = "open"
    STATUS_PROGRESS = "in_progress"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUSES = [STATUS_OPEN, STATUS_PROGRESS, STATUS_RESOLVED, STATUS_CLOSED]
    CATEGORIES = ["bug", "feature", "question", "other"]
    PRIORITIES = ["low", "normal", "high"]

    LABEL_STATUS = {"open": "待处理", "in_progress": "处理中",
                    "resolved": "已解决", "closed": "已关闭"}
    LABEL_CATEGORY = {"bug": "故障/BUG", "feature": "功能建议",
                      "question": "使用咨询", "other": "其他"}
    LABEL_PRIORITY = {"low": "低", "normal": "普通", "high": "高"}

    def __init__(self):
        self.path = TICKETS_FILE
        self.lock = threading.RLock()
        self.tickets = []
        self.seq = 0
        self._load()

    def _load(self):
        data = load_json(self.path, {"seq": 0, "tickets": []})
        self.seq = data.get("seq", 0)
        self.tickets = data.get("tickets", [])

    def _save(self):
        save_json(self.path, {"seq": self.seq, "tickets": self.tickets})

    def _next_id(self):
        self.seq += 1
        return self.seq

    def create(self, uid, subject, content, category="other"):
        category = category if category in self.CATEGORIES else "other"
        subject = (subject or "").strip()
        content = (content or "").strip()
        if not subject or not content:
            return None, "标题和内容不能为空"
        with self.lock:
            tid = self._next_id()
            t = {
                "id": tid, "uid": uid, "subject": subject, "content": content,
                "category": category, "status": self.STATUS_OPEN, "priority": "normal",
                "created_at": now_iso(), "updated_at": now_iso(), "replies": [],
            }
            self.tickets.append(t)
            self._save()
        log(f"用户 {uid} 提交工单 #{tid}: {subject}", "info", uid)
        send_ticket_notify(
            f"新工单 #{tid}：{subject}",
            f"用户 {uid} 提交了新工单，请及时处理。\n\n"
            f"工单编号：#{tid}\n"
            f"问题类型：{self.LABEL_CATEGORY.get(category, category)}\n"
            f"提交时间：{t['created_at']}\n\n"
            f"工单内容：\n{content}\n\n"
            f"后台处理入口：{SITE_BASE}/admin")
        return t, ""

    def get(self, tid):
        with self.lock:
            for t in self.tickets:
                if t["id"] == int(tid):
                    return t
        return None

    def list_by_uid(self, uid):
        with self.lock:
            return [t for t in self.tickets if t["uid"] == uid]

    def list_all(self, status=None, uid=None):
        with self.lock:
            res = self.tickets
            if status:
                res = [t for t in res if t["status"] == status]
            if uid:
                res = [t for t in res if t["uid"] == uid]
            return res

    def reply(self, tid, message, from_uid, role):
        message = (message or "").strip()
        if not message:
            return False, "回复内容不能为空"
        with self.lock:
            t = self.get(tid)
            if not t:
                return False, "工单不存在"
            t["replies"].append({
                "from": from_uid, "role": role, "message": message,
                "time": now_iso(),
            })
            t["updated_at"] = now_iso()
            if role == "admin" and t["status"] == self.STATUS_OPEN:
                t["status"] = self.STATUS_PROGRESS
            self._save()
        if role == "user":
            send_ticket_notify(
                f"工单 #{tid} 有新回复",
                f"用户 {from_uid} 回复了工单「{t['subject']}」，请及时查看。\n\n"
                f"工单编号：#{tid}\n"
                f"回复时间：{t['updated_at']}\n\n"
                f"回复内容：\n{message}\n\n"
                f"后台处理入口：{SITE_BASE}/admin")
        return True, ""

    def set_status(self, tid, status=None, priority=None):
        with self.lock:
            t = self.get(tid)
            if not t:
                return False, "工单不存在"
            if status and status in self.STATUSES:
                t["status"] = status
            if priority and priority in self.PRIORITIES:
                t["priority"] = priority
            t["updated_at"] = now_iso()
            self._save()
        return True, ""

    def delete(self, tid):
        with self.lock:
            before = len(self.tickets)
            self.tickets = [t for t in self.tickets if t["id"] != int(tid)]
            if len(self.tickets) != before:
                self._save()
                return True
            return False

    @staticmethod
    def summary(t):
        return {
            "id": t["id"], "uid": t["uid"], "subject": t["subject"],
            "category": t["category"], "category_label": TicketStore.LABEL_CATEGORY.get(t["category"], t["category"]),
            "status": t["status"], "status_label": TicketStore.LABEL_STATUS.get(t["status"], t["status"]),
            "priority": t["priority"], "priority_label": TicketStore.LABEL_PRIORITY.get(t["priority"], t["priority"]),
            "created_at": t["created_at"], "updated_at": t["updated_at"],
            "reply_count": len(t["replies"]),
        }

    @staticmethod
    def detail(t, include_content=True):
        d = TicketStore.summary(t)
        if include_content:
            d["content"] = t["content"]
            d["replies"] = t["replies"]
        return d


# ---------------- 全局应用管理器 ----------------

class App:
    def __init__(self):
        self.lock = threading.RLock()
        self.site_users = SiteUserStore()
        self.accounts = {}
        self.qr_sessions = {}
        self.started_at = time.time()

    # ---- 站点账号 ----
    def ensure_admin(self):
        self.site_users.ensure_admin()

    # ---- 学习通账号 ----
    def get_account(self, acct_id):
        with self.lock:
            return self.accounts.get(str(acct_id))

    def get_or_create_account(self, owner, acct_id):
        with self.lock:
            a = self.accounts.get(str(acct_id))
            if not a:
                a = ChaoxingAccount(acct_id, owner)
                self.accounts[str(acct_id)] = a
            return a

    def add_account(self, owner, client):
        acct_id = str(client.uid)
        with self.lock:
            a = self.accounts.get(acct_id)
            if not a:
                a = ChaoxingAccount(acct_id, owner)
                self.accounts[acct_id] = a
            elif a.owner != owner:
                # 同一学习通账号被其他站点用户再次扫码时，归属权转移给当前扫码者，
                # 否则会出现“扫码提示成功、但当前用户列表看不到”的问题
                a.owner = owner
                a.save_config()
        a.adopt_client(client)
        return a

    def remove_account(self, acct_id):
        with self.lock:
            a = self.accounts.pop(str(acct_id), None)
        if a:
            a.stop_monitor(persist=True)
            try:
                shutil.rmtree(a.dir, ignore_errors=True)
            except Exception:
                pass
            log(f"学习通账号已移除: {a.name or a.acct_id} (owner={a.owner})", "info", a.owner)
        return bool(a)

    def accounts_by_owner(self, owner):
        with self.lock:
            return [a for a in self.accounts.values() if a.owner == owner]

    def add_user(self, client):
        """兼容本地短信/浏览器登录入口：扫码账号归属管理员"""
        return self.add_account(ADMIN_USERNAME, client)

    def all_accounts(self):
        with self.lock:
            return list(self.accounts.values())

    def get_all_records(self, limit=200, owner=None, result=None):
        """聚合所有账号的签到记录，按时间倒序"""
        rows = []
        for a in self.all_accounts():
            if owner and a.owner != owner:
                continue
            for r in a.records:
                item = dict(r)
                item["acct_id"] = a.acct_id
                item["acct_name"] = a.name or a.acct_id
                item["owner"] = a.owner
                if result and item.get("result") != result:
                    continue
                rows.append(item)
        rows.sort(key=lambda x: x.get("time", ""), reverse=True)
        return rows[:limit]

    def sign_stats(self):
        """全局签到统计：今日/总计的成功、失败、需手动数量"""
        today = datetime.now().strftime("%m-%d")
        st = {"today_success": 0, "today_fail": 0, "today_manual": 0,
              "total_success": 0, "total_fail": 0, "total_manual": 0, "total_records": 0}
        for a in self.all_accounts():
            for r in a.records:
                res = r.get("result")
                st["total_records"] += 1
                if res == "success":
                    st["total_success"] += 1
                elif res == "fail":
                    st["total_fail"] += 1
                elif res == "manual":
                    st["total_manual"] += 1
                if str(r.get("time", "")).startswith(today):
                    if res == "success":
                        st["today_success"] += 1
                    elif res == "fail":
                        st["today_fail"] += 1
                    elif res == "manual":
                        st["today_manual"] += 1
        return st

    def load_all(self):
        os.makedirs(ACCOUNTS_DIR, exist_ok=True)
        self._migrate_legacy()
        acct_ids = [d for d in os.listdir(ACCOUNTS_DIR)
                    if os.path.isdir(os.path.join(ACCOUNTS_DIR, d))]
        for acct_id in acct_ids:
            try:
                owner = load_json(os.path.join(ACCOUNTS_DIR, acct_id, "config.json"), {}).get("owner", "")
                a = self.get_or_create_account(owner, acct_id)
                if a.restore_login() and a.config.get("monitor_on"):
                    # 启动错峰：每个账号随机延迟 0~30s 再开监控，
                    # 避免多账号同时全量扫描形成请求脉冲（曾撞发学习通限频）
                    delay = random.uniform(0, 30)

                    def _delayed_start(acc=a, d=delay):
                        time.sleep(d)
                        acc.start_monitor()
                    threading.Thread(target=_delayed_start, daemon=True).start()
                # 账号间的登录/课程刷新串行化，间隔 2~4s
                time.sleep(2.0 + random.random() * 2.0)
            except Exception as e:
                log(f"恢复账号 {acct_id} 失败: {e}", "warn", owner)
        ok = sum(1 for a in self.accounts.values() if a.logged_in())
        log(f"服务启动完成, 已登记 {len(self.accounts)} 个学习通账号, 其中 {ok} 个登录态有效", "info")

    def _migrate_legacy(self):
        if not os.path.isdir(LEGACY_USERS_DIR):
            return
        for uid in os.listdir(LEGACY_USERS_DIR):
            src = os.path.join(LEGACY_USERS_DIR, uid)
            dst = os.path.join(ACCOUNTS_DIR, uid)
            if not os.path.isdir(src) or os.path.exists(dst):
                continue
            try:
                shutil.move(src, dst)
                cfg = load_json(os.path.join(dst, "config.json"), {})
                cfg["owner"] = ADMIN_USERNAME
                save_json(os.path.join(dst, "config.json"), cfg)
                log(f"已迁移旧账号 {uid} -> 归属管理员 {ADMIN_USERNAME}", "info")
            except Exception as e:
                log(f"迁移旧账号 {uid} 失败: {e}", "warn")
        try:
            remains = os.listdir(LEGACY_USERS_DIR)
            if not remains:
                os.rmdir(LEGACY_USERS_DIR)
        except Exception:
            pass

    # ---- 扫码会话（多人并发）----
    def qr_start(self):
        now = time.time()
        for k in [k for k, v in self.qr_sessions.items() if now - v["ts"] > 600]:
            self.qr_sessions.pop(k, None)
        try:
            ctx = CxClient.qr_create()
        except Exception as e:
            return None, str(e)
        qid = _uuid.uuid4().hex
        self.qr_sessions[qid] = {"ctx": ctx, "ts": now}
        return {"qr_id": qid, "qr": ctx["qr_base64"]}, None

    def qr_poll(self, qid, owner=""):
        item = self.qr_sessions.get(qid)
        if not item:
            return {"status": "expired"}
        res = CxClient.qr_poll(item["ctx"])
        if res.get("status") == "confirmed":
            self.qr_sessions.pop(qid, None)
            a = self.add_account(owner, res["client"])
            if a.config.get("monitor_on") and not a.config.get("need_relogin"):
                a.start_monitor()
            return {"status": "confirmed", "acct_id": a.acct_id, "name": a.name, "owner": a.owner}
        if res.get("status") in ("expired", "canceled", "failed"):
            self.qr_sessions.pop(qid, None)
        return res

    # ---- 守护 ----
    def watchdog(self, interval=20):
        last_restore = 0.0
        while True:
            try:
                allow_restore = (time.time() - last_restore) > 300
                for a in self.all_accounts():
                    try:
                        if a.config.get("need_relogin"):
                            continue
                        if not a.config.get("monitor_on"):
                            # 限频自动冷却：到点后自动恢复监控（手动停止的账号
                            # freq_cooldown_until 为 0，不会被误恢复）
                            cd = a.config.get("freq_cooldown_until", 0) or 0
                            if cd and time.time() >= cd:
                                a.config["monitor_on"] = True
                                a.config["freq_cooldown_until"] = 0
                                a.save_config()
                                log("限频自动冷却结束, 恢复监控", "info", a.owner)
                                a.start_monitor()
                            continue
                        if a.monitoring and not a.monitor_thread_alive():
                            log("看门狗: 监控线程意外死亡, 自动重启", "warn", a.owner)
                            with a.lock:
                                a.monitoring = False
                            a.start_monitor()
                        elif not a.logged_in():
                            if allow_restore and a.restore_login():
                                a.start_monitor()
                        elif not a.monitoring:
                            log("看门狗: 监控未运行, 自动恢复", "warn", a.owner)
                            a.start_monitor()
                    except Exception as e:
                        log(f"看门狗处理账号 {a.acct_id} 出错: {type(e).__name__}: {e}", "warn", a.owner)
                if allow_restore:
                    last_restore = time.time()
            except Exception as e:
                log(f"看门狗异常: {type(e).__name__}: {e}", "warn")
            time.sleep(interval)

    def keepalive(self, interval=120):
        port = int(os.environ.get("PORT", "8765"))
        url = f"http://127.0.0.1:{port}/api/ping"
        while True:
            try:
                requests.get(url, timeout=10)
            except Exception:
                pass
            time.sleep(interval)

    def start_guardians(self):
        threading.Thread(target=self.watchdog, daemon=True).start()
        threading.Thread(target=self.keepalive, daemon=True).start()

    def uptime_seconds(self):
        return int(time.time() - self.started_at)


MGR = App()
TICKETS = TicketStore()


# ---------------- 公告系统 ----------------

class AnnouncementStore:
    TYPES = ["info", "success", "warning", "error"]
    LABEL_TYPE = {"info": "通知", "success": "公告", "warning": "提示", "error": "重要"}

    def __init__(self):
        self.path = ANNOUNCEMENTS_FILE
        self.lock = threading.RLock()
        self.items = []
        self.seq = 0
        self._load()

    def _load(self):
        data = load_json(self.path, {"seq": 0, "items": []})
        self.seq = data.get("seq", 0)
        self.items = data.get("items", [])

    def _save(self):
        save_json(self.path, {"seq": self.seq, "items": self.items})

    def _next_id(self):
        self.seq += 1
        return self.seq

    def create(self, title, content, atype="info", enabled=True):
        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            return None, "标题不能为空"
        if atype not in self.TYPES:
            atype = "info"
        with self.lock:
            aid = self._next_id()
            item = {
                "id": aid, "title": title, "content": content, "type": atype,
                "enabled": bool(enabled), "created_at": now_iso(), "updated_at": now_iso(),
            }
            self.items.append(item)
            self._save()
        log(f"发布新公告 #{aid}: {title}", "info")
        return item, ""

    def get(self, aid):
        with self.lock:
            for it in self.items:
                if it["id"] == int(aid):
                    return it
        return None

    def update(self, aid, **fields):
        with self.lock:
            it = self.get(aid)
            if not it:
                return False, "公告不存在"
            for f in ("title", "content", "type", "enabled"):
                if f in fields:
                    v = fields[f]
                    if f == "type" and v not in self.TYPES:
                        v = it["type"]
                    if f == "enabled":
                        v = bool(v)
                    it[f] = v
            it["updated_at"] = now_iso()
            self._save()
        return True, ""

    def delete(self, aid):
        with self.lock:
            before = len(self.items)
            self.items = [it for it in self.items if it["id"] != int(aid)]
            if len(self.items) != before:
                self._save()
                return True
            return False

    def list_all(self):
        with self.lock:
            res = list(self.items)
            res.sort(key=lambda x: (x.get("enabled", False), x.get("updated_at", "")), reverse=True)
            return res

    def active(self):
        with self.lock:
            res = [it for it in self.items if it.get("enabled")]
            res.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return res


ANNOUNCEMENTS = AnnouncementStore()


# ---------------- 站内消息中心 ----------------

class MessageStore:
    """按用户隔离的站内消息：公告 / 签到结果 / 工单回复 / 系统通知"""

    TYPES = ["announcement", "sign", "ticket", "system"]
    LABEL_TYPE = {"announcement": "公告", "sign": "签到", "ticket": "工单", "system": "系统"}
    MAX_PER_USER = 300

    def __init__(self):
        self.path = MESSAGES_FILE
        self.lock = threading.RLock()
        self.items = []
        self.seq = 0
        self._load()

    def _load(self):
        data = load_json(self.path, {"seq": 0, "items": []})
        self.seq = data.get("seq", 0)
        self.items = data.get("items", [])

    def _save(self):
        save_json(self.path, {"seq": self.seq, "items": self.items})

    def _next_id(self):
        self.seq += 1
        return self.seq

    def create(self, username, mtype, title, content, ref_id=""):
        """给单个用户生成一条消息；username 为空则跳过（未绑定账号的系统消息不入库）"""
        username = (username or "").strip()
        if not username:
            return None
        title = (title or "").strip()
        if not title:
            return None
        if mtype not in self.TYPES:
            mtype = "system"
        with self.lock:
            mid = self._next_id()
            item = {
                "id": mid, "username": username, "type": mtype,
                "title": title, "content": (content or "").strip(),
                "ref_id": str(ref_id or ""), "read": False,
                "created_at": now_iso(),
            }
            self.items.append(item)
            # 每个用户只保留最近 MAX_PER_USER 条，防止文件无限增长
            mine = [it for it in self.items if it["username"] == username]
            if len(mine) > self.MAX_PER_USER:
                drop = {it["id"] for it in sorted(mine, key=lambda x: x["id"])[:len(mine) - self.MAX_PER_USER]}
                self.items = [it for it in self.items if it["id"] not in drop]
            self._save()
        return item

    def create_many(self, usernames, mtype, title, content, ref_id=""):
        """批量生成（如公告群发），返回实际生成条数"""
        n = 0
        for u in usernames or []:
            if self.create(u, mtype, title, content, ref_id):
                n += 1
        return n

    def list_for(self, username, unread_only=False, mtype="", limit=100):
        username = (username or "").strip()
        with self.lock:
            res = [it for it in self.items if it["username"] == username]
            if unread_only:
                res = [it for it in res if not it.get("read")]
            if mtype:
                res = [it for it in res if it.get("type") == mtype]
            res.sort(key=lambda x: x.get("id", 0), reverse=True)
            return res[:limit]

    def unread_count(self, username):
        return len(self.list_for(username, unread_only=True, limit=1000))

    def mark_read(self, mid, username):
        with self.lock:
            for it in self.items:
                if it["id"] == int(mid) and it["username"] == username:
                    if not it.get("read"):
                        it["read"] = True
                        self._save()
                    return True
        return False

    def mark_all_read(self, username):
        username = (username or "").strip()
        n = 0
        with self.lock:
            for it in self.items:
                if it["username"] == username and not it.get("read"):
                    it["read"] = True
                    n += 1
            if n:
                self._save()
        return n

    def delete_read(self, username):
        """清空已读消息，返回删除条数"""
        username = (username or "").strip()
        with self.lock:
            before = len(self.items)
            self.items = [it for it in self.items
                          if not (it["username"] == username and it.get("read"))]
            n = before - len(self.items)
            if n:
                self._save()
            return n


MESSAGES = MessageStore()


# ---------------- 邮件发送日志 ----------------

class EmailLogStore:
    """后台邮件群发历史（只增不改）"""

    def __init__(self):
        self.path = EMAIL_LOGS_FILE
        self.lock = threading.RLock()
        self.items = []
        self.seq = 0
        self._load()

    def _load(self):
        data = load_json(self.path, {"seq": 0, "items": []})
        self.seq = data.get("seq", 0)
        self.items = data.get("items", [])

    def _save(self):
        save_json(self.path, {"seq": self.seq, "items": self.items[-200:]})

    def add(self, sender, to_mode, to_count, subject, ok_count, fail_count, detail=""):
        with self.lock:
            self.seq += 1
            item = {
                "id": self.seq, "sender": sender, "to_mode": to_mode,
                "to_count": to_count, "subject": (subject or "")[:120],
                "ok_count": ok_count, "fail_count": fail_count,
                "detail": (detail or "")[:500], "created_at": now_iso(),
            }
            self.items.append(item)
            self._save()
        return item

    def list_all(self, limit=100):
        with self.lock:
            res = list(self.items)
            res.sort(key=lambda x: x.get("id", 0), reverse=True)
            return res[:limit]


EMAIL_LOGS = EmailLogStore()


# ---------------- 系统设置 ----------------

class SettingsStore:
    """站点级开关设置（注册开关 / 邮件通知总开关 / 站点名称）"""

    DEFAULTS = {
        "site_name": "马上签",
        "registration_open": True,
        "email_notify": True,
    }

    def __init__(self):
        self.path = SETTINGS_FILE
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        try:
            raw = load_json(self.path, {})
            if isinstance(raw, dict):
                self.data = dict(self.DEFAULTS, **{k: v for k, v in raw.items() if k in self.DEFAULTS})
        except Exception:
            self.data = dict(self.DEFAULTS)

    def _save(self):
        save_json(self.path, self.data)

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def all(self):
        with self.lock:
            return dict(self.data)

    def update(self, **fields):
        with self.lock:
            for k, v in fields.items():
                if k not in self.data:
                    continue
                if isinstance(self.data[k], bool):
                    v = bool(v)
                elif isinstance(self.data[k], str):
                    v = str(v)
                self.data[k] = v
            self._save()
            return dict(self.data)


SETTINGS = SettingsStore()


# ---------------- APP 版本发布 ----------------

class AppReleaseStore:
    """APP 版本发布管理：保存历史版本，latest 取 version_code 最大的启用版本。

    字段说明：
      version_name      版本号字符串，如 1.0.0
      version_code      版本号整数（Android versionCode），必须唯一且递增
      apk_url           APK 下载直链
      update_log        更新日志
      force_update      是否强制更新（命中时 APP 必须升级才能继续用）
      min_supported_code 最低支持版本号，低于它的版本也必须升级
      enabled           是否生效（下线某个版本）
    """

    def __init__(self):
        self.path = APP_RELEASES_FILE
        self.lock = threading.RLock()
        self.items = []
        self.seq = 0
        self._load()

    def _load(self):
        data = load_json(self.path, {"seq": 0, "items": []})
        self.seq = data.get("seq", 0)
        self.items = data.get("items", [])

    def _save(self):
        save_json(self.path, {"seq": self.seq, "items": self.items})

    def _next_id(self):
        self.seq += 1
        return self.seq

    @staticmethod
    def _parse_name(name):
        """把 '1.2.3' 解析成 (1,2,3) 用于比较；无法解析返回 None"""
        try:
            parts = [int(p) for p in str(name).strip().split(".") if p != ""]
            return tuple(parts) if parts else None
        except (TypeError, ValueError):
            return None

    def create(self, version_name, version_code, apk_url="", update_log="",
               force_update=False, min_supported_code=0, enabled=True):
        version_name = (version_name or "").strip()
        if not version_name:
            return None, "版本号不能为空（如 1.0.0）"
        if not self._parse_name(version_name):
            return None, "版本号格式不正确（应为 x.y.z，如 1.0.0）"
        try:
            version_code = int(version_code)
        except (TypeError, ValueError):
            return None, "version_code 必须是整数（如 1）"
        if version_code <= 0:
            return None, "version_code 必须大于 0"
        try:
            min_supported_code = int(min_supported_code or 0)
        except (TypeError, ValueError):
            min_supported_code = 0
        with self.lock:
            for it in self.items:
                if it["version_code"] == version_code:
                    return None, f"version_code {version_code} 已被 {it['version_name']} 占用，请递增"
            rid = self._next_id()
            item = {
                "id": rid,
                "version_name": version_name,
                "version_code": version_code,
                "apk_url": (apk_url or "").strip(),
                "update_log": (update_log or "").strip(),
                "force_update": bool(force_update),
                "min_supported_code": max(0, min_supported_code),
                "enabled": bool(enabled),
                "created_at": now_iso(),
            }
            self.items.append(item)
            self._save()
        log(f"发布新 APP 版本 {version_name}(versionCode={version_code})", "info")
        return item, ""

    def get(self, rid):
        with self.lock:
            for it in self.items:
                if it["id"] == int(rid):
                    return it
        return None

    def update(self, rid, **fields):
        with self.lock:
            it = self.get(rid)
            if not it:
                return False, "版本不存在"
            for f in ("version_name", "apk_url", "update_log"):
                if f in fields and fields[f] is not None:
                    v = str(fields[f]).strip()
                    if f == "version_name":
                        if not v or not self._parse_name(v):
                            return False, "版本号格式不正确（应为 x.y.z）"
                    it[f] = v
            for f in ("force_update", "enabled"):
                if f in fields and fields[f] is not None:
                    it[f] = bool(fields[f])
            if fields.get("min_supported_code") is not None:
                try:
                    it["min_supported_code"] = max(0, int(fields["min_supported_code"]))
                except (TypeError, ValueError):
                    return False, "min_supported_code 必须是整数"
            self._save()
        return True, ""

    def delete(self, rid):
        with self.lock:
            before = len(self.items)
            self.items = [it for it in self.items if it["id"] != int(rid)]
            if len(self.items) != before:
                self._save()
                return True
            return False

    def list_all(self):
        with self.lock:
            res = list(self.items)
            res.sort(key=lambda x: x.get("version_code", 0), reverse=True)
            return res

    def latest(self):
        with self.lock:
            enabled = [it for it in self.items if it.get("enabled")]
            if not enabled:
                return None
            return max(enabled, key=lambda x: x.get("version_code", 0))

    def check(self, current_code=None, current_name=None):
        """APP 检测更新：返回最新版本、是否需要更新、是否强制更新。"""
        latest = self.latest()
        cur_code = None
        if current_code not in (None, ""):
            try:
                cur_code = int(current_code)
            except (TypeError, ValueError):
                cur_code = None
        cur_name = (str(current_name).strip() if current_name else None) or None

        has_update = False
        below_min = False
        if latest:
            if cur_code is not None:
                has_update = cur_code < latest["version_code"]
                below_min = cur_code < latest.get("min_supported_code", 0)
            elif cur_name:
                cur_t = self._parse_name(cur_name)
                lat_t = self._parse_name(latest["version_name"])
                if cur_t and lat_t:
                    has_update = cur_t < lat_t
                else:
                    has_update = cur_name != latest["version_name"]
        force = bool(has_update and latest and (latest.get("force_update") or below_min))
        return {
            "latest": latest,
            "has_update": bool(has_update),
            "force_update": force,
            "below_min_supported": bool(below_min),
            "current": {"version_code": cur_code, "version_name": cur_name},
        }


APP_RELEASES = AppReleaseStore()


# ---------------- APP 闪屏配置 ----------------

class SplashStore:
    """APP 闪屏配置（站点级单例）：图片链接 / 展示秒数 / 点击跳转链接 / 开关。

    字段说明：
      enabled      是否启用闪屏（关掉后 APP 拿到的 enabled 直接为 false）
      image_url    闪屏图片链接（建议 1080x1920 竖图、JPG/PNG、<500KB）
      duration     展示秒数，1~10，默认 3
      jump_url     点击闪屏的跳转链接（活动页/公告页等；为空 = 不跳转）
      updated_at   最近一次修改时间（只读，保存时自动更新）
    """

    DEFAULTS = {
        "enabled": False,
        "image_url": "",
        "duration": 3,
        "jump_url": "",
        "updated_at": "",
    }

    MIN_DURATION = 1
    MAX_DURATION = 10

    def __init__(self):
        self.path = SPLASH_FILE
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        try:
            raw = load_json(self.path, {})
            if isinstance(raw, dict):
                d = {k: v for k, v in raw.items() if k in self.DEFAULTS}
                if "duration" in d:
                    try:
                        d["duration"] = int(d["duration"])
                    except (TypeError, ValueError):
                        d.pop("duration")
                self.data = dict(self.DEFAULTS, **d)
        except Exception:
            self.data = dict(self.DEFAULTS)

    def _save(self):
        save_json(self.path, self.data)

    def all(self):
        with self.lock:
            return dict(self.data)

    def update(self, **fields):
        with self.lock:
            for k, v in fields.items():
                if k not in self.data or k == "updated_at":
                    continue
                if k == "enabled":
                    v = bool(v)
                elif k == "duration":
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        continue
                    v = max(self.MIN_DURATION, min(self.MAX_DURATION, v))
                else:
                    v = str(v or "").strip()
                self.data[k] = v
            self.data["updated_at"] = now_iso()
            self._save()
            return dict(self.data)


SPLASH = SplashStore()


def boot():
    MGR.ensure_admin()
    MGR.load_all()
    MGR.start_guardians()
