#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import random
import sys
import time

import requests

from huya_api import HuyaAPI
from huya_cookie import drop_cookie_cache, load_cookie, refresh_cookie, save_cookie_cache


def _pause(a, b):
    time.sleep(random.uniform(a, b))


class HuYaAuto:
    def __init__(self):
        self.enable_push = True
        self.msg_logs = []
        self.passport = ""
        self.api = None
        self.dry_run = os.getenv("HUYA_SEND_DRY_RUN", "").strip() == "1"

        self.cookie_env, self.cookie_cache, self.cookie_path = load_cookie()
        self.rooms = self._parse_rooms(os.getenv("HUYA_ROOMS", ""))
        self.send_key = os.getenv("SEND_KEY", "").strip()

        if self.cookie_cache:
            self.cookie = self.cookie_cache
            self.cookie_source = "file"
            print(f"[INFO] 使用缓存 Cookie: {self.cookie_path}")
        elif self.cookie_env:
            self.cookie = self.cookie_env
            self.cookie_source = "env"
            print("[INFO] 使用环境变量 Cookie")
        else:
            print("[ERROR] 没有可用的 Cookie")
            sys.exit(1)

        if not self.rooms:
            print("[ERROR] 未设置 HUYA_ROOMS")
            sys.exit(1)

    @staticmethod
    def _parse_rooms(text):
        return [int(s) for s in text.replace(" ", "").split(",") if s.isdigit()]

    # ---------------- Cookie ----------------

    def _save_cookie(self, cookie, changed):
        if not changed or not self.cookie_path:
            return
        try:
            save_cookie_cache(self.cookie_path, cookie)
            print(f"[COOKIE] 登录态已写入缓存: {self.cookie_path}")
        except Exception as e:
            print(f"[WARN] 写缓存失败: {type(e).__name__}: {e}")

    def _drop_cookie(self):
        if self.cookie_path and drop_cookie_cache(self.cookie_path):
            print(f"[COOKIE] 已删除失效缓存: {self.cookie_path}")

    def _refresh_cookie(self):
        cookie, info = refresh_cookie(self.cookie)
        if info:
            self.passport = info.get("passport") or self.passport
            return cookie

        # 缓存续期失败时换另一份 Cookie 再试
        if self.cookie_source == "file":
            self._drop_cookie()
            alt, alt_source = self.cookie_env, "env"
        else:
            alt, alt_source = self.cookie_cache, "file"

        if alt:
            print(f"[COOKIE] 改用 {alt_source} Cookie 重试续期")
            alt, info = refresh_cookie(alt)
            if info:
                self.passport = info.get("passport") or self.passport
                self.cookie_env = self.cookie_cache = self.cookie = alt
                self.cookie_source = "file"

        return self.cookie

    # ---------------- 流程 ----------------

    def login(self):
        print("[LOGIN] 正在登录...")
        old_cookie = self.cookie
        self.cookie = self._refresh_cookie()
        self._save_cookie(self.cookie, changed=self.cookie != old_cookie)

        self.api = HuyaAPI(self.cookie, passport=self.passport)
        if self.api.uid <= 0:
            print("[ERROR] Cookie 里没有 udb_uid，无法登录")
            return False

        for i in range(2):
            if self.api.verify_login():
                print(f"[SUCCESS] 登录成功 (uid={self.api.uid})")
                if not self.api.passport:
                    print("[WARN] 未取到 passport，送礼可能失败（查粮、打卡不受影响）")
                _pause(0.5, 1.5)
                return True
            if i == 0:
                print("[WARN] 登录校验失败，重试一次")
                time.sleep(2)

        print("[ERROR] 登录失败，Cookie 可能已失效")
        return False

    def get_hl_count(self):
        print("[SEARCH] 正在查询虎粮数量...")
        try:
            count, _, items = self.api.hu_liang_count()
        except Exception as e:
            print(f"[ERROR] 查询虎粮失败: {type(e).__name__}: {e}")
            return 0
        print(f"[COUNT] 背包 {len(items)} 项，虎粮 {count}")
        return count

    def send_to_room_in_situ(self, rid, count):
        if count <= 0:
            return "无粮跳过"
        try:
            lp, _ = self.api.room_lp_gid(rid)
            if not lp:
                return "❌ 获取参数失败"

            res = self.api.send_hu_liang(int(lp), count, dry_run=self.dry_run)
            if res.get("dryRun"):
                print(f"  [DRY] 流水号={res['sPayId']} sign={res['sSign']}")
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
            print(f"  [ERROR] 房间 {rid} 送礼异常: {type(e).__name__}: {e}")
            return "❌ 过程异常"

    def daily_check_in(self, rid):
        try:
            lp, _ = self.api.room_lp_gid(rid)
            if not lp:
                return "❌ 打卡失败: 获取主播 uid 失败"

            res = self.api.fans_sign(int(lp))
            if res.get("ok"):
                print(f"  [CHECKIN] 房间 {rid} 打卡成功")
                return "✅ 打卡成功"

            msg = (res.get("sMsg") or "").strip()
            if "重复打卡" in msg or "已打卡" in msg:
                print(f"  [CHECKIN] 房间 {rid} 今日已打卡")
                return "ℹ️ 已打卡"
            print(f"  [CHECKIN] 房间 {rid} 打卡失败: {msg}")
            return f"❌ 打卡失败: {msg or res.get('iCode')}"
        except Exception as e:
            print(f"  [ERROR] 房间 {rid} 打卡异常: {type(e).__name__}: {e}")
            return "❌ 打卡异常"

    def send_notification(self):
        if not self.enable_push or not self.send_key:
            return
        print("[PUSH] 正在发送推送...")
        try:
            res = requests.post(
                f"https://sctapi.ftqq.com/{self.send_key}.send",
                data={"title": "虎牙自动任务报告", "desp": "\n\n".join(self.msg_logs)},
                timeout=10,
            )
            if res.status_code == 200:
                print("[PUSH] 推送成功")
            else:
                print(f"[PUSH] 推送失败，状态码 {res.status_code}")
        except Exception as e:
            print(f"[ERROR] 推送异常: {type(e).__name__}: {e}")

    def run(self):
        print("=" * 40 + "\n[HUYA] 虎牙虎粮自动发放\n" + "=" * 40)
        try:
            if not self.login():
                self.msg_logs.append("登录失败")
                return

            total = self.get_hl_count()
            self.msg_logs.append(f"今日虎粮总数: {total}")
            if total <= 0:
                print("[INFO] 暂无虎粮，跳过送礼，只做打卡")

            for i, rid in enumerate(self.rooms):
                _pause(1, 3)
                if total > 0:
                    num = total // len(self.rooms) + (1 if i < total % len(self.rooms) else 0)
                    print(f"\n>>> 房间: {rid} (目标数量: {num})")
                    g_res = self.send_to_room_in_situ(rid, num)
                    _pause(2, 5)
                else:
                    print(f"\n>>> 房间: {rid} (无虎粮，仅打卡)")
                    g_res = "无粮跳过"

                c_res = self.daily_check_in(rid)
                msg = f"{g_res}； {c_res}"
                print(f"结果: {msg}")
                self.msg_logs.append(msg)
                _pause(3, 8)
        finally:
            if self.enable_push:
                self.send_notification()

if __name__ == "__main__":
    HuYaAuto().run()
