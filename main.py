#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import random
import time

import requests

from huya_api import HuyaAPI
from huya_cookie import (drop_cookie_cache, load_cookie, parse_cookie, refresh_cookie,
                         save_cookie_cache)

COOKIE_DIR = ".huya_cookie"


def _pause(a, b):
    time.sleep(random.uniform(a, b))


def build_accounts():
    """多账号用 HUYA_COOKIES（每行一个 Cookie），单账号沿用 HUYA_COOKIE 或缓存文件"""
    raw = os.getenv("HUYA_COOKIES", "").strip()
    if raw:
        rows = [line.strip() for line in raw.splitlines() if line.strip()]
        return [{"label": f"账号{i}", "seed": cookie,
                 "path": os.path.join(COOKIE_DIR, f"cookie_{i}.txt")}
                for i, cookie in enumerate(rows, 1)]

    seed, cache, path = load_cookie()
    return [{"label": "", "seed": seed, "path": path}]


def parse_rooms(text):
    return [int(s) for s in text.replace(" ", "").split(",") if s.isdigit()]


class HuYaAuto:
    def __init__(self, account, rooms, dry_run=False):
        self.label = account["label"]
        self.tag = f"[{self.label}] " if self.label else ""
        self.cookie_seed = account["seed"]
        self.cookie_path = account["path"]
        self.rooms = rooms
        self.dry_run = dry_run
        self.msg_logs = []
        self.passport = ""
        self.api = None
        self.cookie_source = "env"
        self.cookie_cache = ""
        self.cookie = ""

        if self.cookie_path and os.path.exists(self.cookie_path):
            try:
                self.cookie_cache = open(self.cookie_path, encoding="utf-8").read().strip()
            except OSError as e:
                print(f"{self.tag}[WARN] 读缓存失败: {type(e).__name__}: {e}")
            if self.cookie_cache:
                # 账号顺序变了的话缓存可能对不上，按 udb_uid 校验一下
                cache_uid = parse_cookie(self.cookie_cache).get("udb_uid")
                seed_uid = parse_cookie(self.cookie_seed or "").get("udb_uid")
                if cache_uid and seed_uid and cache_uid != seed_uid:
                    print(f"{self.tag}[WARN] 缓存的账号({cache_uid})与当前 Cookie({seed_uid})"
                          f"不一致，改用当前 Cookie")
                    self.cookie_cache = ""
                else:
                    self.cookie = self.cookie_cache
                    self.cookie_source = "file"

        if not self.cookie:
            self.cookie = self.cookie_seed

    # ---------------- Cookie ----------------

    def _save_cookie(self, cookie, changed):
        if not changed or not self.cookie_path:
            return
        try:
            save_cookie_cache(self.cookie_path, cookie)
            print(f"{self.tag}[COOKIE] 登录态已写入缓存: {self.cookie_path}")
        except Exception as e:
            print(f"{self.tag}[WARN] 写缓存失败: {type(e).__name__}: {e}")

    def _drop_cookie(self):
        if self.cookie_path and drop_cookie_cache(self.cookie_path):
            print(f"{self.tag}[COOKIE] 已删除失效缓存: {self.cookie_path}")

    def _refresh_cookie(self):
        cookie, info = refresh_cookie(self.cookie, log=print)
        if info:
            self.passport = info.get("passport") or self.passport
            return cookie

        # 缓存续期失败时换另一份 Cookie 再试
        if self.cookie_source == "file":
            self._drop_cookie()
            alt, alt_source = self.cookie_seed, "env"
        else:
            alt, alt_source = self.cookie_cache, "file"

        if alt:
            print(f"{self.tag}[COOKIE] 改用 {alt_source} Cookie 重试续期")
            alt, info = refresh_cookie(alt, log=print)
            if info:
                self.passport = info.get("passport") or self.passport
                self.cookie_seed = self.cookie_cache = self.cookie = alt
                self.cookie_source = "file"

        return self.cookie

    # ---------------- 流程 ----------------

    def login(self):
        print(f"{self.tag}[LOGIN] 正在登录...")
        old_cookie = self.cookie
        self.cookie = self._refresh_cookie()
        self._save_cookie(self.cookie, changed=self.cookie != old_cookie)

        self.api = HuyaAPI(self.cookie, passport=self.passport)
        if self.api.uid <= 0:
            print(f"{self.tag}[ERROR] Cookie 里没有 udb_uid，无法登录")
            return False

        for i in range(2):
            if self.api.verify_login():
                print(f"{self.tag}[SUCCESS] 登录成功 (uid={self.api.uid})")
                if not self.api.passport:
                    print(f"{self.tag}[WARN] 未取到 passport，送礼可能失败")
                _pause(0.5, 1.5)
                return True
            if i == 0:
                print(f"{self.tag}[WARN] 登录校验失败，重试一次")
                time.sleep(2)

        print(f"{self.tag}[ERROR] 登录失败，Cookie 可能已失效")
        return False

    def get_hl_count(self):
        """查询失败返回 None，不要当成 0（否则会误跳过送礼）"""
        print(f"{self.tag}[SEARCH] 正在查询虎粮数量...")
        for attempt in range(3):
            try:
                count, bcode, items = self.api.hu_liang_count()
            except Exception as e:
                print(f"{self.tag}[WARN] 查询异常: {type(e).__name__}: {e}")
                bcode, count, items = -1, 0, []
            if bcode == 0:
                print(f"{self.tag}[COUNT] 背包 {len(items)} 项，虎粮 {count}")
                return count
            print(f"{self.tag}[WARN] 背包接口失败 bcode={bcode}，第 {attempt + 1} 次重试")
            _pause(2, 4)
        return None

    def send_to_room_in_situ(self, rid, count):
        if count <= 0:
            return "无粮跳过"
        try:
            lp, _ = self.api.room_lp_gid(rid)
            if not lp:
                return "❌ 获取参数失败"

            res = self.api.send_hu_liang(int(lp), count, dry_run=self.dry_run)
            if res.get("dryRun"):
                print(f"{self.tag}  [DRY] 流水号={res['sPayId']} sign={res['sSign']}")
                return f"🧪 房间 {rid} dry-run，{count} 个未发送"
            if res.get("ok"):
                try:
                    left = self.api.hu_liang_count()[0]
                except Exception:
                    left = "?"
                return f"🚀 房间 {rid} 送出虎粮 {count} 个，剩余 {left}"
            msg = res.get("sMsg") or f"iPayRespCode={res.get('iPayRespCode')}"
            return f"❌ 送礼失败: {msg}"
        except Exception as e:
            print(f"{self.tag}[ERROR] 房间 {rid} 送礼异常: {type(e).__name__}: {e}")
            return "❌ 过程异常"

    def daily_check_in(self, rid):
        try:
            lp, _ = self.api.room_lp_gid(rid)
            if not lp:
                return "❌ 打卡失败: 获取主播 uid 失败"

            res = {}
            for attempt in range(3):
                res = self.api.fans_sign(int(lp))
                if res.get("bcode", 0) == 0:
                    break
                print(f"{self.tag}  [CHECKIN] 接口失败 bcode={res.get('bcode')}，"
                      f"第 {attempt + 1} 次重试")
                _pause(2, 4)

            if res.get("bcode", 0) != 0:
                return f"❌ 打卡失败: 接口错误({res.get('bcode')})"
            if res.get("ok"):
                print(f"{self.tag}  [CHECKIN] 房间 {rid} 打卡成功")
                return "✅ 打卡成功"

            msg = (res.get("sMsg") or "").strip()
            if "重复打卡" in msg or "已打卡" in msg:
                print(f"{self.tag}  [CHECKIN] 房间 {rid} 今日已打卡")
                return "ℹ️ 已打卡"
            print(f"{self.tag}  [CHECKIN] 房间 {rid} 打卡失败: {msg}")
            return f"❌ 打卡失败: {msg or res.get('iCode')}"
        except Exception as e:
            print(f"{self.tag}[ERROR] 房间 {rid} 打卡异常: {type(e).__name__}: {e}")
            return "❌ 打卡异常"

    def run(self):
        if not self.cookie:
            print(f"{self.tag}[ERROR] 没有可用的 Cookie，跳过")
            self.msg_logs.append("没有可用的 Cookie")
            return

        if not self.login():
            self.msg_logs.append("登录失败")
            return

        total = self.get_hl_count()
        if total is None:
            self.msg_logs.append("虎粮查询失败，本次只打卡")
            total = 0
        else:
            self.msg_logs.append(f"今日虎粮总数: {total}")
            if total <= 0:
                print(f"{self.tag}[INFO] 暂无虎粮，跳过送礼，只做打卡")

        for i, rid in enumerate(self.rooms):
            _pause(1, 3)
            if total > 0:
                num = total // len(self.rooms) + (1 if i < total % len(self.rooms) else 0)
                print(f"{self.tag}>>> 房间: {rid} (目标数量: {num})")
                g_res = self.send_to_room_in_situ(rid, num)
                _pause(2, 5)
            else:
                print(f"{self.tag}>>> 房间: {rid} (无虎粮，仅打卡)")
                g_res = "无粮跳过"

            c_res = self.daily_check_in(rid)
            msg = f"{g_res}； {c_res}"
            print(f"{self.tag}结果: {msg}")
            self.msg_logs.append(msg)
            _pause(3, 8)


def send_notification(send_key, logs):
    if not send_key or not logs:
        return
    print("[PUSH] 正在发送推送...")
    try:
        res = requests.post(
            f"https://sctapi.ftqq.com/{send_key}.send",
            data={"title": "虎牙自动任务报告", "desp": "\n\n".join(logs)},
            timeout=10,
        )
        print("[PUSH] 推送成功" if res.status_code == 200
              else f"[PUSH] 推送失败，状态码 {res.status_code}")
    except Exception as e:
        print(f"[ERROR] 推送异常: {type(e).__name__}: {e}")


def main():
    rooms = parse_rooms(os.getenv("HUYA_ROOMS", ""))
    if not rooms:
        print("[ERROR] 未设置 HUYA_ROOMS")
        raise SystemExit(1)

    accounts = build_accounts()
    dry_run = os.getenv("HUYA_SEND_DRY_RUN", "").strip() == "1"
    print(f"[INFO] 共 {len(accounts)} 个账号，房间 {rooms}")

    logs = []
    for account in accounts:
        bot = HuYaAuto(account, rooms, dry_run)
        bot.run()
        label = account["label"]
        logs.extend(f"{label}: {m}" if label else m for m in bot.msg_logs)
        if len(accounts) > 1:
            _pause(8, 15)

    send_notification(os.getenv("SEND_KEY", "").strip(), logs)


if __name__ == "__main__":
    main()
