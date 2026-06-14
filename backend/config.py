"""Backend config · 增 V3.0 字段（域名/SDK/WS/CI）。"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOMAINS_DIR = ROOT_DIR / "domains"  # V3.0 行业词库
SDK_DIR = ROOT_DIR / "sdk"           # V3.0 SDK

# === V2.1 SQLite ===
DB_PATH = DATA_DIR / "orders.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# V3.0 PostgreSQL（生产路径）
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "aiagent")
PG_USER = os.getenv("PG_USER", "aiagent")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

# V3.0 Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# V3.0 WebSocket
WS_PATH = os.getenv("WS_PATH", "/ws")

# V3.0 Celery
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# === LLM / 翻译 / 渠道 ===
HOST = os.getenv("AIAGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("AIAGENT_PORT", "8766"))

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://agent.minimaxi.com/mavis/api/v1/llm/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-xxx")
LLM_MODEL = os.getenv("LLM_MODEL", "minimax/MiniMax-M3")

TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "llm")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

VOICE_MOCK = os.getenv("VOICE_MOCK", "1") == "1"
SMS_MOCK = os.getenv("SMS_MOCK", "1") == "1"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_WEBHOOK_BASE = os.getenv("TWILIO_WEBHOOK_BASE", "")

ALIYUN_ACCESS_KEY = os.getenv("ALIYUN_ACCESS_KEY", "")
ALIYUN_ACCESS_SECRET = os.getenv("ALIYUN_ACCESS_SECRET", "")

# === 状态机 ===
# 1.7.1 升级到 20 轮，支持 10 分钟长沟通（10 分钟 ≈ 20 轮 × 30s/轮）
MAX_NEGOTIATION_ROUNDS = 20
PRICE_INCREASE_THRESHOLD_PCT = 20
PRICE_INCREASE_THRESHOLD_ABS = 500

# 1.7.1 协商 session 时长（秒）：900s = 15 分钟
NEGOTIATION_SESSION_TIMEOUT = 900

# 1.7.4 实时进度通知间隔（秒）：每 60s 给客户发一封进度邮件
PROGRESS_NOTIFY_INTERVAL = 60

# 1.7.3 上下文摘要压缩触发：对话超 N 轮后压缩一次
DIALOGUE_COMPRESS_THRESHOLD = 8  # 超过 8 轮触发压缩

# === 行业场景升级阈值（默认，回退到 V1.2 通用阈值）===
DEFAULT_ESCALATION = {
    "hotel": {"pct": 20, "abs": 280, "rounds": 20},
    "car_rental": {"pct": 30, "abs": 240, "rounds": 20},
    "flight": {"pct": 25, "abs": 30000, "rounds": 20},
}

# === V3.0 行业 ↔ 场景映射（从 travel 类场景扩展到外贸行业场景）===
INDUSTRY_SCENARIO_MAP = {
    "cable": ["sample_confirm", "order_modify", "reconciliation", "price_negotiation", "claim_dispute"],
    "machinery": ["sample_confirm", "order_modify", "reconciliation", "price_negotiation", "claim_dispute"],
    "textile": ["sample_confirm", "order_modify", "reconciliation", "price_negotiation", "claim_dispute"],
    "logistics": ["sample_confirm", "order_modify", "reconciliation", "price_negotiation", "claim_dispute"],
    # 兼容 V1.x 旧场景
    "hotel": ["modify_booking", "check_in", "extend_stay", "add_service", "cancel"],
    "car_rental": ["modify_booking", "extend_rental", "add_service", "cancel", "inquiry"],
    "flight": ["change_flight", "add_baggage", "select_seat", "cancel", "inquiry"],
}

SUPPORTED_LANGUAGES = ["en", "ja", "ko", "zh"]
