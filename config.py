#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置文件：选择器、URL、延时
"""

# 登录
LOGIN = {
    "huya_num": "huyaNum",
}

# 充值背包
PAY_PAGE = {
    "pack_tab": "packTab",
    "hl_item_title": "个虎粮",
}

# 礼物相关（全部抽离，无硬编码）
GIFT = {
    "item_class": "m-gift-item",
    "input_css": "input[type='number'][placeholder='自定义']",
    "send_class": "c-send",
    "confirm_class": "btn-success",
}

# 粉丝团每日打卡
# 注意：虎牙前端用 CSS Module，类名带构建哈希（如 FanClubHd--UAIAw8vo8FGSKqVwLp7A），
# 每次发版都会变，所以统一用 [class*="前缀"] 匹配，避免失效
CHECKIN = {
    "badge": '[class*="FanClubHd"]',      # 直播间粉丝团徽章（懒加载，需显式等待）
    "panel": '[class*="FanClubBd"]',      # hover 徽章后弹出的粉丝团面板
    "task_item": '[class*="TaskItem"]',   # 面板里的任务行
    "task_title": '[class*="Title"]',     # 任务行标题
    "task_btn": 'a[class*="Btn"]',        # 任务行按钮
    "task_name": "每日打卡领福利",         # 打卡任务标题
    "disabled_class": "disabled",         # 按钮 class 含此串 = 已完成，不可再点
}

# URL
URLS = {
    "user_index": "https://i.huya.com/",
    "room_base": "https://huya.com/{}",
    "pay_index": "https://hd.huya.com/pay/index.html?source=web",
    "gift_tab": "https://hd.huya.com/web/webPackageV2/index.html?lp={lp}&gid={gid}"
}

# 延时
# 延时建议调整
TIMING = {
    "implicit_wait": 3,
    "page_load_wait": 6,     # 登录刷新后留足加载时间
    "room_enter_wait": 8,    # 直播间页面极大，给它 8 秒去加载基础 DOM
    "badge_wait": 20,        # 粉丝团徽章是懒加载组件，出现时间不稳定，显式等待上限
    "task_wait": 30,         # 面板任务行首次拉取接口较慢，等待上限
    "rehover_gap": 8,        # 重新 hover 的最小间隔：太短会打断面板的数据加载
    "badge_retry": 2,        # 徽章等不到时刷新页面重试的次数
}
