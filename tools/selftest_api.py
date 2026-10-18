#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口自检：查登录、虎粮、流水、打卡状态，可选试跑送礼。

    python tools/selftest_api.py --room 998                  # 只读
    python tools/selftest_api.py --room 998 --send-dry-run   # 生成流水号和签名，不发包
    python tools/selftest_api.py --room 998 --send 1         # 真送，会扣粮

Cookie 优先取环境变量 HUYA_COOKIE，其次 .huya_cookie/cookie1.txt / cookie.txt，
也可以设 HUYA_COOKIE_FILE 指定文件。
"""

import argparse
import datetime
import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import huya_api as hapi  # noqa: E402
import huya_cookie  # noqa: E402


def load_cookie(path):
    env = (os.getenv("HUYA_COOKIE") or "").strip()
    if env:
        return env, "env"
    for p in (path, ".huya_cookie/cookie1.txt", ".huya_cookie/cookie.txt"):
        if p and os.path.exists(p):
            return open(p, encoding="utf-8").read().strip(), p
    raise SystemExit("找不到 Cookie：请设置 HUYA_COOKIE 或准备 .huya_cookie/cookie1.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", type=int, default=998)
    ap.add_argument("--send-dry-run", action="store_true", help="只生成流水号与签名")
    ap.add_argument("--send", type=int, default=0, help="真的送 N 个虎粮（会扣粮！）")
    args = ap.parse_args()

    cookie, src = load_cookie(os.getenv("HUYA_COOKIE_FILE", ""))
    print(f"Cookie 来源: {src}  （长度 {len(cookie)}）")

    # 只有 udb_cred/biztoken 的导出没有 udb_uid，需要先走一次 credLogin
    uid = hapi.HuyaAPI(cookie).uid
    passport = None
    if uid <= 0:
        print("Cookie 里没有 udb_uid，先做一次 credLogin 续期取 uid/passport…")
        payload, merged = huya_cookie.cred_login(huya_cookie.parse_cookie(cookie))
        ld = (payload.get("data") or {}).get("loginData") or {}
        uid, passport = ld.get("uid"), ld.get("passport")
        cookie = huya_cookie.format_cookie(merged)
        print(f"credLogin: uid={uid} passport={passport} returnCode={payload.get('returnCode')}")

    api = hapi.HuyaAPI(cookie, passport=passport)
    print(f"uid={api.uid} passport={api.passport!r} login={api.verify_login()}")
    print("余额(金豆/银豆/虎牙券):", api.bean_balance())

    count, bcode, items = api.hu_liang_count()
    print(f"虎粮: {count}  (bcode={bcode})")
    for it in items:
        print(f"   - {it['name']:<10} x{it['count']:<5} type={it['itemType']}")

    bcode, water = api.water()
    print(f"流水: {len(water)} 条")
    for w in water[:5]:
        ts = datetime.datetime.fromtimestamp(w["time"]) if w["time"] else None
        kind = "收入" if w["waterType"] == 1 else "支出"
        print(f"   {ts:%m-%d %H:%M:%S}  {w['name']} {w['count']} {kind} {w['source']}")

    lp, gid = api.room_lp_gid(args.room)
    print(f"房间 {args.room}: lp={lp} gid={gid}")
    if not lp:
        return
    lpid = int(lp)
    print("打卡状态:", api.fans_sign_state(lpid))

    if args.send_dry_run or args.send:
        n = args.send or 1
        res = api.send_hu_liang(lpid, n, dry_run=(args.send == 0))
        if res.get("dryRun"):
            print(f"dry-run: sPayId={res['sPayId']} sSign={res['sSign']}")
            print("payload:", {k: v for k, v in res["payload"].items()})
        else:
            print("真实发送结果:", {k: v for k, v in res.items() if k != "rsp"})
            left, _, _ = api.hu_liang_count()
            print("发送后虎粮:", left)


if __name__ == "__main__":
    main()
