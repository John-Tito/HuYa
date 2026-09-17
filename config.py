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
# 注意：payNew 只是外壳页，真正的包裹列表是 webPackageV2 这个 React 应用，
# 它被挂在 #wrapshow 的 iframe 里 —— 顶层 document 既没有包裹列表也没有礼物项，
# 必须先 switch_to.frame 才能找到元素。
PAY_PAGE = {
    "pack_tab": "packTab",
    "hl_item_title": "个虎粮",
    # 只匹配 src 已经指向 webPackageV2 的 iframe：静态 HTML 里还有一个 src="" 的空
    # iframe，直接等 "#wrapshow iframe" 会切到 about:blank
    "pack_frame": '#wrapshow iframe[src*="webPackageV2"]',
    "pack_list": ".g-package-list",                # 包裹列表容器
    "pack_item": ".g-package-list .m-gift-item",   # 单个背包物品
    "pack_count": "i.c-count",                     # 数量（>999 时显示 "999+"）
    "pack_name": "p",                              # 物品名（如"虎粮"）
    "pack_empty": ".g-empty",                      # 空态占位（背包为空）
}

# 礼物相关（全部抽离，无硬编码）
# 这些类名都属于 iframe 里的 webPackageV2 应用：
#   悬停 m-gift-item → 出现 g-present-content（赠送面板，内含自定义数量输入框）
#   点 .c-send（赠送）→ 弹确认框 → 点 .btn-success（立即送出）
GIFT = {
    "item_class": "m-gift-item",
    "panel_css": ".g-present-content",                     # 悬停礼物后才出现的赠送面板
    "input_css": "input[type='number'][placeholder='自定义']",
    "send_css": ".g-present-content .c-send",              # 面板里的"赠送"
    "dialog_css": ".g-model",                              # 确认弹窗（文案里有实际数量）
    "confirm_class": "btn-success",                        # 确认弹窗的"立即送出"
    "cancel_class": "btn-cancel",                          # 确认弹窗的"我再想想"
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
    # 必须带 source=web：payNew 会把它透传成 iframe 的 fromType，而 iframe 里
    # roomInfo.isIcenter = (fromType == "icenter")，一旦是 icenter，点击礼物就是空操作。
    # {lp}/{gid} 由 room 页 body 的 data-lp / data-gid 提供（查背包时传 0 即可，
    # 背包列表的归属其实是 cookie 里的 udb_uid）。
    "gift_tab": "https://hd.huya.com/web/payNew/index.html?source=web&package=1&lp={lp}&hasVideo=0&gid={gid}&panelType=wrap"
}

# 延时
# 延时建议调整
TIMING = {
    "implicit_wait": 3,
    "page_load_wait": 6,     # 登录刷新后留足加载时间
    "room_enter_wait": 8,    # 直播间页面极大，给它 8 秒去加载基础 DOM
    "pack_load_wait": 6,     # payNew 外壳页的加载时间
    "frame_wait": 20,        # 等内嵌的 webPackageV2 iframe 出现并切入
    "pack_data_wait": 25,    # 包裹列表接口渲染上限
    "badge_wait": 20,        # 粉丝团徽章是懒加载组件，出现时间不稳定，显式等待上限
    "task_wait": 30,         # 面板任务行首次拉取接口较慢，等待上限
    "rehover_gap": 8,        # 重新 hover 的最小间隔：太短会打断面板的数据加载
    "badge_retry": 2,        # 徽章等不到时刷新页面重试的次数
}
