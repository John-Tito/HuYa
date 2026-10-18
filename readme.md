# 虎牙虎粮自动发放、直播间打卡
轻量、开箱即用的 **虎牙虎粮自动批量赠送、直播间打卡工具**, 支持 GitHub Actions, 并通过 [Server 酱](https://sct.ftqq.com/)推送赠送虎粮、打卡结果至微信.

---

## 功能

- Cookie、房间号通过 GitHub Secrets 管理
- 支持定时运行和手动触发
- 自动读取背包虎粮, 按房间批量分配
- 通过 GitHub Actions 计划运行
- 可选 Server 酱推送赠送和打卡结果

---

## 项目结构

```
.github/workflows/auto.yml  # GitHub Actions 配置
requirements.txt            # 依赖清单
main.py                     # 主程序
huya_api.py                 # 虎牙接口客户端
huya_cookie.py              # Cookie 续期, 可单独运行自检
tools/selftest_api.py       # 接口自检
```

---

## 部署

### 1. 获取虎牙 Cookie

1. 登录 [虎牙网页版](https://i.huya.com/index.php?m=Msg&do=getMsgC)
2. 按 F12 打开开发者工具, 切到网络, 刷新页面
3. 找到 `index.php?m=Msg&do=getMsgC` 这个请求
4. 在请求头里复制完整的 Cookie 字符串(只有 `udb_version` `udb_biztoken` `udb_cred` 三个字段也能用, 脚本会自己换出 uid.)

### 2. 获取 Server 酱 SendKey(可选)

1. 打开 [Server 酱](https://sct.ftqq.com/)
2. 注册登录, 进入"发送通道"
3. 创建一个通道, 拿到 `SendKey`

### 3. 在 GitHub 上配置

1. Fork 本仓库
2. 进入仓库的 **Settings → Secrets and variables → Actions**
3. 添加密钥:
   - `HUYA_COOKIE`: 虎牙登录 Cookie, 必须
   - `HUYA_ROOMS`: 房间号列表, 英文逗号分隔, 例如 `518512,1964,294636272`, 必须
   - `SEND_KEY`: Server 酱 SendKey, 可选
4. 进入 **Actions**, 启用工作流
5. 默认每天北京时间 07:17 自动运行

---

## 手动运行

### 在 GitHub 上运行

1. 进入仓库的 Actions
2. 选择"虎牙虎粮自动发放"
3. 点击 `Run workflow`
4. 可以输入房间号覆盖 Secrets 里的配置

### 本地运行

```bash
pip install -r requirements.txt

export HUYA_COOKIE="你的Cookie"
export HUYA_ROOMS="518512,1964"
export SEND_KEY="你的sendkey"

python main.py
```

---

## 配置项

| 名称 | 说明 |
|------|------|
| HUYA_COOKIE | 登录凭证, 必须 |
| HUYA_ROOMS | 目标房间号列表, 必须 |
| SEND_KEY | Server 酱 SendKey, 可选 |

---

## 用到的接口

背包、送礼、粉丝团打卡都是虎牙自研的 WUP(JCE) 协议, 用 HTTP POST 发到
`cdnws.api.huya.com`, 不是常见的 REST. `huya_api.py` 里做了编解码和这些调用:

| 操作 | 接口 |
|------|------|
| 登录校验 | `q.huya.com/index.php?m=PackageApi&do=getTimeSign` |
| 金豆/银豆 | `q.huya.com/index.php?m=PackageApi&do=listTotal` |
| 主播 uid / 游戏 id | `mp.huya.com/cache.php?m=Live&do=profileRoom` |
| 虎粮数量 | `wupui.getPackageGift` |
| 背包流水 | `wupui.getPackageGiftWater` |
| 送礼 | `sequenceui.getSequence` + `PropsUIServer.consumeGiftSafe` |
| 打卡 | `wupui.setFansSign` (查询用 `wupui.getFansSign`) |

送礼走背包支付(`iPayPloy=2`, 虎粮 `iItemType=4`), 签名是 md5 拼固定 appkey.
字段顺序和签名规则都照线上前端实现, 要改之前先跑一遍自检:

```bash
python tools/selftest_api.py --room 998                  # 只读: 登录/虎粮/流水/打卡状态
python tools/selftest_api.py --room 998 --send-dry-run   # 额外生成流水号和签名
python tools/selftest_api.py --room 998 --send 1         # 真送 1 个, 会扣粮
```

---

## 关于 Cookie 续期

虎牙登录态里有两个关键 Cookie: `udb_biztoken` 负责接口鉴权, 寿命较短；`udb_cred` 是长期凭证, 寿命 180 天. 网页端会在 `udb_biztoken` 失效时用 `udb_cred` 自动换新, 同时滚动 `udb_cred` 本身.

本工具复刻了这个续期请求, 每次运行前自动续期, 再用新 Cookie 调接口. 续期后的 Cookie 使用 **Actions 缓存**保存, 缓存 7 天没访问会被清理, 每天跑一次就不会过期.

本地可以单独测试续期是否正常:

```bash
HUYA_COOKIE="你的Cookie" python huya_cookie.py
```

---

## 定时任务

默认每天 UTC 23:17 运行, 对应北京时间 07:17(UTC+8), 实际运行时间会被 Github 推迟. 要修改时间, 编辑 `.github/workflows/auto.yml`:

```yaml
on:
  schedule:
    - cron: '17 23 * * *'
```

---

## 运行流程

1. 续期 Cookie, 调 PackageApi 校验登录态
2. 读背包虎粮, 按房间数平均分配
3. 每个房间: 取主播 uid → 申请支付流水号 → 送礼
4. 每个房间: 粉丝团打卡
5. 输出结果, 配了 SEND_KEY 就推送

---

## 已知限制

- 打卡要求账号已加入该主播的粉丝团, 否则接口返回"非粉丝用户打卡失败".
- 送虎粮依赖背包支付参数(`iPayPloy=2` `iItemType=4`), 虎牙换礼物体系后要重新对字段.
- 房间没开播时送礼一般会失败.
- 目前只在本地验证过, 还没在 GitHub Actions 上跑.

---

## 推送结果

推送内容类似:

```
🚀 房间 XXX 送出虎粮 X 个
打卡结果: ✅ 打卡成功 / ℹ️ 已打卡
```

---

## 注意

- 不要分享 Cookie
- 送礼和打卡之间会插入随机延时, Actions 定时运行还会随机延迟 30~210 秒
- Cookie 会自动续期. 如果日志出现"续期被拒绝", 说明 `udb_cred` 也失效了, 重新获取 Cookie 即可
- 本项目仅供学习交流, 请遵守平台规则

---

## 常见问题

- **登录失败**: 日志里"续期被拒绝"= Cookie 失效, 重新导出即可; 否则看是不是网络问题
- **送礼失败**: 先看返回的 `iPayRespCode`, 再确认背包里还有没有虎粮
- **打卡失败**: 确认这个房间有没有加入粉丝团
- **Action 报错**: 检查 Secrets 是否配置正确

---

## 许可证

MIT License
