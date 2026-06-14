# AI 邮件代办 · 部署与使用指南（V3.0 C 方案）

> 适用版本：V3.0 · C 方案（IMAP 邮件转发接入）
> 目标用户：内部运维 + 种子客户（试用）

---

## 1. 30 秒了解

客户不需要装任何客户端。客户只需要**在邮箱里做一个"自动转发"配置**：

```
原工作流：客户  → 邮件发商家
新工作流：客户  → 邮件先转发到 aiagent@qq.com  → AI 替客户处理  → AI 用客户原邮箱回信
```

本服务跑在客户自己的服务器（或者 SaaS）上，监听 `aiagent@qq.com` 这个邮箱的 IMAP 收信。每收到一封，AI 全自动跑完整个电话+短信流程，最后 SMTP 写一封总结邮件回给客户。

---

## 2. 部署步骤

### 2.1 准备邮箱

- 申请一个专用 QQ 邮箱：`aiagent@yourcompany.com`（用企业邮或 foxmail 别名）
- 开启 **IMAP/SMTP 服务**：邮箱设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → 开启 IMAP 和 SMTP
- 生成 **授权码**（不是 QQ 密码）：QQ 邮箱会要求发短信验证，生成 16 位授权码

### 2.2 配置环境变量

```bash
# .env
IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USER=aiagent@yourcompany.com
IMAP_PASSWORD=xxxxxxxxxxxxxxxx        # 16 位授权码
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=aiagent@yourcompany.com
SMTP_PASSWORD=xxxxxxxxxxxxxxxx        # 同 IMAP 授权码
SMTP_FROM_NAME=AI 外贸代办
AIAGENT_API_BASE=http://127.0.0.1:8766
EMAIL_POLL_INTERVAL=30
APPROVED_SENDERS=li@customer.com,zhao@buyer.com    # 白名单，逗号分隔
LOG_FILE=data/email_worker.log
```

### 2.3 启动后端 API（已有则跳过）

```bash
cd aiagent-comms
./.venv/bin/python3 -m backend.main
```

### 2.4 启动邮件 worker

```bash
./scripts/start_email_worker.sh
```

输出：

```
[email_worker] starting with:
  IMAP: aiagent@yourcompany.com@imap.qq.com:993
  SMTP: aiagent@yourcompany.com@smtp.qq.com:465
  poll: 30s
  approved: li@customer.com,zhao@buyer.com
[email_worker] started, pid=12345
[email_worker] tail -f data/email_worker.log
```

停止：`./scripts/stop_email_worker.sh`

### 2.5 让客户的邮件自动转过来

客户邮箱设置 → 邮件转发 → 添加规则：
- 触发：所有外发邮件（或者带"AI代办"/"aiagent" 主题前缀的）
- 动作：转发到 `aiagent@yourcompany.com`
- 保留副本：勾选

> Gmail / Outlook / 企业邮 / QQ 邮箱的设置路径略有不同，但都有"自动转发"功能。

---

## 3. 客户使用流程

**客户每天的工作流：**
1. 写一封给商家的邮件
2. 在收件人加 `aiagent@yourcompany.com`，主题加 `[代办]` 前缀（可选）
3. 点发送
4. 等几分钟后，邮箱会收到一封 AI 处理回执

**AI 邮件的样式（回执预览）：**

```
From: AI 外贸代办 <aiagent@yourcompany.com>
To: li@customer.com
Subject: Re: 帮我订三亚海棠湾威斯汀
In-Reply-To: <原始邮件 Message-ID>

Hi 李总，

您的委托已处理完毕，状态：✅ 已成交
订单 ID：ord_xxx
场景：hotel · 商家：三亚海棠湾威斯汀

【AI 处理纪要】
已与三亚海棠湾威斯汀完成 1 项酒店代办确认

【AI 协商策略】hold_position, value_trade

【AI 表现评分】总分 88/100
  · 礼仪规范: 24/25
  · 策略合理: 22/25
  · 议价力度: 18/20
  · 效率: 14/15
  · 客户满意: 10/15

【对话回放（最近 6 轮）】
[AI] Good afternoon, this is Alex calling on behalf of a customer...
[商家] Front desk, this is Sarah speaking...
...
```

---

## 4. 安全设计

### 4.1 白名单（最关键！）

`APPROVED_SENDERS` 强制：只有列出的邮箱才能触发 AI 处理。**空白名单 = 拒收所有邮件**（demo 模式除外，会打印警告）。

```bash
APPROVED_SENDERS=li@customer.com,zhao@buyer.com
```

### 4.2 域名 / 邮箱黑名单

未来扩展：

```python
DENIED_DOMAINS=spam.com,malicious.cn
DENIED_SENDERS=blacklisted@x.com
```

### 4.3 限流

`EMAIL_POLL_INTERVAL=30` 表示每 30s 轮询一次，避免触发 IMAP 反垃圾限制。

### 4.4 凭据保护

- `.env` 不入 git
- 部署到生产用 docker secret / k8s secret
- 授权码定期轮换（QQ 邮箱支持撤销并重发）

### 4.5 SPF / DKIM / DMARC

回信 SMTP 使用 `aiagent@yourcompany.com` —— 因为是客户自己的域名，提前配好 SPF/DKIM/DMARC，回信不会进垃圾箱。

---

## 5. 联调控制台（内部用）

不接真 IMAP，用浏览器控制台直接模拟：

打开：`http://127.0.0.1:8766/static/email-console.html`

- 左侧：填一封邮件
- 右侧：实时看 AI 跑
- 下方：邮件源预览 + AI 回信预览
- 5 个快速填充样例：酒店、电线电缆、机加工、纺织、海运

这个页是 demo、调试、内部培训的"沙盒"，**生产环境不开放**。

---

## 6. E2E 验证

```bash
# 解析器单测
./.venv/bin/python3 test_email_parser.py

# API + 邮件回执联调
./.venv/bin/python3 test_email_e2e.py

# Mock IMAP/SMTP 端到端
./.venv/bin/python3 test_email_e2e_full.py
```

3 个测试都通过 = C 方案生产可用。

---

## 7. 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| 启动报 `IMAP_USER not set` | 缺 env | `export IMAP_USER=...` |
| IMAP login 失败 | 授权码错 / IMAP 未开 | 邮箱设置里重生成授权码 |
| 邮件解析乱码 | 源邮件未声明 charset | email_worker 用 `policy.default` 兜底 |
| 收不到 AI 回信 | SMTP 端口被封 / 授权码失效 | 用 `openssl s_client -connect smtp.qq.com:465` 测连通 |
| 回信进垃圾箱 | 域名未配 SPF/DKIM | 让客户联系域名服务商加 SPF |
| AI 处理超时 | 后端慢 / LLM 卡 | 看 `data/email_worker.log`，后端 `/api/health` |
| 白名单不生效 | 大小写或空格 | env 用小写，逗号分隔无空格 |

---

## 8. 路线图

| 时间 | 功能 |
|------|------|
| V3.0（当前）| IMAP 收信 + 解析 + AI + SMTP 回信 |
| V3.1 | 客户直接发邮件回复"确认/取消/转人工" → 邮件 worker 解析客户意图 |
| V3.2 | 邮件多语言（中/英/日/韩）AI 回信 |
| V3.3 | 邮件附件 OCR（PDF/图片订单）→ 解析商家回复附件 |
| V3.4 | 多邮箱支持（每个客户分配独立 aiagent@yourcompany.com） |
| V4.0 | 邮件 + 短信 + 微信 + 飞书 全渠道统一入口 |
