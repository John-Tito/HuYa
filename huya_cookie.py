#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""虎牙 UDB 登录态静默续期（复刻网页端 udb.sdk.web.js 的 credLogin）。

为什么导出的 Cookie 会「过期」，而浏览器永远不会掉登录？
--------------------------------------------------------
虎牙登录态由两个 udb Cookie 组成：

  udb_biztoken  业务令牌，网页/接口真正用来判断登录的凭证，寿命只有 15 天
  udb_cred      长期凭证（refresh credential），寿命 180 天

浏览器并不是「Cookie 永不过期」，而是每次访问时前端 SDK
(https://a.msstatic.com/huya/hd/web/udb_login/lib/udb.sdk.web.js) 会检测到
udb_cred 还在、而 udb_biztoken 已缺失/失效，于是静默 POST
  https://udblgn.huya.com/web/credLogin
用 udb_cred 换一份全新的 udb_biztoken（服务端通过 Set-Cookie 下发），同时把
udb_cred 本身也滚动成一张新的 180 天凭证。也就是说这是一个「滑动续期」：
只要你 180 天内访问过一次网页，登录态就永远续下去，所以你从来没被要求重新登录。

而从浏览器里「导出」的只是一份静态快照：udb_biztoken 一到期（约两周，部分场景
只有 7 天）就没人替它续期，脚本自然就登录失败了 —— 这就是本模块要解决的问题。

只要能把续期后的 Cookie 保存下来（写回 GitHub Secret），一张 Cookie 就可以无限用。
"""

import sys
import base64
import hashlib
import json
import os
from urllib.parse import quote

import requests

DEFAULT_COOKIE_ENV = "HUYA_COOKIE"
DEFAULT_COOKIE_FILE = ".huya_cookie/cookie.txt"

# 复刻自 udb.sdk.web.js 中 credLogin() 的默认参数
CRED_LOGIN_URL = "https://udblgn.huya.com/web/credLogin"
UDB_APPID = "5002"
UDB_APPKEY = "bfd434f70d40433c6b57a781dbcee91a"
UDB_SDK_VERSION = "2.6"

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def parse_cookie(cookie_str):
    """Cookie 字符串 -> dict。值里可能含 '='，所以只按第一个 '=' 切分。"""
    out = {}
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def load_cookie(log=print):
    """载入 Cookie
    """

    cookie_env = os.getenv(DEFAULT_COOKIE_ENV, "").strip()
    cookie_cache = ""

    if os.path.exists(DEFAULT_COOKIE_FILE):
        try:
            cookie_cache = open(DEFAULT_COOKIE_FILE, encoding="utf-8").read().strip()
        except OSError as e:
            log(f"[COOKIE] 读取缓存文件失败: {type(e).__name__}: {e}")

    return (cookie_env, cookie_cache, DEFAULT_COOKIE_FILE)

def drop_cookie_cache(path, log=print):
    """丢弃缓存文件"""
    if not path:
        return False
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        log(f"[WARN] 删除缓存文件失败: {type(e).__name__}: {e}")
        return False


def save_cookie_cache(path, cookie):
    """保存缓存文件"""
    if not path:
        return None
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cookie)
    os.chmod(path, 0o600)
    return path

def format_cookie(cookies):
    return ";".join(f"{k}={v}" for k, v in cookies.items() if v != "")

def _app_sign(appid=UDB_APPID, version=UDB_SDK_VERSION, appkey=UDB_APPKEY):
    # SDK 里的 r() 就是一份标准 MD5 实现
    return hashlib.md5(f"{appid}_{version}_{appkey}".encode()).hexdigest()

def cred_login(cookies, timeout=20, page="https://www.huya.com/"):
    """用 udb_cred 换新令牌，返回 (响应 JSON, 合并后的 cookie dict)。"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_UA,
        "Content-Type": "application/json",
        "Origin": "https://www.huya.com",
        "Referer": "https://www.huya.com/",
    })
    for k, v in cookies.items():
        session.cookies.set(k, v, domain=".huya.com", path="/")

    body = {
        "uri": "70017",
        "version": UDB_SDK_VERSION,
        "context": "1",
        "appId": UDB_APPID,
        "appSign": _app_sign(),
        "lcid": "2052",
        "data": {"page": quote(page, safe="")},
    }
    resp = session.post(CRED_LOGIN_URL, data=json.dumps(body), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    merged = dict(cookies)
    for c in session.cookies:
        if c.domain and "huya.com" in c.domain:
            merged[c.name] = c.value
    return payload, merged

def refresh_cookie(cookie_str, log=print):
    """续期 Cookie

    返回 (cookie_str, info)。续期失败时原样返回，并在日志里给出原因，
    这样即使虎牙改了协议，脚本也只是退化成「旧行为」，不会直接崩。
    """
    cookies = parse_cookie(cookie_str)
    if not cookies.get("udb_cred"):
        log("[COOKIE] 未发现 udb_cred，跳过续期（请按 readme 重新导出完整 Cookie）")
        return cookie_str, None

    try:
        payload, merged = cred_login(cookies)
    except Exception as e:
        log(f"[COOKIE] 续期请求失败: {type(e).__name__}: {e}")
        return cookie_str, None

    if payload.get("returnCode") != 0:
        log(f"[COOKIE] 续期被拒绝 returnCode={payload.get('returnCode')} "
            f"message={payload.get('message')}，Cookie 可能已失效，请重新导出")
        return cookie_str, None

    login_data = (payload.get("data") or {}).get("loginData") or {}
    uid = login_data.get("uid")
    if not uid:
        log("[COOKIE] 续期响应缺少 uid，按失败处理")
        return cookie_str, None

    changed = format_cookie(merged) != format_cookie(cookies)
    info = {
        "uid": uid,
        "passport": login_data.get("passport"),
        "biztoken_changed": merged.get("udb_biztoken") != cookies.get("udb_biztoken"),
        "cred_changed": merged.get("udb_cred") != cookies.get("udb_cred"),
        "changed": changed,
    }
    log(f"[COOKIE] 续期成功 "
        f"(biztoken {'已更新' if info['biztoken_changed'] else '未变'}, "
        f"cred {'已更新' if info['cred_changed'] else '未变'})")
    return format_cookie(merged), info

if __name__ == "__main__":
    # 直接运行本文件 = 用 cookie 做一次续期自检
    # 用法: python huya_cookie.py [cookie_file]
    #   若 cookie_file 存在则从其读取，否则回退到环境变量 HUYA_COOKIE
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_COOKIE_FILE

    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    else:
        raw = os.getenv(DEFAULT_COOKIE_ENV, "").strip()

    if not raw:
        print(f"用法: python {sys.argv[0]} [cookie_file]")
        print(f"  或:  {DEFAULT_COOKIE_ENV}='...' python {sys.argv[0]}")
        raise SystemExit(1)

    new_cookie, info = refresh_cookie(raw)
    if info:
        parsed = parse_cookie(new_cookie)
        print("\n续期后的 Cookie：")
        print(new_cookie)
        print(f"\n(uid={info['uid']}, 共 {len(parsed)} 个字段)")

        # 保存为 {path_name}_refresh.txt
        base, _ = os.path.splitext(path)
        refresh_path = f"{base}_refresh.txt"
        save_cookie_cache(refresh_path, new_cookie)
        print(f"\n已保存到: {refresh_path}")
    else:
        print("续期失败")
        raise SystemExit(2)
