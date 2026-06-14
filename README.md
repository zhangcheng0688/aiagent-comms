# AI 全权代办沟通 · aiagent-comms

> **跨境出行业务的「AI 全权电话+短信双语代办」底座**
> 用户用中文一句话提需求，AI 自主与境外商家多轮沟通，处理语言障碍 + 商务敬语 + 加价协商，**有结果再给用户**。

[![Status](https://img.shields.io/badge/status-V2.1-success)]() [![LLM](https://img.shields.io/badge/LLM-MiniMax--M3-blue)]() [![License](https://img.shields.io/badge/license-MIT-internal)]()

---

## 🎬 30 秒看明白

| 用户 | AI | 商家 |
|---|---|---|
| "帮我改入住 6.12 双床+免费早餐，**不可加价**" | 🔁 多轮日语沟通：先坚持 → 探邻日 → 锁定让步 | 大阪心斋桥大和鲁内酒店 |
| "I need an economy car for 3 days at the airport." | 🔁 一次 chain_offer 打包换车型 | Hertz Honolulu |
| "Please change my flight to June 15, peak season upgrade." | 🔁 chain_offer 化解 +42% 大幅加价 | ANA |

**全程无需用户介入**，AI 自主选策略 + 生成对方语言话术 + 评估商家是否让步 + 升级到用户当超过阈值。

---

## ✨ 核心特性

- 🌍 **4 语言 · 3 场景** — 中/日/英/韩 × 酒店/租车/机票
- 🧠 **真 LLM 决策** — 走 Mavis 托管的 MiniMax-M3，不是规则回放
- 🤝 **6 策略协商** — hold_position / alt_date / value_trade / chain_offer / loyalty / walk_away
- 📊 **V2.1 AI 表现评估** — 每单 5 维评分 + 雷达图 + 改进建议
- 🛡️ **降级安全网** — LLM 不可用时自动切 V1.2 规则
- 📈 **场景化升级阈值** — 机票 ¥30k 加价 vs 租车 ¥240 加价含义不同
- 👥 **多租户** — User/Org 模型 + Bearer token 鉴权 + org 隔离
- 🖥️ **运营后台** — /admin 看订单列表 + 详情 + 雷达图

---

## 🚀 5 分钟跑起来

### 1. 克隆 & 装依赖

```bash
cd aiagent-comms
./.venv/bin/python3 -m pip install -r requirements.txt
```

### 2. 启动主服务（FastAPI + 全部 API + 静态前端）

```bash
./.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8766
```

启动后会看到：

```
🚀 AI 全权代办沟通 V2.1 启动 http://127.0.0.1:8766
   前台: /static/submit.html  后台: /static/admin.html
```

### 3. 启动演示服务（仅前端静态 + demo/pitch 入口，可选）

```bash
./.venv/bin/python3 demo_server.py
# → http://127.0.0.1:8767/demo.html
# → http://127.0.0.1:8767/pitch-deck.html
```

### 4. 打开浏览器

| 入口 | URL | 用途 |
|---|---|---|
| **前台下单** | http://127.0.0.1:8766/static/submit.html | 客户提交代办 |
| **运营后台** | http://127.0.0.1:8766/static/admin.html | 运营看订单 |
| **API 文档** | http://127.0.0.1:8766/docs | Swagger UI |
| **演示页** | http://127.0.0.1:8767/demo.html | 4 case 互动演示 |
| **Pitch Deck** | http://127.0.0.1:8767/pitch-deck.html | 种子客户 1 页 |
| **健康检查** | http://127.0.0.1:8766/api/health | 服务存活 |
| **指标** | http://127.0.0.1:8766/api/metrics | 运营数据 |

### 5. Mavis 用户的特殊便利

如果你跑在 Mavis Code 里，**`MAVIS_ACCESS_TOKEN` 环境变量自动可用**，LLM 直接走真 MiniMax-M3：
- 不需要 `LLM_API_KEY`
- 鉴权由 daemon 转发
- 实测延迟：1-2s/次

---

## 📐 架构

```
┌────────────────────────────────────────────────────────────┐
│                       Frontend (HTML)                       │
│  submit.html │ order.html │ admin.html │ demo.html │ ...  │
└────────────────────┬───────────────────────────────────────┘
                     │ fetch /api/*
┌────────────────────▼───────────────────────────────────────┐
│                    FastAPI 0.115 (main.py)                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Auth:  /api/auth/{register,login,me}                 │ │
│  │ Order: /api/orders/*                                 │ │
│  │ Observability: /api/health, /api/metrics             │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  Dialogue    │  │  Negotiation │  │   Evaluator      │ │
│  │  Engine      │←→│  Context     │  │  (V2.1)          │ │
│  │  (FSM)       │  │  6 策略      │  │  5 维评分        │ │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘ │
│         │                 │                    │            │
│  ┌──────▼─────────────────▼────────────────────▼─────────┐ │
│  │  Intent Parser │ LLM Negotiator │ LLM Client          │ │
│  │  (3 场景规则)  │ (M3 真决策)    │ (Anthropic format)  │ │
│  └──────────────────┬──────────────────────────────────────┘ │
└─────────────────────┼───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌────────────┐
   │ SQLite  │  │ MiniMax  │  │  Twilio /  │
   │ 4 表    │  │ M3 (LLM) │  │  阿里云 SMS│
   └─────────┘  └──────────┘  └────────────┘
```

---

## 📂 项目结构

```
aiagent-comms/
├── backend/                       # 后端（Python 3.11）
│   ├── main.py                    # FastAPI 入口，15 个路由
│   ├── config.py                  # 全局配置（env-driven）
│   ├── models.py                  # Pydantic 数据模型
│   ├── storage.py                 # SQLite 存储层（4 表 + 12 CRUD + metrics 聚合）
│   ├── auth.py                    # A2 用户/租户 + 鉴权
│   ├── llm_client.py              # Mavis 托管 LLM 客户端（Anthropic 格式）
│   ├── core/
│   │   ├── dialogue.py            # 多轮对话引擎（含 _negotiate 循环）
│   │   ├── state_machine.py       # 10 状态 FSM
│   │   ├── intent_parser.py       # 3 场景意图拆解（规则 + LLM 兜底）
│   │   ├── translator.py          # 翻译抽象（DeepL/Google/LLM）
│   │   ├── negotiation.py         # 协商上下文 + 升级阈值
│   │   ├── llm_negotiator.py      # V2.0 LLM 驱动策略选择
│   │   └── evaluator.py           # V2.1 5 维 AI 表现评分
│   ├── knowledge/
│   │   ├── hotel_templates.py     # 酒店场景话术
│   │   ├── car_rental_templates.py# 租车场景话术
│   │   ├── flight_templates.py    # 机票场景话术（含 IVR 穿透）
│   │   └── negotiation_strategies.py  # 6 策略 + 场景阈值
│   └── channels/
│       ├── voice.py               # 语音通道（mock + Twilio 集成）
│       ├── sms.py                 # 短信通道（mock + 阿里云占位）
│       └── mock_merchant.py       # 模拟商家（3 场景 + 6 策略触发）
│
├── frontend/                      # 前端（Vanilla JS，0 构建）
│   ├── index.html
│   ├── submit.html                # 下单
│   ├── order.html                 # 订单详情
│   ├── negotiate.html             # 反提案选择
│   ├── admin.html                 # A3 运营后台（深色主题）
│   ├── demo.html                  # V2.0 演示页（4 case 互动）
│   └── pitch-deck.html            # 种子客户 1 页 pitch
│
├── docs/
│   ├── report/
│   │   ├── AI-Agent-V2.0-真机演示报告.pdf
│   │   └── v21_eval_results.json
│   └── screenshots/               # 11 张产品截图
│
├── test_*.py                      # 7 个端到端测试
├── demo_server.py                 # 演示静态服务（端口 8767）
├── INTEGRATION_TWILIO.md          # Twilio 集成 10 步指南
├── requirements.txt
└── README.md                      # 本文件
```

---

## 🔌 API 速查

### 行业词库（V3.0 新增）

```bash
# 列出所有行业
curl http://127.0.0.1:8766/api/industries

# 列出某行业的所有场景
curl http://127.0.0.1:8766/api/industries/cable/scenarios

# 自动检测行业+场景
curl -X POST http://127.0.0.1:8766/api/industries/detect \
  -H "Content-Type: application/json" \
  -d '{"text":"XLPE 电缆 4mm² 议价 5%"}'
# → {"text":"...","industry":"cable","scenario":"price_negotiation"}

# 获取 Prompt 注入片段
curl "http://127.0.0.1:8766/api/industries/cable/prompt-injection?scenario=price_negotiation&lang=ja"
```

### WebSocket 实时推送（V3.0 新增）

```javascript
// 前端订阅订单状态变化
const ws = new WebSocket(`ws://127.0.0.1:8766/ws?order_id=${orderId}`);
ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  // event.type: status_changed | evaluation_ready | dialogue_turn | escalated
  // event.status: success | failed | needs_user | in_progress
  console.log(event);
};
```

### 4 行业 × 5 场景矩阵

| 行业 | 场景 |
|---|---|
| **cable** 线缆 | sample_confirm · order_modify · reconciliation · price_negotiation · claim_dispute |
| **machinery** 机械 | sample_confirm · order_modify · reconciliation · price_negotiation · claim_dispute |
| **textile** 纺织 | sample_confirm · order_modify · reconciliation · price_negotiation · claim_dispute |
| **logistics** 物流 | sample_confirm · order_modify · reconciliation · price_negotiation · claim_dispute |

每场景含：≥8 关键词 + 商务套话（英/日/韩/中）+ 硬规则关键词 + 升级阈值（pct/¥/rounds）

### 鉴权（A2）

```bash
# 注册
curl -X POST http://127.0.0.1:8766/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"org_name":"上海博隆贸易","email":"chen@bolong.com","password":"test1234","name":"陈总"}'

# 登录
curl -X POST http://127.0.0.1:8766/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"chen@bolong.com","password":"test1234"}'
# → {"token": "xxx", "user": {...}, "org": {...}, "expires_at": "..."}

# 携带 token
curl http://127.0.0.1:8766/api/auth/me -H "Authorization: Bearer xxx"
```

### 订单

```bash
# 提交需求
curl -X POST http://127.0.0.1:8766/api/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "organization": "大阪心斋桥大和鲁内酒店",
    "contact_number": "+81661234567",
    "requirement": "帮我改入住 6.12 双床+免费早餐",
    "constraints": "不可加价",
    "preferred_channel": "voice",
    "scenario": "hotel"
  }'

# 查询详情（含 V2.1 评估）
curl http://127.0.0.1:8766/api/orders/$ID -H "Authorization: Bearer $TOKEN"

# 列表
curl "http://127.0.0.1:8766/api/orders?limit=20" -H "Authorization: Bearer $TOKEN"
```

### 可观测性（A4）

```bash
# 健康检查
curl http://127.0.0.1:8766/api/health
# → {"status": "ok", "version": "V2.1", "uptime_seconds": 123, "ts": "..."}

# 指标（按 org 隔离）
curl http://127.0.0.1:8766/api/metrics -H "Authorization: Bearer $TOKEN"
# → {"orders": {"total": 5, "success_rate": 80, "by_status": {...}}, "ai_quality": {"avg_evaluation_total": 65.7}, "scope": "org"}
```

---

## 🧠 V2.1 AI 表现评估（核心壁垒）

每单完成后异步评估，按 5 维评分：

| 维度 | 满分 | 评分依据 |
|---|---|---|
| 商务话术 | 25 | 敬语体系 / 语气专业度 / 目标语种地道度 |
| 策略选优 | 25 | 第一轮开局 / 调整及时性 / 顺序合理性 |
| 让步幅度 | 20 | 加价 X% → AI 谈到 Y% |
| 对话效率 | 15 | 轮数 vs 场景平均 |
| 商家满意度 | 15 | 商家最后回复语气 |

**总分 0-100 + 雷达图 + 3 条改进建议**，存到 `order.result.evaluation`，admin 后台可视化。

实测样例（V2.1 真 MiniMax-M3 评估）：

| 场景 | 总分 | 关键发现 |
|---|---|---|
| 酒店·硬约束+加价 | 76 | 商务话术好，效率有提升空间 |
| 租车·无约束+加价 | 55 | "避免中英混杂输出" |
| 机票·旺季+大幅加价 | 66 | "首轮应直接切入用户真实诉求" |

LLM 真评估时 `engine=MiniMax-M3`；降级时 `engine=fallback-heuristic`。

---

## 🛠️ 配置

### 必填环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_API_BASE` | `https://agent.minimaxi.com/mavis/api/v1/llm/v1` | Mavis LLM 端点 |
| `LLM_API_KEY` | `sk-xxx`（占位符，daemon 转发） | 通常不用设 |
| `LLM_MODEL` | `MiniMax-M3` | 自动去前缀 |

### 可选环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `AIAGENT_HOST` | `127.0.0.1` | FastAPI 监听 |
| `AIAGENT_PORT` | `8765` | FastAPI 端口 |
| `TRANSLATION_PROVIDER` | `llm` | `deepl` / `google` / `llm` |
| `DEEPL_API_KEY` | `""` | DeepL 翻译时填 |
| `VOICE_MOCK` | `1` | 0 = 真 Twilio |
| `SMS_MOCK` | `1` | 0 = 真阿里云 |
| `TWILIO_ACCOUNT_SID` | `""` | Twilio 真集成 |
| `TWILIO_AUTH_TOKEN` | `""` | Twilio 真集成 |
| `TWILIO_FROM_NUMBER` | `""` | E.164 格式 |
| `TWILIO_WEBHOOK_BASE` | `""` | ngrok 隧道 |
| `ALIYUN_ACCESS_KEY` | `""` | 阿里云 SMS |
| `ALIYUN_ACCESS_SECRET` | `""` | 阿里云 SMS |
| `MAX_NEGOTIATION_ROUNDS` | `3` | 兼容旧 |
| `PRICE_INCREASE_THRESHOLD_PCT` | `20` | 兼容旧 |
| `PRICE_INCREASE_THRESHOLD_ABS` | `500` | 兼容旧 |

详见 `backend/config.py`。

---

## 🧪 测试

```bash
# V1.0 基础
./.venv/bin/python3 test_e2e.py

# V1.1 多场景
./.venv/bin/python3 test_e2e_v11.py

# V1.2 6 策略协商
./.venv/bin/python3 test_e2e_v12.py

# V2.0 三模式
./.venv/bin/python3 test_e2e_v20.py

# V2.0 真 LLM
./.venv/bin/python3 test_e2e_v20_real_llm.py

# V2.0 LLM vs V1.2 对比
./.venv/bin/python3 test_llm_vs_v12.py

# V2.1 评估
./.venv/bin/python3 test_e2e_v21.py

# V2.1 全集成（A1-A4）
./.venv/bin/python3 test_v21_integration.py

# PDF 报告生成
./.venv/bin/python3 test_pdf_gen.py
```

---

## 🚦 路线图

### ✅ V1.0（已交付）— 酒店 only
- 4 意图（取消/改签/升级/加订）· 3 状态闭环 · 3 语言

### ✅ V1.1（已交付）— 多场景
- 酒店 + 租车 + 机票 · 4 语言 · IVR 穿透 · 6 case 端到端

### ✅ V1.2（已交付）— 协商引擎
- 6 策略 · 场景化升级阈值 · 9 case 端到端

### ✅ V2.0（已交付）— LLM 驱动
- MiniMax-M3 真决策 · LLM-first + V1.2 fallback · 4/4 比规则更聪明

### ✅ V2.1（已交付）— 评估闭环
- 5 维 AI 表现评分 · 雷达图 · 改进建议 · 鉴权 · 运营后台 · 指标

### ✅ V3.0（已交付）— 技术债清理 + 4 行业 × 5 场景
- **行业词库**：4 行业（线缆/机械/纺织/物流）× 5 场景（样品/改单/对账/议价/索赔）= **20 场景**
- 66 个通用术语 + 每场景 ≥8 关键词 + 商务套话 + 硬规则 + 升级阈值
- `POST /api/industries/detect` 自动识别行业+场景
- `GET /api/industries/{industry}/prompt-injection` 输出注入 LLM 的行业上下文
- **PostgreSQL 适配层**（`STORAGE_BACKEND=postgres` 切换，schema 与 SQLite 兼容）
- **WebSocket** `/ws?order_id=xxx` 订单状态变化实时推前端（status_changed / evaluation_ready / escalated）
- **Celery + Redis**（`CELERY_ENABLED=1` 启用，跨平台兼容）
- **OpenTelemetry**（`ENABLE_OTEL=1` 启用，可接 Jaeger/Datadog）
- **暗色主题**统一 CSS 变量（`frontend/css/design-system.css`）
- **Python SDK** 抽一层（`from sdk import AiagClient`，同步+异步版）
- **CI/CD** GitHub Actions（自动 lint + mypy + bandit + 测试）
- **mypy / bandit** 接入（0 high/medium，12 low demo 默认）
- 集成验证 20/20 case 通过

### 🔜 V4.0（计划）— 实战闭环
- Twilio 真拨号 · 阿里云 SMS 真集成 · 实战学习闭环 · 商业计费
- 真实商家行为模型 · 多 LLM 路由

---

## 🤝 集成指南

### Twilio 语音

详见 [`INTEGRATION_TWILIO.md`](./INTEGRATION_TWILIO.md)，10 步从 0 到 1 跑通 1 通真电话。

### 阿里云 SMS

需要：
1. 阿里云账号 → 申请 AccessKey
2. 短信签名 + 模板审核（1-3 天）
3. `ALIYUN_ACCESS_KEY` / `ALIYUN_ACCESS_SECRET` 填入 env
4. `SMS_MOCK=0` 重启
5. 在 `backend/channels/sms.py` 补完 `_aliyun_send()` 实现

### 自定义 LLM

修改 `backend/llm_client.py` 的 `_get_token()` 和 endpoint 默认值即可。

### Python SDK（V3.0 新增）

```python
from sdk import AiagClient

with AiagClient(base_url="http://localhost:8766", token="xxx") as c:
    order = c.create_order(
        organization="Hertz Honolulu",
        contact_number="+18084373000",
        requirement="I need an economy car 3 days",
        scenario="car_rental",
    )
    c.wait_for_completion(order["order_id"], timeout=120)
    result = c.evaluate(order["order_id"])
    print(result["total"])  # V2.1 评分
```

异步版见 `from sdk import AiagAsyncClient`。


---

## 📊 实测数据

### V2.0 LLM vs V1.2 规则（4 case 关键证据）

| Case | V1.2 规则 | M3 真决策 | 价值 |
|---|---|---|---|
| 酒店·硬约束+加价 | hold | **alt_date** | 主动探邻日 |
| 租车·无约束+加价 | value_trade | **chain_offer** | 打包换车型 |
| 机票·旺季+¥35k | value_trade | **chain_offer** | 巨幅加价下还有招 |
| 酒店·硬约束+满房 | walk_away | **alt_date** | 不轻易放弃 |

**4/4 LLM 给出比规则更聪明的策略。**

### V2.1 评估样例

见 `docs/report/v21_eval_results.json`，3 场景真 M3 评估分数 + 改进建议。

---

## 🔒 安全 & 隐私

- **密码**：PBKDF2-SHA256, 100,000 轮 + 16 字节随机 salt
- **Token**：32 字节随机 → SHA256 → DB 存 hash，**不存明文**
- **API**：Bearer token 鉴权，可选 `optional_user` 支持匿名（demo 阶段）
- **数据隔离**：订单按 `org_id` 隔离，跨 org 访问返回 403
- **TODO（生产前）**：CORS 收紧、邮箱验证、限流、审计日志

---

## 📜 License

Internal use, 2026-2027. All rights reserved.

---

## 🙏 致谢

- Mavis daemon（提供 MiniMax-M3 托管 LLM 接入）
- Twilio（语音通道）
- 阿里云（短信通道）
- DeepL（备选翻译）

---

**问题反馈**：在 issue 里贴 `/api/health` + `/api/metrics` 的输出 + 复现步骤。
