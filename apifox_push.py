# -*- coding: utf-8 -*-
"""
把 openapi.json 推送到你的 Apifox 项目（已验证可用）。

用法：
  export APIFOX_TOKEN="afxp_..."        # 个人访问令牌（必填）
  export APIFOX_PROJECT_ID="2079879"    # 目标项目 ID（必填）
  # 可选：自定义规范来源（默认用线上部署的 URL）
  export APIFOX_OPENAPI_URL="http://xxt.leich.cn/openapi.json"
  python3 apifox_push.py

令牌获取：Apifox 右上角头像 -> 账号设置 -> API 访问令牌 -> 新建。
项目 ID：项目设置 -> 基本设置 里查看。
"""
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    token = os.environ.get("APIFOX_TOKEN")
    project_id = os.environ.get("APIFOX_PROJECT_ID")
    if not token or not project_id:
        print("缺少环境变量 APIFOX_TOKEN / APIFOX_PROJECT_ID，无法推送。")
        print("请设置后重新运行；你也可以直接把 openapi.json 导入 Apifox。")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Apifox-Api-Version": "2024-03-28",
        "Content-Type": "application/json",
    }

    # 优先用线上 URL（最稳，已验证可被 Apifox 抓取），否则内联本地文件
    src = os.environ.get("APIFOX_OPENAPI_URL") or "http://xxt.leich.cn/openapi.json"
    if src.startswith(("http://", "https://")):
        inp = {"url": src}
    else:
        with open(src, "r", encoding="utf-8") as f:
            inp = json.load(f)

    body = {
        "input": inp,
        "options": {
            "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
            "schemaOverwriteBehavior": "OVERWRITE_EXISTING",
        },
    }
    api = f"https://api.apifox.com/v1/projects/{project_id}/import-openapi"
    try:
        r = requests.post(api, headers=headers, json=body, timeout=120)
        print("HTTP", r.status_code)
        print(r.text[:1000])
        if r.status_code != 200:
            sys.exit(1)
    except Exception as e:
        print("推送失败:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
