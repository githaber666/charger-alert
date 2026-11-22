# 充电结束 / 被拔 微信提醒

盯的是**你自己在威胜智能充电平台上的订单**，不针对某个桩。充电中订单消失即判定结束，
并用平台的真实字段区分"时间用满正常结束"和"提前被拔断电"。

## 判定原理（平台真实字段，已实测）

| 接口 | 作用 |
|---|---|
| `POST /PersonnelOrder/GetInOrders?start=1&end=10&openid=<OPENID>` | 进行中的订单，`Sysc`=剩余分钟 |
| `POST /PersonnelOrder/GetHisOrders?start=1&end=20&openid=<OPENID>` | 已结束订单，`UseTimes`=实际使用分钟数、`CostElectricit`=度数 |

- 计划时长 = 最后一次看到该单时的（已过分钟 + 剩余分钟）
- `UseTimes >= 计划-5` → ✅ 时间用满，正常结束
- `UseTimes <  计划-5` → ⚡ 提前断电（被拔 / 充满停机），并告知少用了多少

**关键点：openid 就是身份，不需要 cookie、不需要微信登录、不会过期。**
openid 对同一公众号永久不变，所以整套程序零维护。

## 文件

- `semiot.py` —— 平台接口封装
- `monitor.py` —— 轮询 + 状态机 + 推送（`--once` / `--loop 300` / `--dry`）
- `config.json` —— 本地配置（openid、推送通道）
- `.github/workflows/monitor.yml` —— 每 5 分钟自动跑

## 推送通道

`config.json` 里 `push.channel` 可选 `ntfy` / `serverchan` / `pushplus` / `bark`：

- **ntfy（当前默认，零注册）**：手机装 ntfy App → Subscribe to topic → 填你自选的 topic（已存进 GitHub Secrets 的 PUSH_TOKEN）
- **serverchan（直接进微信）**：sct.ftqq.com 微信扫码 → 复制 SendKey 填进 `token`
- **pushplus（直接进微信）**：pushplus.plus 微信扫码 → 复制 token

## 本地手动跑

```bash
python monitor.py --once --dry     # 只看结果不推送
python monitor.py --loop 300       # 本机常驻，每 5 分钟一次
```

## 部署到 GitHub Actions（本仓库已配好）

1. Settings → Secrets and variables → Actions，新建：
   - `SEMIOT_OPENID` = 你的 openid
   - `PUSH_CHANNEL` = `ntfy`（或 `serverchan` / `pushplus` / `bark`）
   - `PUSH_TOKEN` = 对应 token / topic
2. 仓库保持 **public**：公开仓库的 Actions 分钟数免费不限；私有仓库免费额度只有 2000 分钟/月，5 分钟一次会超。代码里不含任何密钥（密钥都在 Secrets）。
3. 默认每 5 分钟运行；可在 `monitor.yml` 里改 `cron`（GitHub 最短 5 分钟，且实际有 1~10 分钟排队延迟）。

## 已知边界

- GitHub 定时任务可能延迟 1~10 分钟（平台限流时更长），不是秒级实时。
- 平台历史订单表有几十秒~1 分钟延迟，程序会自动等下一轮再确认。
- 若某次轮询正好跨过"订单结束"，计划时长用最后观测值推算，误差在轮询间隔内。
- 公开仓库若连续 60 天没有任何提交，GitHub 会自动停用定时任务；随便提交一次即恢复。
