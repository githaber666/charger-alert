# -*- coding: utf-8 -*-
"""
威胜/智能充电平台 个人订单读取（openid 免登录版）

原理：站点 /PersonnelOrder/GetInOrders 与 /GetHisOrders 用 URL 里的 openid 作为身份，
不校验 cookie / session / 微信授权。openid 对同一公众号永久不变，因此**一次拿到，长期可用**。

实测接口（2026-11-22）：
  POST https://semiot.wasion.cn/PersonnelOrder/GetInOrders?start=1&end=5&openid=<OPENID>
       -> {"success":1,"data":[{"OrderNo":..,"DeviceNumber":..,"PaymentTime":"2026-11-22 14:41:17",
                                "Sysc":608,  # 剩余分钟
                                "PayType":"免支付","PayInstructions":"购买小时","PayAmount":0.0, ...}]}
  POST https://semiot.wasion.cn/PersonnelOrder/GetHisOrders?start=1&end=10&openid=<OPENID>
       -> 已结束订单，含 "UseTimes": 实际使用分钟数, "CostElectricit": 度数, "Sysc":0
"""
import requests
from datetime import datetime

BASE = "https://semiot.wasion.cn"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
      "WindowsWechat(0x63090a13) XWEB/16133")


class Semiot:
    def __init__(self, openid, timeout=20):
        self.openid = openid
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                               "X-Requested-With": "XMLHttpRequest",
                               "Referer": BASE + "/PersonnelOrder/Index"})

    # ---- 内部 ----
    def _post(self, path, start, end):
        url = f"{BASE}{path}?start={start}&end={end}&openid={self.openid}"
        r = self.s.post(url, data="", timeout=self.timeout)
        r.raise_for_status()
        txt = (r.text or "").strip()
        if not txt:
            return {"success": 0, "message": "空响应", "data": []}
        try:
            j = r.json()
        except Exception:
            return {"success": 0, "message": "非JSON: " + txt[:200], "data": []}
        if j.get("data") is None:
            j["data"] = []
        return j

    # ---- 公开 ----
    def in_orders(self, start=1, end=10):
        """进行中的订单列表"""
        return self._post("/PersonnelOrder/GetInOrders", start, end)

    def his_orders(self, start=1, end=20):
        """已结束的订单列表（最新在前）"""
        return self._post("/PersonnelOrder/GetHisOrders", start, end)

    def find_his(self, order_no, end=20):
        for o in self.his_orders(1, end).get("data", []):
            if str(o.get("OrderNo")) == str(order_no):
                return o
        return None


def parse_time(s):
    """'2026-11-22 14:41:17' -> datetime（服务器时间为北京时间口径）"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def fmt_min(m):
    m = int(round(m))
    if m < 60:
        return f"{m}分钟"
    return f"{m // 60}小时{m % 60}分" if m % 60 else f"{m // 60}小时"


if __name__ == "__main__":
    import json, sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    oid = sys.argv[1] if len(sys.argv) > 1 else "<YOUR_OPENID>"
    api = Semiot(oid)
    print("== 进行中 ==")
    print(json.dumps(api.in_orders(), ensure_ascii=False, indent=1))
    print("== 已结束(最近5条) ==")
    print(json.dumps(api.his_orders(1, 5), ensure_ascii=False, indent=1))
