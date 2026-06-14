"""Pydantic 数据模型。"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class OrderState(str, Enum):
    """订单状态机 13 个状态（V1.7 长沟通扩展）。"""
    INIT = "init"                          # 初始
    CONNECTING = "connecting"              # 拨号中
    OPENING = "opening"                    # 开场
    CONFIRMING = "confirming"              # 逐项确认
    NEGOTIATING = "negotiating"            # 多轮协商
    AWAIT_USER = "await_user"              # 等待用户决策（用户说了算）
    AWAIT_MERCHANT = "await_merchant"      # 1.7.2 新增：等待商家响应（商家去核价/查库存）
    PAUSED = "paused"                      # 1.7.2 新增：用户主动暂停（"等我问问老板"）
    ESCALATE_TO_USER = "escalate"          # 升级到用户
    CLOSING_SUCCESS = "closing_success"    # 成功结束
    CLOSING_FAILURE = "closing_failure"    # 失败结束
    ABORTED = "aborted"                    # 中止
    RESUMED = "resumed"                    # 1.7.2 新增：从 PAUSED 恢复（内部中间态）


class Channel(str, Enum):
    SMS = "sms"
    VOICE = "voice"


class OrderStatus(str, Enum):
    PENDING = "pending"        # 等待处理
    IN_PROGRESS = "in_progress"  # 沟通中
    SUCCESS = "success"        # 成功
    FAILED = "failed"          # 失败
    NEEDS_USER = "needs_user"  # 需要用户决策


class IntentSlot(BaseModel):
    """拆解后的一个意图项（用户想做的一件事）。"""
    slot_id: str
    type: Literal["info", "modify", "cancel", "add_service"]
    description: str  # 人类可读
    target_value: str | None = None  # 用户期望的值
    confirmed_value: str | None = None  # 商家最终确认的值
    priority: int = 1  # 1=最高


class OrderCreate(BaseModel):
    """用户提交代办需求。"""
    organization: str = Field(..., description="目标机构名称，如'大阪心斋桥大和鲁内酒店'")
    contact_number: str = Field(..., description="境外联系号码，含国家代码")
    requirement: str = Field(..., min_length=5, description="中文需求自然语言")
    constraints: str | None = Field(None, description="特殊约束（不可加价/必须免费取消等）")
    preferred_channel: Channel = Channel.SMS  # 优先通道
    scenario: str = Field("hotel", description="场景：hotel / car_rental / flight")
    user_email: str | None = Field(None, description="1.7.4: 客户邮箱（用于实时进度通知）")


class Order(BaseModel):
    """完整订单。"""
    id: str
    organization: str
    contact_number: str
    requirement: str
    constraints: str | None = None
    target_language: str = "en"  # 默认英语
    preferred_channel: Channel = Channel.SMS
    scenario: str = "hotel"  # hotel / car_rental / flight
    state: OrderState = OrderState.INIT
    status: OrderStatus = OrderStatus.PENDING
    intents: list[IntentSlot] = []
    dialogue: list[DialogueTurn] = []
    result: dict | None = None
    org_id: str | None = None  # A2: 归属组织
    user_id: str | None = None  # A2: 创建人
    user_email: str | None = None  # 1.7.4: 客户邮箱（用于进度通知）
    created_at: datetime
    updated_at: datetime


class DialogueTurn(BaseModel):
    """对话一轮。"""
    turn_id: int
    speaker: Literal["ai", "merchant"]
    original: str  # 商家原话
    translated: str  # 中文翻译
    intent_match: str | None = None  # 命中的意图 slot_id
    timestamp: datetime
    confidence: float = 1.0


class OrderResult(BaseModel):
    """最终回执。"""
    summary: str  # 中文精简总结
    confirmed_intents: list[IntentSlot]
    failed_intents: list[IntentSlot]
    receipt: dict | None = None  # 邮件回执（mock）
    total_cost: float | None = None  # 实际成交金额
    next_steps: list[str] = []


class NegotiationProposal(BaseModel):
    """商家反提案（多轮协商时触发）。"""
    proposal_id: str
    summary: str  # 中文简述：原房型已满，升级到豪华房加价 ¥280/晚
    options: list[dict]  # [{option_id, label, price_change, key_changes, risk}]
    deadline_minutes: int = 30


# =============================================================================
# Outbound Sales Agent 模型
# =============================================================================
class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    ORDER_CREATED = "order_created"
    UNSUBSCRIBED = "unsubscribed"
    DRAFT = "draft"


class Lead(BaseModel):
    """ outbound 销售线索。"""
    id: str
    source: str = "manual"          # 来源：sample / linkedin / customs / manual
    industry: str = "cable"         # 当前 MVP 默认 cable
    company_name: str
    contact_name: str | None = None
    email: str
    country: str | None = None
    website: str | None = None
    scenario: str = "sample_confirm"  # 预计触达场景
    status: LeadStatus = LeadStatus.NEW
    last_email_subject: str | None = None
    last_email_body: str | None = None
    last_email_sent_at: datetime | None = None
    reply_summary: str | None = None
    order_id: str | None = None
    org_id: str | None = None       # A2: 归属组织
    user_id: str | None = None      # A2: 创建人
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadCreate(BaseModel):
    """新增线索请求。"""
    source: str = "manual"
    industry: str = "cable"
    company_name: str
    contact_name: str | None = None
    email: str
    country: str | None = None
    website: str | None = None
    scenario: str = "sample_confirm"
    notes: str | None = None


class OutreachResult(BaseModel):
    """单次触达结果。"""
    lead_id: str
    sent: bool
    subject: str
    body: str
    mode: Literal["real", "draft", "mock"]
    error: str | None = None
