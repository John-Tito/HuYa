#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import config as cfg

class HuYaAuto:
    def __init__(self):
        # ============ 配置项 ============
        self.debug = False  # 开启调试
        self.enable_push = True  # 推送开关已开启
        # ================================

        self.msg_logs = []
        self.cookie = os.getenv('HUYA_COOKIE', '').strip()
        self.rooms = self._parse_rooms(os.getenv('HUYA_ROOMS', ''))
        self.send_key = os.getenv('SEND_KEY', '').strip()

        if not self.cookie:
            print("[ERROR] 未设置 HUYA_COOKIE"); sys.exit(1)
        if not self.rooms:
            self.rooms = [518512, 518511]

        self.driver = self._init_browser()
        self.wait = WebDriverWait(self.driver, 15)

    def _parse_rooms(self, rooms_str):
        if not rooms_str: return []
        return [int(s.strip()) for s in rooms_str.split(',') if s.strip().isdigit()]

    def _init_browser(self):
        chrome_options = Options()
        if not self.debug:
            chrome_options.add_argument('--headless=new')

        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.page_load_strategy = 'eager'

        # 可选：设置 CHROME_BINARY 时直接使用指定的 Chrome（离线/固定版本，不触发下载）
        bin_path = os.getenv('CHROME_BINARY', '').strip()
        if bin_path:
            chrome_options.binary_location = bin_path

        # 不传 Service：交给 Selenium Manager 自动获取匹配的 chromedriver；
        # 本机没装 Chrome 时它会自动下载 Chrome for Testing，
        # 并缓存到 ~/.cache/selenium（可用 SE_CACHE_PATH 改），下次运行直接复用
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)
        return driver

    def _safe_get(self, url, sleep=3):
        """导航到 url，页面加载超时时忽略异常（内容通常已就绪）"""
        try:
            self.driver.get(url)
        except TimeoutException:
            print("[WARN] 页面加载超时，尝试继续解析...")
        except Exception as e:
            print(f"[WARN] 导航异常: {e}")
        time.sleep(sleep)

    def send_notification(self):
        """新增：Server酱推送方法"""
        if not self.enable_push or not self.send_key:
            return

        print("[PUSH] 正在发送推送通知...")
        try:
            content = "\n\n".join(self.msg_logs)
            url = f"https://sctapi.ftqq.com/{self.send_key}.send"
            data = {
                "title": "虎牙自动任务报告",
                "desp": content
            }
            res = requests.post(url, data=data, timeout=10)
            if res.status_code == 200:
                print("[SUCCESS] 推送发送成功")
            else:
                print(f"[FAILED] 推送失败，状态码: {res.status_code}")
        except Exception as e:
            print(f"[ERROR] 推送异常: {e}")

    def login(self):
        print("[LOGIN] 正在登录...")
        try:
            self._safe_get(cfg.URLS["user_index"], sleep=2)
            for line in self.cookie.split(';'):
                if '=' not in line: continue
                name, val = line.split('=', 1)
                self.driver.add_cookie({'name': name.strip(), 'value': val.strip(), 'domain': '.huya.com', 'path': '/'})
            self.driver.refresh()
            self.wait.until(EC.presence_of_element_located((By.ID, cfg.LOGIN["huya_num"])))
            print("[SUCCESS] 登录成功")
            return True
        except Exception as e:
            print(f"[ERROR] 登录失败: {e}")
            return False

    def _open_pack_panel(self, lp, gid):
        """打开 payNew 的『包裹』面板，并切进内嵌的 webPackageV2 iframe。

        返回 True 时 driver 的上下文已经在该 iframe 内，调用方用完必须
        switch_to.default_content()。

        为什么要切 frame：payNew 只是外壳，包裹列表/礼物项都在 #wrapshow 的
        iframe 里，顶层 document 里既没有 .m-gift-item 也没有数量元素。
        """
        self._safe_get(cfg.URLS["gift_tab"].format(lp=lp, gid=gid),
                       sleep=cfg.TIMING["pack_load_wait"])
        try:
            pack_tab = self.wait.until(EC.element_to_be_clickable((By.ID, cfg.PAY_PAGE["pack_tab"])))
            try:
                pack_tab.click()
            except Exception:
                # 外壳页偶尔会挂一层 #popupMask 遮罩，原生点击会被拦截；JS 点击不受影响
                self.driver.execute_script("arguments[0].click();", pack_tab)
        except Exception as e:
            print(f"  [PACK] 点击『包裹』标签失败: {type(e).__name__}: {e}")
            return False
        try:
            WebDriverWait(self.driver, cfg.TIMING["frame_wait"]).until(
                EC.frame_to_be_available_and_switch_to_it(
                    (By.CSS_SELECTOR, cfg.PAY_PAGE["pack_frame"])))
            return True
        except TimeoutException:
            print("  [PACK] 未等到 webPackageV2 包裹 iframe")
            return False

    def _leave_frame(self):
        """切回顶层文档；失败也不该影响主流程。"""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def _wait_pack_data(self):
        """在包裹 iframe 内等列表渲染完（有物品，或明确显示空态）。"""
        deadline = time.time() + cfg.TIMING["pack_data_wait"]
        while time.time() < deadline:
            try:
                state = self.driver.execute_script(
                    "return {items: document.querySelectorAll(arguments[0]).length,"
                    "        empty: !!document.querySelector(arguments[1])};",
                    cfg.PAY_PAGE["pack_item"], cfg.PAY_PAGE["pack_empty"])
            except Exception:
                state = {}
            if state.get("items") or state.get("empty"):
                return True
            time.sleep(0.5)
        print("  [PACK] 包裹列表加载超时，按当前 DOM 解析")
        return False

    def get_hl_count(self):
        print("[SEARCH] 正在查询虎粮数量...")
        # 查自己背包时 lp/gid 传 0 即可：列表归属走 cookie 里的 udb_uid
        if not self._open_pack_panel(lp=0, gid=0):
            print("[ERROR] 虎粮数量识别失败: 未能进入包裹面板")
            return 0
        try:
            self._wait_pack_data()
            # 新版包裹项结构：div.m-gift-item > [i.c-count(数量), img, p(物品名)]
            n = self.driver.execute_script(
                """
                const items = document.querySelectorAll(arguments[0]);
                for (const item of items) {
                    const nameEl = item.querySelector(arguments[2]);
                    const name = (nameEl ? nameEl.textContent : '') || item.title || '';
                    if (!name.includes('虎粮')) continue;
                    const countEl = item.querySelector(arguments[1]);
                    const m = (countEl ? countEl.textContent : '').match(/\\d+/);
                    return m ? m[0] : 0;
                }
                return 0;
                """,
                cfg.PAY_PAGE["pack_item"], cfg.PAY_PAGE["pack_count"], cfg.PAY_PAGE["pack_name"])
            count = int(n) if n else 0
            print(f"[COUNT] 识别到虎粮: {count}")
            return count
        except Exception as e:
            print(f"[ERROR] 虎粮数量识别失败: {type(e).__name__}: {e}")
            return 0
        finally:
            self._leave_frame()

    def _hover_gift_item(self, item):
        """让 iframe 里的礼物项进入 hover 态（『赠送』面板靠 onMouseEnter 才渲染）。

        优先用真鼠标移动；父页面偶尔会挂遮罩（#popupMask）盖在 iframe 上方，
        真实鼠标事件会被遮罩吃掉，此时退回 JS 派发 mouseover —— React 的
        onMouseEnter 本来就是从 mouseover 合成的，效果一样。
        """
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            ActionChains(self.driver).move_to_element(body).pause(0.2).move_to_element(item).perform()
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, cfg.GIFT["panel_css"])))
            return True
        except Exception:
            pass
        try:
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new MouseEvent('mouseover',"
                "{bubbles: true, cancelable: true, view: window}));", item)
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, cfg.GIFT["panel_css"])))
            return True
        except Exception:
            return False

    def send_to_room_in_situ(self, rid, count):
        if count <= 0: return "无粮跳过"
        try:
            self._safe_get(cfg.URLS["room_base"].format(rid), sleep=5)
            lp = self.driver.execute_script('return document.body.getAttribute("data-lp")')
            gid = self.driver.execute_script('return document.body.getAttribute("data-gid")')
            if not lp or not gid: return "❌ 获取参数失败"

            # 包裹面板在 iframe 里，后面的元素查找都在该 frame 内进行
            if not self._open_pack_panel(lp=lp, gid=gid):
                return "❌ 未进入包裹面板"

            items = self.wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, cfg.GIFT["item_class"])))
            hu_liang = next((i for i in items if "虎粮" in i.text), None)
            if not hu_liang: return "❌ 未找到虎粮"

            # 只要 hover，不要 click：点礼物本身会触发一次"送 1 个"的确认弹窗
            if not self._hover_gift_item(hu_liang):
                return "❌ 赠送面板未出现"

            # 数量框是 React 受控 input，两个坑：
            # 1. 必须先 click 一下：onClick 会把选中项切成"自定义"，发送数量取的是
            #    「预设值 || 自定义值」，预设值初始为 1 —— 不点它就会永远只送 1 个；
            # 2. 它是受控组件，只能走原生 value setter + input 事件才能改写 state。
            # 全程 JS 操作，指针停在礼物上，"赠送"面板才不会被 mouseleave 收掉。
            filled = self.driver.execute_script(
                """
                const inp = document.querySelector(arguments[0]);
                if (!inp) return false;
                inp.click();                       // 选中"自定义"，否则按预设的 1 个送
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, arguments[1]);
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                return true;
                """, cfg.GIFT["input_css"], str(count))
            if not filled: return "❌ 未找到数量输入框"
            time.sleep(1)

            clicked = self.driver.execute_script(
                "const b = document.querySelector(arguments[0]);"
                "if (!b) return false; b.click(); return true;", cfg.GIFT["send_css"])
            if not clicked: return "❌ 未找到赠送按钮"
            time.sleep(cfg.TIMING["implicit_wait"])

            # 确认框里写着实际数量（"确定要送 N 个"）：对不上就取消，宁可不送也不能送错
            try:
                # 用 JS 点击：父页面的遮罩可能盖在 iframe 上方
                confirm = WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located((By.CLASS_NAME, cfg.GIFT["confirm_class"])))
            except TimeoutException:
                print(f"  [WARN] 房间 {rid} 未出现确认框（可能已直接送出）")
                confirm = None

            if confirm is not None:
                try:
                    text = self.driver.find_element(By.CSS_SELECTOR, cfg.GIFT["dialog_css"]).text
                except Exception:
                    text = ""
                matched = re.search(r"送\s*(\d+)\s*个", text)
                shown = matched.group(1) if matched else "?"
                if not matched or int(shown) != count:
                    try:
                        cancel = self.driver.find_element(By.CLASS_NAME, cfg.GIFT["cancel_class"])
                        self.driver.execute_script("arguments[0].click();", cancel)
                    except Exception:
                        pass
                    print(f"  [ERROR] 房间 {rid} 确认框数量不符: 显示 {shown}，期望 {count}")
                    return f"❌ 数量不符（弹窗 {shown} ≠ 目标 {count}），已取消"
                self.driver.execute_script("arguments[0].click();", confirm)

            print(f"  [WAIT] 正在结算房间 {rid}，原地等待 12 秒...")
            time.sleep(12)
            return f"🚀 房间 {rid} 送出虎粮 {count} 个"
        except Exception as e:
            print(f"  [ERROR] 房间 {rid} 送礼异常: {type(e).__name__}: {e}")
            return "❌ 过程异常"
        finally:
            self._leave_frame()

    def _wait_checkin_row(self):
        """等待并返回粉丝团面板里的打卡任务行，找不到返回 None。

        这里有三个坑：
        1. 面板容器约 0.2 秒就存在，但任务行要等接口返回后（冷启动可到数秒）才渲染；
        2. 面板会 re-render，抓住旧引用可能一直查不到，所以每轮都重新查询；
        3. hover 面板的数据是"进入时拉取"的，频繁 leave/enter 会把请求反复打断，
           反而永远加载不出来 —— 所以每次 hover 后必须留足加载时间再重试。
        """
        sel = cfg.CHECKIN
        deadline = time.time() + cfg.TIMING["task_wait"]
        hover_gap = cfg.TIMING["rehover_gap"]
        last_hover = 0.0

        def find_row():
            for panel in self.driver.find_elements(By.CSS_SELECTOR, sel["panel"]):
                for item in panel.find_elements(By.CSS_SELECTOR, sel["task_item"]):
                    try:
                        title = item.find_element(By.CSS_SELECTOR, sel["task_title"]).text
                    except Exception:
                        continue
                    if sel["task_name"] in title:
                        return item
            return None

        def hover_badge():
            try:
                badges = self.driver.find_elements(By.CSS_SELECTOR, sel["badge"])
                if not badges:
                    return
                # 先移到 body 再移上去：指针已停在徽章上时，直接 move_to_element
                # 不会重新触发 mouseenter，面板会停在空状态
                body = self.driver.find_element(By.TAG_NAME, "body")
                ActionChains(self.driver).move_to_element(body).pause(0.1).move_to_element(badges[0]).perform()
            except Exception:
                pass

        while time.time() < deadline:
            row = find_row()
            if row is not None:
                return row
            # 每隔 rehover_gap 秒才重新 hover 一次，中间留给面板把数据加载完
            if time.time() - last_hover >= hover_gap:
                hover_badge()
                last_hover = time.time()
            time.sleep(0.5)
        return find_row()

    def daily_check_in(self, rid):
        """粉丝团每日打卡：显式等待徽章 → hover 弹出面板 → 定位打卡任务行 → 按按钮状态判断/点击"""
        try:
            self._safe_get(cfg.URLS["room_base"].format(rid), sleep=6)

            # 1) 徽章是懒加载组件，出现时间不稳定；等不到就刷新页面重试一次
            badge_ok = False
            for attempt in range(1, cfg.TIMING["badge_retry"] + 1):
                try:
                    WebDriverWait(self.driver, cfg.TIMING["badge_wait"]).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, cfg.CHECKIN["badge"])))
                    badge_ok = True
                    break
                except TimeoutException:
                    if attempt < cfg.TIMING["badge_retry"]:
                        print(f"  [CHECKIN] 房间 {rid} 第 {attempt} 次未等到粉丝团徽章，刷新页面重试")
                        try:
                            self.driver.refresh()
                        except Exception:
                            pass
                        time.sleep(3)

            if not badge_ok:
                print(f"  [CHECKIN] 房间 {rid} 未找到粉丝团徽章（未加入粉丝团或页面未加载）")
                return "❌ 打卡失败: 无粉丝团徽章"

            # 2) hover 徽章等面板渲染，定位打卡任务行（它是第 2 个任务，不能用下标）
            row = self._wait_checkin_row()
            if row is None:
                print(f"  [CHECKIN] 房间 {rid} 面板中未找到『{cfg.CHECKIN['task_name']}』")
                return "❌ 打卡失败: 未找到打卡任务"

            try:
                btn = row.find_element(By.CSS_SELECTOR, cfg.CHECKIN["task_btn"])
            except Exception:
                print(f"  [CHECKIN] 房间 {rid} 打卡任务行没有按钮")
                return "❌ 打卡失败: 任务无按钮"

            # 3) 已完成时按钮带 disabled 类（文案变为"已完成"），不能再点
            btn_cls = btn.get_attribute("class") or ""
            if cfg.CHECKIN["disabled_class"] in btn_cls or "已完成" in btn.text:
                print(f"  [CHECKIN] 房间 {rid} 今日已打卡")
                return "ℹ️ 已打卡"

            # 4) 未完成则点击。先 hover 徽章保证面板展开，再用 ActionChains 滑到按钮点击
            try:
                ActionChains(self.driver).move_to_element(btn).pause(0.5).click().perform()
            except Exception:
                row = self._wait_checkin_row()
                if row is None:
                    return "❌ 打卡失败: 面板已收起"
                btn = row.find_element(By.CSS_SELECTOR, cfg.CHECKIN["task_btn"])
                self.wait.until(EC.element_to_be_clickable(btn)).click()

            # 5) 点击后按钮应变灰，以此确认真的成功（而不是假定成功）
            try:
                WebDriverWait(self.driver, 8).until(
                    lambda d: cfg.CHECKIN["disabled_class"] in (btn.get_attribute("class") or ""))
                print(f"  [CHECKIN] 房间 {rid} 打卡成功")
                return "✅ 打卡成功"
            except TimeoutException:
                print(f"  [CHECKIN] 房间 {rid} 已点击打卡，但按钮状态未变化，结果未知")
                return "⚠️ 打卡结果未知"

        except Exception as e:
            # 不再吞掉异常假装成功，把真实原因带出来
            print(f"  [ERROR] 房间 {rid} 打卡异常: {type(e).__name__}: {e}")
            return "❌ 打卡异常"

    def run(self):
        print("=" * 40 + f"\n[HUYA] 虎牙自动任务启动 (Debug: {self.debug})\n" + "=" * 40)
        try:
            if not self.login():
                self.msg_logs.append("登录失败")
                return
            total = self.get_hl_count()
            self.msg_logs.append(f"今日虎粮总数: {total}")

            # 打卡与虎粮数量无关：即使没有虎粮（或数量识别失败），也要进房间打卡
            if total <= 0:
                print("[INFO] 暂无虎粮，跳过送礼，仅执行打卡")
            else:
                print(f"[INFO] 共 {len(self.rooms)} 个房间，每个房间先送礼再打卡")

            for i, rid in enumerate(self.rooms):
                if total > 0:
                    num = (total // len(self.rooms) + (1 if i < (total % len(self.rooms)) else 0))
                    print(f"\n>>> 房间: {rid} (目标数量: {num})")
                    g_res = self.send_to_room_in_situ(rid, num)
                else:
                    print(f"\n>>> 房间: {rid} (无虎粮，仅打卡)")
                    g_res = "无粮跳过"

                c_res = self.daily_check_in(rid)

                msg = f"{g_res}； {c_res}"
                print(f"结果: {msg}")
                self.msg_logs.append(msg)
                time.sleep(2)
        finally:
            # 无论是否运行成功，最后都尝试推送并关闭浏览器
            if self.enable_push:
                self.send_notification()
            if hasattr(self, 'driver'):
                self.driver.quit()

if __name__ == '__main__':
    HuYaAuto().run()
