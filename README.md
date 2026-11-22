# 充电结束 / 被拔 提醒

电瓶车在公共扫码充电桩上充电，**没充满就被拔掉/断电**时，给你推一条提醒。

数据来源：威胜「智能充电平台」`semiot.wasion.cn` 的订单接口，靠你的 openid 识别"我的单"，
不需要抓包、不需要登录态、不会过期。

## 判定逻辑

| 平台字段 | 含义 |
| --- | --- |
| `GetInOrders` 的 `Sysc` | 进行中订单的剩余分钟 |
| `GetHisOrders` 的 `UseTimes` | 已结束订单的实际使用分钟 |
| `GetHisOrders` 的 `CostElectricit` | 充入度数 |

计划时长 = 最后一次看到该订单时的「已过分钟 + 剩余分钟」。
结束时 `UseTimes` 明显小于计划时长（容差 5 分钟）→ ⚡ 提前断电（基本就是被拔了或充满停机）；
否则 → ✅ 时间用满，正常结束。

订单从「进行中」消失但平台历史表还没更新时，等 15 分钟；仍查不到就按最后观测的剩余时间判定，
避免漏报。

## 实际跑通的证据

```
[push:ntfy] ⚡ 充电提前结束（可能被拔） 120000000012
设备 120000000012 / 开始 2026-11-22 14:41:17
实际使用 2小时15分，计划 10小时40分
⚠️ 少用了约 8小时24分，电没充满就被断电了
充入 0.39 度
推送结果 200: {"id":"iEXFPfq6L38X", ...}
```

## 运行方式（GitHub Actions，机器不用开机）

`.github/workflows/monitor.yml`：

- 每 5 分钟轮询一次，单次运行最长 5 小时 20 分（320 分钟）；
- 每轮结束前用 `GITHUB_TOKEN`（`actions: write`）**自触发下一轮**，形成 7×24 的连续轮询
  （本仓库的 `schedule` cron 长期不触发，所以用自续链兜住；`schedule` 仍保留作备用触发器）；
- 监控状态 `state.json` 通过 Actions 缓存跨轮次传递，同一订单不会重复提醒；
- 轮询步骤报错时先等 4 分钟再续链，避免空转。

**停止**：

```bash
gh workflow disable charger-alert --repo githaber666/charger-alert
```

（重新开启用 `gh workflow enable ...`；被停用后当前这一轮跑完就不再续接。）

## 收提醒

推送通道由 Secrets 决定，换通道不用改代码：

```bash
gh secret set PUSH_CHANNEL --repo githaber666/charger-alert --body serverchan
gh secret set PUSH_TOKEN   --repo githaber666/charger-alert --body "SCTxxxxxx"
```

| `PUSH_CHANNEL` | `PUSH_TOKEN` | 到哪 |
| --- | --- | --- |
| `ntfy` | topic 名 | 手机装 ntfy App 订阅该 topic（免注册，当前默认） |
| `serverchan` | Server酱 SendKey | 微信服务号「方糖」推送（sct.ftqq.com 扫码拿 key） |
| `pushplus` | PushPlus token | 微信推送（pushplus.plus 扫码拿 token） |
| `bark` | Bark key | iPhone Bark App |

`SEMIOT_OPENID` 同样是仓库 Secret，代码里不含任何个人信息。

## 本地手动跑

```bash
python monitor.py --once          # 查一次
python monitor.py --once --dry    # 只打印不推送
python monitor.py --loop 300      # 本机常驻
```

`config.json`（本地用，已 gitignore）：

```json
{
  "openid": "SEMIOT_OPENID 的值",
  "push": {"channel": "ntfy", "token": "topic"},
  "early_tolerance_min": 5,
  "missing_wait_min": 15,
  "notify_start": true
}
```

## 接口备注

```
POST https://semiot.wasion.cn/PersonnelOrder/GetInOrders?start=1&end=10&openid=<openid>
POST https://semiot.wasion.cn/PersonnelOrder/GetHisOrders?start=1&end=10&openid=<openid>
```

- `start` / `end` 都是 1 起、区间闭合；
- 只要 `openid` 参数即可取自己的订单，无需 cookie / 微信授权；
- `/PersonnelOrder/GetOrderList` 是空壳（恒返回空数组），别用。

## 已知边界

- GitHub Actions 的排队时间不确定，提醒可能延后 1~10 分钟；
- 平台历史表本身有延迟（最长十几分钟），所以加了 15 分钟的等待兜底；
- 连续 60 天仓库无提交，GitHub 会停用 `schedule` 触发器（自续链不受影响）；
- 公共仓库跑 Actions 不消耗额度，所以仓库保持 public，代码与配置都不含密钥。
