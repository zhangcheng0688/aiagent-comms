# Twilio 真实接入指南

把 V1.1 的 VOIP 渠道从 mock 切换到 Twilio 真实拨号，让 AI 真的能拨通境外酒店/租车/航空公司的电话。

## 0. 前提

- 一台 Mac / Linux / WSL（开发测试用）
- Twilio 账号（免费试用 $15）
- 一个能收电话的手机号（Trial 账号只能打"已验证号码"，需要先去 Twilio 控制台验证）
- ngrok 账号（免费够用，暴露公网 webhook）

## 1. Twilio 账号准备

### 1.1 注册并验证

1. 打开 https://console.twilio.com 注册
2. 拿到 `Account SID` + `Auth Token`（控制台首页）
3. **Phone Numbers → Manage → Verified Caller IDs**，验证你测试用的手机号
4. 免费 Trial 只能打已验证号码；正式上线要升级 + 买国际号码

### 1.2 买一个国际号码（可选）

- `Phone Numbers → Buy a Number`
- 选支持你要的国家（日本/韩国/美国）
- Capabilities 必须勾上 **Voice** + **SMS**（V1.1）
- 月费 ~$1-2

如果你只是想跑通流程，可以暂时不改 `TWILIO_FROM_NUMBER`，先用 magic 验证流程（Trial 账号号码）。

## 2. 暴露公网 Webhook（ngrok）

Twilio 是公网服务，要 POST 到我们的 `/webhooks/twilio/gather`，需要暴露本地 8765 端口。

### 2.1 安装 ngrok

```bash
brew install ngrok  # macOS
# 或
snap install ngrok # Linux
```

### 2.2 注册并认证

1. https://dashboard.ngrok.com/signup 注册
2. 拿 authtoken
3. `ngrok config add-authtoken <你的token>`

### 2.3 启动隧道

```bash
ngrok http 8765
```

会显示类似：
```
Session Status  online
Forwarding      https://xxxx-xxx-xxx-xxx.ngrok-free.app -> http://localhost:8765
```

记下 `https://xxxx-xxx-xxx-xxx.ngrok-free.app` 这个域名。

## 3. 配置环境变量

在项目根目录建 `.env`：

```bash
cd "/Users/chenwanyi/Documents/mini Max/aiagent-comms"
cat > .env << 'EOF'
# Mock 关闭
VOICE_MOCK=0
SMS_MOCK=0

# Twilio（替换为你的真实值）
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+1xxxxxxxxxx

# Webhook base（用 ngrok 给的域名，不要带末尾 / ）
TWILIO_WEBHOOK_BASE=https://xxxx-xxx-xxx-xxx.ngrok-free.app

# LLM
LLM_API_KEY=sk-xxx
EOF
```

## 4. 安装 Twilio 依赖

```bash
cd "/Users/chenwanyi/Documents/mini Max/aiagent-comms"
./.venv/bin/pip install twilio==9.4.1
```

## 5. 启动服务

```bash
./.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
```

注意绑 `0.0.0.0` 而不是 `127.0.0.1`，因为 ngrok 要从外部访问。

## 6. 真实测试

### 6.1 浏览器提交一个订单

打开 `http://127.0.0.1:8765/static/submit.html`：
- organization: 酒店名（如 Hilton Tokyo）
- contact_number: 酒店前台真实号码（带国家区号 +81...）
- requirement: "请帮我改 6.12 双床+免费早餐"
- preferred_channel: 选 **voice**
- 提交

### 6.2 观察 Twilio 控制台

1. 打开 https://console.twilio.com/us1/monitor/logs/voice
2. 会看到一次 Outgoing Call
3. 几秒后你测试手机会响（这是 Twilio 打给酒店，但 Trial 模式下"打"会先打给已验证号码模拟）
4. 接听后听 AI 的日语开场白
5. 说完后 Twilio 自动 STT 转写商家原话（5 秒超时）
6. 转写结果 POST 到你的 ngrok → 本地 FastAPI → `handle_twilio_gather_webhook` → 唤醒 `voice.call()` 的等待 → 返回下一句

### 6.3 浏览器看订单详情

`http://127.0.0.1:8765/order/<order_id>` 看到双语对话记录已经更新。

## 7. 故障排查

### "Permission to send SMS/voice to this number is not allowed"

- Trial 账号：去控制台 → Verified Caller IDs 加这个号码
- Production 账号：号码必须有 Geo Permissions（在 Voice Geographic Permissions 设置）

### "Webhook URL is not reachable"

- 检查 ngrok 是否还活着
- 检查 `TWILIO_WEBHOOK_BASE` 是否正确（不要带 /webhooks/... 后缀）
- 在 Twilio 控制台 Call Log 里点具体通话，看 Error 提示

### 商家没回复 / 5 秒超时

- 真人接电话时可能不知道说什么，5 秒 timeout 是合理的
- 可以调大 `voice.py:_twilio_call` 里 `resp.gather(timeout=8)` 给商家 8 秒

### 听到 AI 但没回传文字

- Twilio SpeechResult 字段为空 → 检查 `input_="speech"` 是否正确
- 有可能商家说话的语种和 `<Gather language="...">` 不匹配，转写失败

## 8. 切换回 Mock

调试时方便：

```bash
# .env
VOICE_MOCK=1
SMS_MOCK=1
```

重启服务即可。

## 9. V1.1 后续可加

- **接 Twilio SMS**：跟 V1.0 mock 一致，只需设 `SMS_MOCK=0` + `ALIYUN_*` 或 Twilio Messaging API
- **接 DeepL**：设 `TRANSLATION_PROVIDER=deepl` + `DEEPL_API_KEY`
- **接通 Media Streams**（V2.0）：替换 `<Gather>` 方案为 WebSocket 双向流，AI 语音实时对话（延迟 < 500ms）

## 10. 关键文件

| 文件 | 作用 |
|---|---|
| `backend/channels/voice.py` | VOIP 抽象 + Twilio `<Gather>` 同步实现 |
| `backend/main.py` `/webhooks/twilio/init` `/webhooks/twilio/gather` | 接收 Twilio 回调 |
| `backend/config.py` | Twilio 环境变量定义 |
| `requirements.txt` | `twilio==9.4.1` |
| `.env` | 你自己的 Twilio 凭证（不要提交到 git） |
