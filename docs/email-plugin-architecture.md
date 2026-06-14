# V3.0 邮件插件架构 · 方案 A (QQ 邮箱插件) + C (邮件转发) 组合

> 目标：**客户不用登任何网站，在自己邮箱里就能委托 AI 处理跨境商家沟通。**
>
> V3.1 调整：删去 Outlook / Gmail 插件路线，改用 **QQ 邮箱插件**（更符合中国外贸商户使用习惯）。

## 0. 全景

```
┌─────────────────────┐                ┌─────────────────────┐
│  客户邮箱            │                │  境外商家            │
│  (QQ 邮箱 / 163 /    │                │  (酒店/货代/采购)   │
│   Gmail Web 备选)    │                │                      │
└──────────┬──────────┘                └──────────┬──────────┘
           │ ① 客户写邮件                       ↑ ④ AI 替客户打电话
           │ "帮我改 6.12 双床"                  │ / 发邮件
           ↓                                     │
┌─────────────────────┐                ┌─────────────────────┐
│  接入层              │ ── IMAP 收 ──→ │  AI 后端             │
│  C 方案：邮件转发     │                │  (V3.0 已就位)      │
│  A 方案：QQ 邮箱插件   │                │                      │
│  163 邮箱 / Gmail     │                │  - 真 LLM 决策        │
│  (备选)              │                │  - 20 场景词库       │
└─────────────────────┘                │  - V2.1 评估         │
           ↑                            │  - WebSocket 推      │
           │ ⑤ SMTP 回信                  │                      │
           │ 包含：AI 处理纪要 + 确认按钮  └──────────────────────┘
           ↓
      客户读邮件 → 确认 → AI 给商家发确认
```

---

## 1. 方案 C：邮件转发（1 周 MVP）

### 1.1 客户使用流程

1. 客户配邮箱规则（一次性）：
   - Gmail：Settings → Filters → "if To: contains 'aiagent' → forward to aiagent@ourdomain.com"
   - Outlook：Rules → "Forward all mail sent to aiagent@ourdomain.com to aiteam@ourdomain.com"
2. 客户写邮件：
   ```
   To: aiagent@ourdomain.com
   Subject: 委托 AI · 大阪酒店改单
   
   帮我把大阪心斋桥大和鲁内酒店的入住改成 6.12 双床+免费早餐。
   不可加价。如果原日期满了可以接受 6.11 或 6.13。
   
   [下面是跟酒店的往来邮件，从这里开始转发]
   ```
3. 客户把跟酒店的历史邮件 forward 到 aiagent@ourdomain.com
4. 我们的 IMAP 收件 → 解析 → 跑 AI
5. AI 给酒店打电话/发邮件（用 Twilio/阿里云，将来接入）
6. AI 通过 SMTP reply 给客户，主题改成 `Re: 委托 AI · 大阪酒店改单`
7. 邮件正文包含：
   - AI 处理纪要
   - 商家回复摘要 + 翻译
   - 评估分数（5 维）
   - 「确认」按钮（HTML mailto: link）
8. 客户回复「确认」→ AI 发正式确认给酒店
9. 客户回复「转人工」→ 推送给人工客服

### 1.2 技术栈

- **Python stdlib `imaplib` + `smtplib`** — 零依赖
- **email 标准库** — 解析 MIME/多部分
- **email.utils** — 解析 From/To/Subject/Date
- **后台进程** — `python -m backend.email_worker` 持续轮询
- **多邮箱支持** — 同时监听 Gmail / QQ邮箱 / 163邮箱

### 1.3 安全

- **SPF / DKIM / DMARC** 配置（防进垃圾箱）
- **白名单**：只处理 `from ∈ approved_senders` 的邮件
- **一次性 Token**：每封邮件生成短 token，回复时验证
- **速率限制**：每客户 60 封/小时上限
- **审计日志**：所有邮件都存档 36 个月（合规要求）

### 1.4 1 周交付

- D1-2：IMAP/SMTP 客户端 + 多邮箱适配
- D3：邮件解析（指令提取 + 附件下载 + 邮件链还原）
- D4：AI 流程触发器（解析后调后端 API）
- D5：SMTP 回复（纪要格式 + 评估嵌入）
- D6-7：白名单 + 速率限制 + 端到端验证

---

## 2. 方案 A：QQ 邮箱插件（1 周 MVP + 1 月正式上架）

### 2.1 客户使用流程

1. 客户登录 QQ 邮箱 → 设置 → 实验室 → 启用「**AI 外贸代办**」插件
2. 打开任意邮件 → 顶部出现「委托 AI 处理」按钮
3. 点按钮 → 弹窗显示「委托 AI 处理此邮件」
4. 可选：填指令、约束、目标商家
5. 点确认 → 插件调后端 API 创建订单
6. 后端跑 AI 流程（与 C 方案同一条路径）
7. **WebSocket 实时推送到插件浮窗**：状态变化、商家回复、评估结果
8. 插件浮窗显示 AI 进度：
   - "正在解析需求..." 30%
   - "AI 选策略: alt_date" 60%
   - "商家已让步到 ¥0 加价" 80%
   - "AI 评分: 76/100" 100%
9. 客户在插件里点「确认」→ 调后端 API 给商家发确认
10. 客户在插件里点「转人工」→ 推送给客服

### 2.2 QQ 邮箱插件形态

QQ 邮箱开放平台（[openmail.qq.com](https://openmail.qq.com)）提供：
- **应用号**（轻量级插件，1 周上架）
- **邮箱小程序**（更复杂，2-4 周）
- **Foxmail 插件**（PC 客户端，2-4 周）

我们选 **QQ 邮箱应用号**（最快最广）。

### 2.3 技术栈

- **QQ 邮箱应用号**（H5 + JS SDK）
- **OAuth 2.0** 鉴权（用户授权后我们可读他邮件）
- **WebSocket** 实时通信
- **chrome.storage 等价物** = QQ 邮箱 LocalStorage API

### 2.4 1 周交付

- D1-2：QQ 邮箱应用号注册 + manifest + 浮窗 UI
- D3：邮件读取 JS SDK 接入
- D4：调后端 API 鉴权 + 提交订单
- D5：WebSocket 实时推 + 状态浮窗
- D6-7：E2E 验证 + 提审 QQ 邮箱

### 2.5 备选插件形态（V3.2 扩展）

如果 QQ 邮箱应用号审核慢，可以并行做：
- **163 邮箱插件**（外贸商户用 163 也很多）
- **Foxmail 客户端插件**（腾讯企业邮的桌面端）
- **通用 Web 邮件小书签**（JavaScript bookmarklet，0 审核）

这些都是中国市场优先，不做 Outlook/Gmail。

---

## 3. 主邮件账号策略

我们用 **1 个统一邮箱**接所有客户委托：

```
模式 1（推荐 MVP）：客户自己 forward
  客户在邮箱配规则: forward to aiagent@ourdomain.com
  我们的 aiagent@ 收到 → 解析 from 字段 → 关联 org

模式 2（生产）：每个客户独立子邮箱
  客户用专门邮箱: chen@chen-customers.aiagent.com
  我们的 MX 服务器接 → 自动分配到该客户
  客户不用配转发规则

模式 3（QQ 邮箱插件）：客户在 QQ 邮箱装插件
  插件直接读邮件（OAuth 授权）→ 调我们后端
  客户连转发都不用配
```

模式 1+3 是 V3.0 MVP，模式 2 是商用。

---

## 4. 邮件协议数据流

```
Inbound email:
  From: chen@bolong.com
  To: aiagent@ourdomain.com
  Subject: 委托 AI · 大阪酒店改单
  Body: "帮我把...改成 6.12..."
  Attachments: hotel-thread.eml (含商家历史邮件)
    ↓
  parsed to OrderCreate {
    organization: "大阪心斋桥大和鲁内酒店",
    contact_number: "+81661234567", (从邮件链提取)
    requirement: "帮我把...改成 6.12...",
    constraints: "不可加价",
    preferred_channel: "voice",
    scenario: "hotel",
    industry: null,
  }
    ↓
  POST /api/orders (带 token, 自动关联 org)
    ↓
  跑 AI 流程（同 V3.0 已有）
    ↓
  WebSocket 推送（扩展订阅 OR 邮件监听）
    ↓
Outbound email (reply):
  From: aiagent@ourdomain.com
  To: chen@bolong.com
  Subject: Re: 委托 AI · 大阪酒店改单 · 已完成
  Body: AI 纪要 + 评估 + 确认链接
```

---

## 5. 优先级（已根据最新要求调整）

- **C 方案 MVP**（1 周）—— 真实可发邮件就能用
- **A 方案 QQ 邮箱应用号插件**（1 周 MVP + 1 月正式上架）
- ~~A 方案 Outlook 插件~~ —— **不做**
- ~~A 方案 Gmail 插件~~ —— **不做**
- A 方案备选（V3.2）：163 邮箱插件 / Foxmail 客户端插件 / Web 邮件 bookmarklet

中国市场优先，不做海外邮箱插件。
