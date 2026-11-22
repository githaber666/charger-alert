# charger-alert

电瓶车在公共扫码桩上充电，最怕没充满就被人拔掉。这个工具每 5 分钟读一次**你自己**的充电订单，订单结束时对比"实际充了多久"和"本该充多久"，把结论推到微信。

数据来自威胜「智能充电平台」（`semiot.wasion.cn`）的订单接口，用你自己的 `openid` 识别"我的单"。不需要抓包换取登录态、不需要服务器长期在线，整套东西跑在 GitHub Actions 上。

完整步骤见 **[docs/使用手册.md](docs/使用手册.md)**。这里只放最短路径。

## 判断逻辑

| 平台字段 | 含义 |
| --- | --- |
| `GetInOrders` 的 `Sysc` | 进行中订单的剩余分钟 |
| `GetHisOrders` 的 `UseTimes` | 已结束订单的实际使用分钟 |
| `GetHisOrders` 的 `CostElectricit` | 充入度数 |

计划时长 = 最后一次看到该订单时的「已过分钟 + 剩余分钟」。结束后若 `UseTimes` 比计划少 5 分钟以上 → ⚡ 提前断电（基本就是被拔）；否则 ✅ 时间用满。

订单从「进行中」消失但平台历史表还没更新时，等 15 分钟；仍查不到就按最后观测的剩余时间判定，避免漏报。

## 最短上手

```bash
git clone https://github.com/<your-name>/charger-alert.git
cd charger-alert
pip install requests
cp config.example.json config.json     # 填入你的 openid
python monitor.py --once --dry
PUSH_CHANNEL=serverchan PUSH_TOKEN=<SendKey> python monitor.py --test-push
```

`openid` 的取法、推送通道的选择、GitHub Secrets 的填法，全部在[使用手册](docs/使用手册.md)里。

## 推送通道

由 `PUSH_CHANNEL` 与 `PUSH_TOKEN` 决定，换通道不用改代码。

| `PUSH_CHANNEL` | `PUSH_TOKEN` | 送到哪 |
| --- | --- | --- |
| `serverchan` | Server酱 SendKey | 微信服务号「方糖」（sct.ftqq.com 扫码取 key） |
| `pushplus` | PushPlus token | 微信（pushplus.plus 扫码取 token） |
| `ntfy` | 自建 topic 名 | ntfy App 通知，免注册 |
| `bark` | Bark key | iPhone Bark App |

省推送额度：把仓库变量 `NOTIFY_START` 设为 `false`（Settings > Secrets and variables > Actions > Variables），就只推结束提醒，一次充电只占 1 条。

## 运行方式

`.github/workflows/monitor.yml`：单次运行执行 `monitor.py --loop 300 --minutes 320`，每 5 分钟查一次、最长跑 5 小时 20 分；每轮结束前用 `GITHUB_TOKEN`（需 `actions: write`）自触发下一轮，形成连续轮询。`state.json` 走 Actions 缓存跨轮传递，同一订单不重复提醒。

`schedule` 触发器保留作备用。部分仓库的 cron 长期不触发，所以主力是自续链。

`.github/workflows/smoke.yml` 是手动自检：只跑一次 `--dry`，不推送，用来确认 Secret 填对、openid 有效、接口通。

**暂停**：`gh workflow disable charger-alert --repo <your-name>/charger-alert`（当前这轮跑完就停）。

## 本地手跑

```bash
python monitor.py --once         # 查一次
python monitor.py --once --dry   # 只打印不推送
python monitor.py --test-push    # 发一条测试提醒
python monitor.py --loop 300     # 本机常驻
```

## 接口备注

```
POST https://semiot.wasion.cn/PersonnelOrder/GetInOrders?start=1&end=10&openid=<openid>
POST https://semiot.wasion.cn/PersonnelOrder/GetHisOrders?start=1&end=10&openid=<openid>
```

`start` / `end` 从 1 起、区间闭合，每页最多 10 条。只要 `openid` 参数即可读自己的订单，无需 Cookie 或微信授权。`/PersonnelOrder/GetOrderList` 是空壳（恒返回空数组），不要用。

## 已知边界

- GitHub 排队时间不固定，提醒可能延迟几分钟到十几分钟。
- 平台历史表本身有延迟，所以加了 15 分钟等待兜底。
- 公共仓库跑 Actions 不消耗额度，故建议仓库保持 public；代码里不含任何密钥。
- 连续 60 天无提交时 GitHub 会停用 `schedule` 触发器（自续链不受影响）。

## 免责

仅用于读取你自己的充电订单。不要用别人的 `openid`，那等于读取他人账户数据。请求间隔请保持在分钟级。

## License

MIT
