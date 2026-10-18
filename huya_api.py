#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""虎牙接口客户端：虎粮查询、送礼、粉丝团打卡。

这些接口是虎牙自研的 WUP(JCE) 协议，用 HTTP POST 打到 cdnws.api.huya.com，
不是常见的 REST。字段顺序和签名规则都照线上前端实现，改动前先跑一遍
tools/selftest_api.py。
"""

import hashlib
import re
import struct
import time

import requests

WUP_URL = "https://cdnws.api.huya.com?baseinfo=default&timestamp=%d"
PROFILE_URL = "https://mp.huya.com/cache.php?m=Live&do=profileRoom&roomid=%s"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_WEB = "webh5&1.0.0&huya"

APPKEY = "AzCXiouW6aLc4AsVGKAOOLlNLawNQsuV"            # 支付流水号签名
CONSUME_APPKEY = "Hi2UfWa8LhRM07ZjucWL9wzuX7okmGvd"    # 送礼签名
HU_LIANG_GIFT_ID = 4
I_FROM_TYPE_WEB = 5
I_PAY_PLOY_BAG = 2

# JCE 类型编号
EN_INT8, EN_INT16, EN_INT32, EN_INT64 = 0, 1, 2, 3
EN_FLOAT, EN_DOUBLE = 4, 5
EN_STRING1, EN_STRING4 = 6, 7
EN_MAP, EN_LIST, EN_STRUCTBEGIN, EN_STRUCTEND, EN_ZERO, EN_SIMPLELIST = 8, 9, 10, 11, 12, 13


class HuyaApiError(Exception):
    pass


class JceWriter:
    """字段头一个字节，高 4 位 tag、低 4 位类型（和标准 Tars 相反）"""

    def __init__(self):
        self.b = bytearray()

    def _head(self, tag, typ):
        if tag < 15:
            self.b.append((tag << 4) | typ)
        else:
            self.b.append(0xF0 | typ)
            self.b.append(tag)

    def int8(self, tag, v):
        if v == 0:
            self._head(tag, EN_ZERO)
        else:
            self._head(tag, EN_INT8)
            self.b += struct.pack(">b", v)

    def int16(self, tag, v):
        if -128 <= v <= 127:
            self.int8(tag, v)
        else:
            self._head(tag, EN_INT16)
            self.b += struct.pack(">h", v)

    def int32(self, tag, v):
        if -32768 <= v <= 32767:
            self.int16(tag, v)
        else:
            self._head(tag, EN_INT32)
            self.b += struct.pack(">i", v)

    def int64(self, tag, v):
        if -(2 ** 31) <= v <= 2 ** 31 - 1:
            self.int32(tag, v)
        else:
            self._head(tag, EN_INT64)
            self.b += struct.pack(">q", v)

    def string(self, tag, s):
        raw = (s or "").encode("utf-8")
        if len(raw) > 255:
            self._head(tag, EN_STRING4)
            self.b += struct.pack(">I", len(raw))
        else:
            self._head(tag, EN_STRING1)
            self.b.append(len(raw))
        self.b += raw

    def raw_bytes(self, tag, data):
        self._head(tag, EN_SIMPLELIST)
        self._head(0, EN_INT8)
        self.int32(0, len(data))
        self.b += data

    def struct(self, tag, fn):
        self._head(tag, EN_STRUCTBEGIN)
        fn(self)
        self._head(0, EN_STRUCTEND)

    def map_empty(self, tag):
        self._head(tag, EN_MAP)
        self.int32(0, 0)


class JceReader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def head(self):
        b = self.d[self.p]
        self.p += 1
        tag = b >> 4
        typ = b & 0x0F
        if tag >= 15:
            tag = self.d[self.p]
            self.p += 1
        return tag, typ

    def _int(self, typ):
        if typ == EN_ZERO:
            return 0
        fmt, size = {EN_INT8: (">b", 1), EN_INT16: (">h", 2),
                     EN_INT32: (">i", 4), EN_INT64: (">q", 8)}[typ]
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return v

    def _count(self):
        tag, typ = self.head()
        if tag != 0:
            raise HuyaApiError(f"expect tag 0, got {tag}")
        return self._int(typ)

    def _field(self):
        tag, typ = self.head()
        return {"tag": tag, "value": self.value(typ)}

    def value(self, typ):
        if typ in (EN_INT8, EN_INT16, EN_INT32, EN_INT64, EN_ZERO):
            return self._int(typ)
        if typ == EN_FLOAT:
            v = struct.unpack_from(">f", self.d, self.p)[0]
            self.p += 4
            return v
        if typ == EN_DOUBLE:
            v = struct.unpack_from(">d", self.d, self.p)[0]
            self.p += 8
            return v
        if typ in (EN_STRING1, EN_STRING4):
            if typ == EN_STRING1:
                n = self.d[self.p]
                self.p += 1
            else:
                n = struct.unpack_from(">i", self.d, self.p)[0]
                self.p += 4
            raw = bytes(self.d[self.p:self.p + n])
            self.p += n
            return raw.decode("utf-8", "replace")
        if typ == EN_MAP:
            n = self._count()
            return [{"k": self._field(), "v": self._field()} for _ in range(n)]
        if typ == EN_LIST:
            return [self._field() for _ in range(self._count())]
        if typ == EN_SIMPLELIST:
            _, elem = self.head()
            n = self._count()
            if elem != EN_INT8:
                raise HuyaApiError(f"unsupported simplelist type {elem}")
            raw = bytes(self.d[self.p:self.p + n])
            self.p += n
            return {"bytes": raw}
        if typ == EN_STRUCTBEGIN:
            out = {}
            while True:
                tag, t = self.head()
                if t == EN_STRUCTEND:
                    return out
                out[tag] = self.value(t)
        raise HuyaApiError(f"bad jce type {typ} at {self.p}")


def _struct(raw):
    r = JceReader(raw)
    _, typ = r.head()
    return r.value(typ)


def _int_attr(raw):
    r = JceReader(raw)
    _, typ = r.head()
    return r._int(typ)


def json_safe(obj):
    """解码结果里的 bytes 转成字符串，方便打印"""
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.hex()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj


# ---------------- WUP 封包 ----------------

def wup_encode(servant, func, req_fields, request_id=1):
    """req_fields 是请求体字段，外面再包一层 struct(0x0a ... 0x0b)"""
    body = bytearray(b"\x0a") + bytes(req_fields) + b"\x0b"

    buf = JceWriter()
    buf._head(0, EN_MAP)
    buf.int32(0, 1)
    buf.string(0, "tReq")
    buf.raw_bytes(1, bytes(body))

    head = JceWriter()
    head.int16(1, 3)              # iVersion
    head.int8(2, 0)               # cPacketType
    head.int32(3, 0)              # iMessageType
    head.int32(4, request_id)
    head.string(5, servant)
    head.string(6, func)
    head.raw_bytes(7, bytes(buf.b))
    head.int32(8, 0)              # iTimeout
    head.map_empty(9)             # context
    head.map_empty(10)            # status

    payload = bytes(head.b)
    return struct.pack(">i", 4 + len(payload)) + payload


def wup_decode(data):
    """返回 (头部字段, 响应体)；响应体是 {"": bcode, "tRsp": 结构体}"""
    r = JceReader(data, 4)
    head = {}
    for _ in range(10):
        tag, typ = r.head()
        head[tag] = r.value(typ)

    body = JceReader(head[7]["bytes"])
    _, typ = body.head()
    if typ != EN_MAP:
        raise HuyaApiError("unexpected response body")

    attrs = {}
    for _ in range(body._count()):
        k = body._field()["value"]
        v = body._field()["value"]
        attrs[k] = v.get("bytes", v) if isinstance(v, dict) else v
    return head, attrs


# ---------------- 客户端 ----------------

def _cookie_value(cookie, name, default=""):
    for part in (cookie or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
    return default


class HuyaAPI:
    def __init__(self, cookie, passport=None, timeout=20, log=print):
        self.cookie = (cookie or "").strip()
        self.uid = int(_cookie_value(self.cookie, "udb_uid", "0") or 0)
        # 送礼签名要 sPassport；精简导出的 Cookie 里没有 username，用 credLogin 的返回值补
        self.passport = passport or _cookie_value(self.cookie, "username")
        self.timeout = timeout
        self.log = log
        self._req_id = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # ---------------- 底层 ----------------

    def _retry(self, fn, attempts=3, what="请求"):
        last = None
        for i in range(attempts):
            try:
                return fn()
            except (requests.RequestException, HuyaApiError) as e:
                last = e
                if i + 1 < attempts:
                    self.log(f"  [API] {what} 失败({type(e).__name__})，重试")
                    time.sleep(1.2 * (i + 1))
        raise last

    def wup(self, servant, func, fields_writer):
        """调一个 WUP 方法，返回 (bcode, 响应结构体或 None)"""
        body = JceWriter()
        fields_writer(body)
        self._req_id += 1
        pkt = wup_encode(servant, func, bytes(body.b), request_id=self._req_id)

        resp = self._retry(lambda: self.session.post(
            WUP_URL % int(time.time() * 1000), data=pkt, timeout=self.timeout,
            headers={"Content-Type": "application/octet-stream",
                     "Origin": "https://hd.huya.com",
                     "Referer": "https://hd.huya.com/"},
        ), what=f"{servant}.{func}")
        resp.raise_for_status()

        _, attrs = wup_decode(resp.content)
        bcode = _int_attr(attrs[""]) if "" in attrs else -1
        rsp = attrs.get("tRsp")
        return bcode, (_struct(rsp) if rsp else None)

    def _with_user(self, extra):
        def write(w):
            w.struct(0, self._write_user)
            extra(w)
        return write

    def _write_user(self, w):
        w.int64(0, self.uid)
        w.string(1, "")
        w.string(2, "")
        w.string(3, UA_WEB)
        w.string(4, self.cookie)
        w.int32(5, 0)
        w.string(6, "")

    def _get(self, url):
        headers = {"Referer": "https://www.huya.com/"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        return self.session.get(url, headers=headers, timeout=self.timeout)

    # ---------------- 登录与余额 ----------------

    def verify_login(self):
        """登录态校验，未登录时接口返回 501"""
        try:
            data = self._retry(lambda: self._get(
                "https://q.huya.com/index.php?m=PackageApi&do=getTimeSign"),
                what="getTimeSign").json()
            return data.get("status") == 200 and bool((data.get("data") or {}).get("time"))
        except Exception as e:
            self.log(f"  [API] 登录校验出错: {type(e).__name__}: {e}")
            return False

    def bean_balance(self):
        """金豆、银豆、虎牙券，不含虎粮"""
        sign = (self._get("https://q.huya.com/index.php?m=PackageApi&do=getTimeSign")
                .json().get("data") or {})
        data = (self._get("https://q.huya.com/index.php?m=PackageApi&do=listTotal"
                          f"&time={sign.get('time')}&sign={sign.get('sign')}")
                .json().get("data") or {})
        return {k: (data.get(k) or {}).get("num")
                for k in ("goldbean", "silverBean", "goldbeanTicket")}

    # ---------------- 房间 ----------------

    def room_lp_gid(self, rid):
        """lp 是主播 uid，gid 是游戏分类 id"""
        try:
            data = self._get(PROFILE_URL % rid).json().get("data") or {}
            lp = (data.get("profileInfo") or {}).get("uid")
            gid = (data.get("liveData") or {}).get("gid")
            if lp not in (None, "") and gid not in (None, ""):
                return str(lp), str(gid)
        except Exception as e:
            self.log(f"  [API] profileRoom 失败: {type(e).__name__}: {e}")

        # 接口取不到就读房间页服务端渲染的 body 属性
        try:
            html = self._get(f"https://huya.com/{rid}").text
            body = (re.search(r"<body[^>]*>", html) or [""])[0]
            lp = re.search(r'data-lp="([^"]*)"', body)
            gid = re.search(r'data-gid="([^"]*)"', body)
            if lp and gid:
                return lp.group(1), gid.group(1)
        except Exception as e:
            self.log(f"  [API] 房间页抓取失败: {type(e).__name__}: {e}")
        return None, None

    # ---------------- 背包 ----------------

    def package(self):
        """背包列表"""
        bcode, data = self.wup("wupui", "getPackageGift",
                               self._with_user(lambda w: w.int64(1, 0)))
        if bcode != 0 or not data:
            return bcode, []

        items = []
        for row in data.get(0) or []:
            detail = row["value"]
            info = detail.get(0) or {}
            items.append({
                "name": info.get(3, ""),
                "itemType": info.get(0, 0),
                "count": detail.get(5, 0),
                "expireDayCount": detail.get(2, 0),
                "expireTime": detail.get(3, 0),
            })
        return bcode, items

    def hu_liang_count(self, name="虎粮"):
        """返回 (数量, bcode, 背包列表)"""
        bcode, items = self.package()
        return sum(i["count"] for i in items if name in i["name"]), bcode, items

    def water(self, offset=0, last_order_id=""):
        """背包流水，waterType 1 收入 2 支出"""
        def extra(w):
            w.string(1, last_order_id)
            w.int32(2, offset)

        bcode, data = self.wup("wupui", "getPackageGiftWater", self._with_user(extra))
        if bcode != 0 or not data:
            return bcode, []

        gift = {e["k"]["value"]: e["v"]["value"] for e in data.get(2) or []}
        source = {e["k"]["value"]: e["v"]["value"] for e in data.get(3) or []}
        rows = []
        for row in data.get(6) or []:
            w = row["value"]
            rows.append({
                "name": (gift.get(w.get(0)) or {}).get(3, str(w.get(0))),
                "giftType": w.get(0),
                "count": w.get(3),
                "waterType": w.get(1),
                "source": source.get(w.get(2), w.get(2)),
                "time": w.get(4),
            })
        return bcode, rows

    # ---------------- 打卡 ----------------

    def fans_sign_state(self, lpid):
        bcode, data = self.wup("wupui", "getFansSign",
                               self._with_user(lambda w: w.int64(1, lpid)))
        if bcode != 0 or not data:
            return {"iCode": bcode, "sMsg": "wup 失败"}
        info = data.get(2) or {}
        return {"iCode": data.get(0, -1), "sMsg": data.get(1, ""),
                "iPos": info.get(0), "lPosTime": info.get(1),
                "lSignInFlag": info.get(2)}

    def fans_sign(self, lpid):
        """打卡，iCode 为 0 才算成功"""
        bcode, data = self.wup("wupui", "setFansSign",
                               self._with_user(lambda w: w.int64(1, lpid)))
        if bcode != 0 or not data:
            return {"ok": False, "iCode": bcode, "sMsg": "wup 失败"}
        return {"ok": data.get(0) == 0, "iCode": data.get(0), "sMsg": data.get(1, "")}

    # ---------------- 送礼 ----------------

    def get_sequence(self, seq_num=1, business_type=1):
        """申请支付流水号，送礼时作为 sPayId"""
        sign = hashlib.md5(
            f"{self.uid}{seq_num}{I_FROM_TYPE_WEB}{business_type}{APPKEY}".encode()
        ).hexdigest()

        def fields(w):
            w.struct(0, self._write_user)
            w.int32(1, seq_num)
            w.int32(2, I_FROM_TYPE_WEB)
            w.int32(3, business_type)
            w.string(4, sign)

        bcode, data = self.wup("sequenceui", "getSequence", fields)
        if bcode != 0 or not data or not data.get(1):
            raise HuyaApiError(f"getSequence 失败: bcode={bcode} rsp={data}")
        return data.get(1)

    def send_hu_liang(self, anchor_uid, count, room_id=0,
                      gift_id=HU_LIANG_GIFT_ID, dry_run=True):
        """送虎粮（背包支付）。dry_run 只生成流水号和签名，不发包"""
        if count <= 0:
            return {"ok": False, "msg": "数量为 0"}

        seq = self.get_sequence()
        payload = {
            "tId": self.uid, "lRoomId": room_id, "iShowFreeitemInfo": 0,
            "iItemType": gift_id, "iItemCount": count,
            "lPresenterUid": anchor_uid, "lHomeOwnerUid": anchor_uid,
            "sPayId": seq, "sSendContent": "", "iPayPloy": I_PAY_PLOY_BAG,
            "iFromType": I_FROM_TYPE_WEB, "sExpand": "", "iTemplateType": 5,
            "sPassport": self.passport, "iEventType": 2, "iUseType": 0,
        }
        sign = hashlib.md5((
            f"{payload['tId']}{payload['lRoomId']}{payload['iShowFreeitemInfo']}"
            f"{payload['iItemType']}{payload['iItemCount']}{payload['lPresenterUid']}"
            f"{payload['sPayId']}{payload['iPayPloy']}{payload['iFromType']}"
            f"{payload['iTemplateType']}{payload['sPassport']}{payload['iEventType']}"
            f"{CONSUME_APPKEY}"
        ).encode()).hexdigest()

        if dry_run:
            return {"ok": False, "dryRun": True, "sPayId": seq, "sSign": sign,
                    "payload": payload}

        def fields(w):
            w.struct(0, self._write_user)          # tId
            w.int64(1, payload["lRoomId"])
            w.int32(2, payload["iShowFreeitemInfo"])
            w.int32(3, payload["iItemType"])
            w.int32(4, payload["iItemCount"])
            w.int64(5, payload["lPresenterUid"])
            w.int64(6, payload["lHomeOwnerUid"])
            w.string(7, payload["sPayId"])
            w.string(8, payload["sSendContent"])
            w.int32(9, payload["iPayPloy"])
            w.int32(10, payload["iFromType"])
            w.string(11, payload["sExpand"])
            w.int32(12, payload["iTemplateType"])
            w.string(13, payload["sPassport"])
            w.int16(14, payload["iEventType"])
            w.string(15, sign)
            w.int32(16, payload["iUseType"])
            w.int32(17, 0)                         # iMergeDeliver
            w.int32(18, 0)                         # iMultiSend

        bcode, data = self.wup("PropsUIServer", "consumeGiftSafe", fields)
        if bcode != 0 or data is None:
            return {"ok": False, "iPayRespCode": bcode, "sPayId": seq,
                    "sSign": sign, "sMsg": "wup 失败"}
        return {"ok": data.get(0) == 0, "iPayRespCode": data.get(0),
                "sPayId": seq, "sSign": sign, "sMsg": data.get(11, ""),
                "rsp": json_safe(data)}
