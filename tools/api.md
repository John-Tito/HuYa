# 接口备忘（仅本地，不入库）

这份文件被 .gitignore 忽略，用来记录实现细节，readme 里不写这些内容。

## 协议

虎牙的背包、送礼、粉丝团打卡都是自研的 WUP(JCE) RPC，不是 REST。
编码用 JCE 变体，HTTP 发到：

```
POST https://cdnws.api.huya.com?baseinfo=default&timestamp=<ms>
```

包里带 `servant` / `func`，实现见 `huya_api.py`。

## 用到的接口

| 操作 | servant.func |
|------|--------------|
| 登录校验 | `q.huya.com/index.php?m=PackageApi&do=getTimeSign`（未登录 501） |
| 金豆/银豆 | `q.huya.com/index.php?m=PackageApi&do=listTotal`（不含虎粮） |
| 主播 uid / 游戏 id | `mp.huya.com/cache.php?m=Live&do=profileRoom` |
| 虎粮数量 | `wupui.getPackageGift`（取「虎粮」的 lTotalCount） |
| 背包流水 | `wupui.getPackageGiftWater`（waterType 1 收入 2 支出） |
| 送礼 | `sequenceui.getSequence` → `PropsUIServer.consumeGiftSafe` |
| 打卡 | `wupui.setFansSign`（查询用 `wupui.getFansSign`） |

## 关键参数

- 送礼是背包支付：`iPayPloy=2`，虎粮 `iItemType=4`
- `sPayId` = `getSequence` 返回的 `sSeq`
- 签名：md5 拼固定 appkey
  - 流水号：`lUid + iSeqNum + iFromType + iBusinessType + APPKEY`
  - 送礼：`lUid + lRoomId + iShowFreeitemInfo + iItemType + iItemCount + lPresenterUid
    + sPayId + iPayPloy + iFromType + iTemplateType + sPassport + iEventType + APPKEY`
- `sPassport` 取 credLogin 返回的 passport（精简 Cookie 里没有 `username`）
- 打卡 `lPid` 是主播 uid，`iCode == 0` 成功；`-1 + 请勿重复打卡` = 今天打过了

## 实测记录（2026-10-18）

- 打卡：`iCode=0`，`getFansSign.lSignInFlag` 从 0 变 64
- 送礼：`iPayRespCode=0`「扣费成功」，虎粮 52→51，流水同步新增一条支出
- 背包为空时 `getPackageGift` 返回空列表（bcode 0），不是错误
- **房间没开播也能送**（998 是离线状态，送礼成功）——readme 里那句「需要正常开播」是错的
- 送礼与打卡都已用真实账号验证

## 排错

- WUP 返回非 0 时日志会打印 `[WUP] servant.func bcode=... 描述`
- `905`：UserId 结构信息与 Cookie 对不上，通常是 Cookie/uid 不匹配，重新导出
- 其它码：多半是瞬时失败，代码里已重试 3 次
- 打卡接口失败会在结果里显示 `接口错误(<bcode>)`

## 自检

```bash
python tools/selftest_api.py --room 998                  # 只读
python tools/selftest_api.py --room 998 --send-dry-run   # 生成流水号与签名，不发包
python tools/selftest_api.py --room 998 --send 1         # 真发 1 个，会扣粮
```

Cookie 优先取 `HUYA_COOKIE`，其次 `.huya_cookie/*.txt`；
只有 `udb_version/udb_biztoken/udb_cred` 的 Cookie 也能用，脚本会先 credLogin 换出 uid/passport。

## 缓存文件

- 单账号：`.huya_cookie/cookie.txt`
- 多账号：`.huya_cookie/cookie_1.txt`、`cookie_2.txt`…（按 HUYA_COOKIES 的行序）
- 缓存里的 `udb_uid` 与当前 Cookie 不一致时会忽略缓存，避免调换顺序后用错账号
- Actions 保存条件用 `find .huya_cookie -name "*.txt"`（多账号文件名不是 cookie.txt）

## 重新挖接口

接口改版时：

1. 打开直播间页，注入 hook 记录 WebSocket 出站帧（旧的 `tools/mine_api.py` 已从仓库移除，可从 git 历史里取）
2. 用 `huya_api` 里的 JCE 解码器把帧还原成 `servant.func + 请求体`
3. 字段顺序改动后，先跑 `selftest_api.py --send-dry-run` 确认签名通过，再小额真发
