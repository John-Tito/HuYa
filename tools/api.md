# 虎牙 API 备忘

## 协议

WUP(JCE) over HTTP POST，请求带 `servant` / `func` / `tReq`。

- 网页：`https://cdnws.api.huya.com?baseinfo=default&timestamp=<ms>`，`Content-Type: application/octet-stream`
- App / 粉丝盒：`https://wup.huya.com`，`Content-Type: application/x-wup`
- 响应 `tRsp`：`cdnws` 直接是业务字段；`wup.huya.com` 多包一层 `0`，`app_wup()` 已拆。

## 接口

| 操作 | servant.func | 关键参数 / 返回 |
|------|--------------|-----------------|
| 登录校验 | `q.huya.com/index.php?m=PackageApi&do=getTimeSign` | 未登录 501 |
| 金豆/银豆 | `q.huya.com/index.php?m=PackageApi&do=listTotal` | 需 `time` / `sign`；不含虎粮 |
| 主播 uid / 游戏 id | `mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=<rid>` | `profileInfo.uid`、`liveData.gid` |
| 虎粮背包 | `wupui.getPackageGift` | `lPid=主播uid`；只读，不触发礼包 |
| 背包流水 | `wupui.getPackageGiftWater` | `sLastOrderId`、`iOffset`；`waterType` 1 收入 2 支出 |
| 粉丝牌等级 | `liveui.queryBadgeInfoList` | `lPid`；返回 `level` |
| 粉丝盒状态 | `wupui.queryFansGroupTaskInfo` | `UserId + lPid + tag2=3` |
| 领取粉丝盒 | `wupui.operateFansBox` | 同上；返回 `iCode`、`itemCount` |
| 送礼流水号 | `sequenceui.getSequence` | `lUid`、`iSeqNum=1`、`iFromType=5`、`iBusinessType=1`、签名 |
| 送礼 | `PropsUIServer.consumeGiftSafe` | `lRoomId`、`iItemType=4`、`iItemCount`、`lPresenterUid`、`sPayId`、`sPassport`、签名 |
| 打卡状态 | `wupui.getFansSign` | `lPid`；返回 `lSignInFlag` |
| 打卡 | `wupui.setFansSign` | `lPid`；`iCode=0` 成功 |

## 关键字段

- 虎粮 `iItemType=4`；背包支付 `iPayPloy=2`；网页来源 `iFromType=5`。
- `sPayId`：`getSequence` 返回的 `sSeq`。
- 签名（md5 + appkey）：
  - 流水号：`lUid + iSeqNum + iFromType + iBusinessType + APPKEY`
  - 送礼：`lUid + lRoomId + iShowFreeitemInfo + iItemType + iItemCount + lPresenterUid + sPayId + iPayPloy + iFromType + iTemplateType + sPassport + iEventType + APPKEY`
- `sPassport`：`credLogin` 返回的 passport；精简 Cookie 里没有 `username`。

## 每日粉丝礼包

- 由**进入直播间**触发（真实房间 WebSocket 会话）；`getPackageGift(lPid)` 只读背包，不触发。
- 本项目用 `room_visit.py` 打开房间页触发。
- 流水 `source=53`；金额实测 `等级-2`（Lv5→3、Lv12→10、Lv17→15；0 级为 1），以返回 `count` 为准。
- 每个主播/粉丝牌每天一次，24 点清零。

## 粉丝盒

- `wupui.queryFansGroupTaskInfo`：请求 `UserId + lPid + tag2=3`；响应 `tRsp[0][7][0]` 状态：1 未达到 / 2 计时中 / 3 可领取 / 4 已领取。
- `wupui.operateFansBox`：同请求；响应 `tRsp[0][0]` 业务码、`tRsp[0][5]` 数量；成功 +10，流水 `source=53`。
- 必须走 `wup.huya.com` + App UserId；网页身份可查询，领取用 `app_wup()`。
- `state=4` 时直接调用仍返回 `iCode=0, count=10`，先查状态再领。
- 线上字段是 `tag 2 = 3`；写成 `tag 3 = 2` 查询能过、领取 `iCode=5`。
