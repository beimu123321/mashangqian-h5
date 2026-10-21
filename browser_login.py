# -*- coding: utf-8 -*-
"""
浏览器辅助登录（手机验证码登录）。

学习通发送短信验证码前必须通过 captcha.chaoxing.com 的人机验证（滑块），
纯接口方式无法稳定通过，因此采用「弹出浏览器窗口」的辅助方式：
  1. 程序打开真实的学习通登录页
  2. 用户自己切换到「验证码登录」，输入手机号、过滑块、填验证码并登录
  3. 程序检测到登录成功的 Cookie 后自动接管（注册为一个用户）

依赖（可选安装）: pip install playwright && playwright install chromium
注意：云端/无桌面环境无法弹出窗口，请使用二维码扫码登录。
"""
import threading
import time

from core import CxClient, MGR, log


class _BrowserState:
    def __init__(self):
        self.run_flag = False
        self.status = ""
        self.uid = None


STATE = _BrowserState()


def start_browser_login():
    if STATE.run_flag:
        return "已有浏览器登录进行中"
    try:
        import playwright  # noqa: F401
    except ImportError:
        STATE.status = ("未安装 playwright。请先执行: "
                        "pip install playwright && playwright install chromium")
        log(STATE.status, "warn")
        return STATE.status

    STATE.run_flag = True
    STATE.status = "正在打开浏览器窗口..."
    threading.Thread(target=_run, daemon=True).start()
    return None


def _run():
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False,
                                            args=["--no-sandbox", "--start-maximized"])
            except Exception as e:
                STATE.status = f"启动浏览器失败: {e}（请先执行 playwright install chromium）"
                log(STATE.status, "error")
                return
            ctx = browser.new_context(no_viewport=True)
            pg = ctx.new_page()
            pg.goto("https://passport2.chaoxing.com/login",
                    wait_until="domcontentloaded", timeout=60000)
            STATE.status = ("浏览器窗口已打开: 请在窗口中完成登录"
                            "（验证码登录或任意方式均可），登录成功后会自动接管。")
            log("浏览器登录窗口已打开, 等待用户完成登录...")

            deadline = time.time() + 600
            success = False
            while time.time() < deadline:
                if browser.is_closed():
                    STATE.status = "浏览器已关闭, 登录未完成"
                    log(STATE.status, "warn")
                    return
                try:
                    cookies = ctx.cookies()
                except Exception:
                    break
                names = {c["name"]: c for c in cookies}
                if "_uid" in names and names["_uid"].get("value"):
                    client = CxClient(cookies=[{"name": c["name"], "value": c["value"],
                                                "domain": c.get("domain", ".chaoxing.com")}
                                               for c in cookies])
                    client._refresh_ids()
                    if client.check_valid():
                        u = MGR.add_user(client)
                        if u.config.get("monitor_on"):
                            u.start_monitor()
                        STATE.uid = u.uid
                        STATE.status = f"登录成功！用户: {u.name or u.uid}"
                        try:
                            browser.close()
                        except Exception:
                            pass
                        success = True
                        break
                time.sleep(1.5)
            if not success and STATE.run_flag:
                STATE.status = "等待超时（10 分钟）, 请重试"
                log(STATE.status, "warn")
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        STATE.status = f"浏览器登录出错: {e}"
        log(STATE.status, "error")
    finally:
        STATE.run_flag = False
