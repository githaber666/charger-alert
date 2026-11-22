# -*- coding: utf-8 -*-
"""
充电结束 / 被拔 微信提醒 —— 监控主程序

判定逻辑（基于平台真实字段）：
  进行中订单 Sysc = 剩余分钟；已结束订单 UseTimes = 实际使用分钟数。
  计划时长 = 最后一次看到订单时的(已过分钟 + 剩余分钟)。
  UseTimes >= 计划-5  → 用满时间，正常结束
  UseTimes <  计划-5  → 提前结束（被拔 / 充满停机）
用法：
  python monitor.py --once            跑一次（供 cron / GitHub Actions 用）
  python monitor.py --loop 300        本机常驻，每 300 秒一次
  python monitor.py --once --dry      只打印，不推送
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from semiot import Semiot, parse_time, fmt_min

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
CFG_FILE = os.path.join(HERE, "config.json")

DEFAULT_CFG = {
    "openid": "",
    "push": {"channel": "ntfy", "token": ""},
    "notify_start": True,
    "early_tolerance_min": 5,
    "missing_wait_min": 15,
}


# ---------------- 配置 / 状态 ----------------
def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    if os.environ.get("SEMIOT_OPENID"):
        cfg["openid"] = os.environ["SEMIOT_OPENID"]
    if os.environ.get("PUSH_CHANNEL"):
        cfg["push"]["channel"] = os.environ["PUSH_CHANNEL"]
    if os.environ.get("PUSH_TOKEN"):
        cfg["push"]["token"] = os.environ["PUSH_TOKEN"]
    if os.environ.get("NOTIFY_START"):
        # 关掉"开始充电"那条提醒，只在结束时推送，省推送额度
        cfg["notify_start"] = os.environ["NOTIFY_START"].strip().lower() in ("1", "true", "yes", "on")
    return cfg


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sessions": {}, "closed": [], "last_poll": None}


def save_state(st):
    st.setdefault("sessions", {})
    st.setdefault("closed", [])
    st["closed"] = st.get("closed", [])[-50:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


# ---------------- 推送 ----------------
def push(cfg, title, body, dry=False):
    ch = (cfg.get("push") or {}).get("channel", "")
    tok = (cfg.get("push") or {}).get("token", "")
    print(f"[push:{ch}] {title}\n{body}\n")
    if dry or not ch:
        return
    import requests
    try:
        if ch == "ntfy":
            # 无需注册：手机装 ntfy App 后订阅同名 topic 即可
            r = requests.post(f"https://ntfy.sh/{tok}", data=body.encode("utf-8"),
                              headers={"Title": title.encode("utf-8").decode("latin-1", "replace"),
                                       "Tags": "electric_plug", "Priority": "high"}, timeout=20)
        elif ch == "serverchan":
            r = requests.post(f"https://sctapi.ftqq.com/{tok}.send",
                              data={"title": title, "desp": body}, timeout=20)
        elif ch == "pushplus":
            r = requests.post("https://www.pushplus.plus/send",
                              json={"token": tok, "title": title, "content": body.replace("\n", "<br>"),
                                    "template": "html"}, timeout=20)
        elif ch == "bark":
            r = requests.post(f"https://api.day.app/{tok}",
                              json={"title": title, "body": body, "group": "充电"}, timeout=20)
        else:
            print("未知推送通道:", ch)
            return
        print(f"推送结果 {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print("推送失败:", e)


# ---------------- 核心 ----------------
def check(cfg, st, dry=False):
    api = Semiot(cfg["openid"])
    now = datetime.now()

    in_res = api.in_orders()
    cur = {}
    for o in in_res.get("data", []):
        no = str(o.get("OrderNo"))
        if no and no != "None":
            cur[no] = o

    # 1) 记录/更新进行中的单
    for no, o in cur.items():
        rec = st.setdefault("sessions", {}).setdefault(no, {"first_seen": now.isoformat(timespec="seconds"),
                                             "notified_start": False})
        rec.update({
            "device": o.get("DeviceNumber"),
            "payment_time": o.get("PaymentTime"),
            "last_seen": now.isoformat(timespec="seconds"),
            "last_sysc": o.get("Sysc"),
            "pay_type": o.get("PayType"),
            "pay_amount": o.get("PayAmount"),
        })
        if cfg.get("notify_start") and not rec.get("notified_start"):
            rec["notified_start"] = True
            push(cfg, f"🔌 开始充电 {o.get('DeviceNumber')}",
                 f"设备 {o.get('DeviceNumber')}\n开始时间 {o.get('PaymentTime')}\n"
                 f"剩余 {fmt_min(o.get('Sysc') or 0)}\n充满或结束时我会再提醒你。", dry)

    # 2) 检测结束的单
    wait_min = cfg.get("missing_wait_min", 15)
    for no, rec in list(st.setdefault("sessions", {}).items()):
        if no in cur or no in st["closed"]:
            rec.pop("missing_since", None)
            continue
        his = api.find_his(no)
        if his is None:
            # 进行中列表里没了、历史表又还没更新：可能是历史表延迟
            # 先记下第一次发现"消失"的时间；超过 wait_min 仍查不到就直接按剩余时间判定并发提醒
            rec.setdefault("missing_since", now.isoformat(timespec="seconds"))
            gone = (now - (parse_time(rec["missing_since"]) or now)).total_seconds() / 60
            if gone < wait_min:
                continue
            tol0 = cfg.get("early_tolerance_min", 5)
            left = rec.get("last_sysc") or 0
            early0 = left > tol0
            device0 = rec.get("device")
            head0 = f"{'⚡ 充电提前结束（可能被拔）' if early0 else '✅ 充电结束（时间用满）'} {device0}"
            push(cfg, head0,
                 f"设备 {device0}\n开始 {rec.get('payment_time')}\n"
                 f"订单已从「进行中」消失，最后观测还剩 {fmt_min(left)}"
                 + ("\n⚠️ 还剩时间就断了，基本是被拔了" if early0 else "")
                 + "\n（平台历史表暂未更新，按剩余时间判定）", dry)
            st["closed"].append(no)
            st["sessions"].pop(no, None)
            continue
        # 计划时长 = 最后一次观测时的已过分钟 + 剩余分钟
        pt = parse_time(rec.get("payment_time") or "")
        ls = parse_time(rec.get("last_seen") or "") or now
        plan = None
        if pt:
            plan = (ls - pt).total_seconds() / 60 + (rec.get("last_sysc") or 0)
        rec.pop("missing_since", None)
        used = his.get("UseTimes")
        kwh = his.get("CostElectricit")
        tol = cfg.get("early_tolerance_min", 5)

        if used is not None and plan:
            early = used < plan - tol
        else:
            early = (rec.get("last_sysc") or 0) > tol  # 兜底：结束时还剩时间

        end_t = parse_time(his.get("PaymentTime") or "")  # 平台不给结束时间，用开始+使用时长推算
        device = his.get("DeviceNumber") or rec.get("device")
        head = f"{'⚡ 充电提前结束（可能被拔）' if early else '✅ 充电结束（时间用满）'} {device}"
        lines = [f"设备 {device}",
                 f"开始 {rec.get('payment_time')}"]
        if used is not None:
            lines.append(f"实际使用 {fmt_min(used)}" + (f"，计划 {fmt_min(plan)}" if plan else ""))
            if early and plan:
                lines.append(f"⚠️ 少用了约 {fmt_min(plan - used)}，电没充满就被断电了")
        if kwh:
            lines.append(f"充入 {kwh} 度")
        push(cfg, head, "\n".join(lines), dry)

        st["closed"].append(no)
        st["sessions"].pop(no, None)

    st["last_poll"] = now.isoformat(timespec="seconds")
    print(f"[{now:%H:%M:%S}] 进行中 {len(cur)} 单"
          + (f"：{', '.join(cur)}" if cur else "")
          + f" | 跟踪中 {len(st['sessions'])} | 已结束累计 {len(st['closed'])}")
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="秒；本机常驻轮询间隔")
    ap.add_argument("--minutes", type=float, default=0,
                    help="配合 --loop：最多跑这么多分钟就退出（GitHub Actions 续链用）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--test-push", action="store_true", help="只发一条测试提醒，验证推送通道")
    a = ap.parse_args()

    cfg = load_cfg()
    if a.test_push:
        push(cfg, "🔌 充电提醒测试",
             "推送通道配置成功。\n以后充电开始、以及没充满就被拔掉/断电时，都会推给你。", a.dry)
        return
    st = load_state()
    if a.loop:
        deadline = time.time() + a.minutes * 60 if a.minutes else None
        while True:
            try:
                check(cfg, st, a.dry)
                save_state(st)
            except Exception as e:
                print("本轮出错:", type(e).__name__, e)
            if deadline and time.time() >= deadline:
                print("已到本轮运行时长上限，退出等待下一次接续。")
                break
            sleep_s = a.loop
            if deadline:
                sleep_s = max(5, min(sleep_s, deadline - time.time()))
            time.sleep(sleep_s)
    else:
        check(cfg, st, a.dry)
        save_state(st)


if __name__ == "__main__":
    main()

