"""处理潜客回复：解析、分类、更新线索、自动建单。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from ...email_worker import EmailParser
from ...llm_client import call_mavis_llm, extract_json_from_text
from ...models import Channel, Lead, LeadStatus, Order, OrderState, OrderStatus
from ...storage_backend import storage
from ...core.intent_parser import parse_intent
from ...channels.voice import VoiceChannel
from ...channels.sms import SmsChannel
from ...core.dialogue import DialogueEngine

log = logging.getLogger("aiagent.outbound.inbound")


def _detect_language(text: str) -> str:
    """简单语言检测，默认英语。"""
    if any(ord(c) > 0x3040 and ord(c) < 0x30FF for c in text):
        return "ja"
    if any(ord(c) > 0xAC00 and ord(c) < 0xD7A4 for c in text):
        return "ko"
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return "zh"
    return "en"


def _keyword_classify(text_lower: str) -> tuple[str, float]:
    """关键词兜底分类。"""
    if any(kw in text_lower for kw in ["unsubscribe", "remove me", "stop", "not interested", "no need"]):
        return "unsubscribed", 0.9
    inquiry_kws = ["sample", "quotation", "quote", "price", "catalog", "interested", "please send",
                   "send me", "would like", "want to buy", "purchase", "order", "询价", "报价", "样品", "感兴趣"]
    if any(kw in text_lower for kw in inquiry_kws):
        return "qualified", 0.8
    if any(kw in text_lower for kw in ["thanks", "thank you", "received", "ok", "好的", "谢谢"]):
        return "replied", 0.6
    return "replied", 0.5


async def _llm_classify(subject: str, body: str) -> tuple[str, str] | None:
    """用 LLM 分类回复意图并生成摘要。返回 (category, summary) 或 None。"""
    system = """You are a sales assistant analyzing a prospect reply to a cold email.
Output ONLY a JSON object with two keys:
- "category": one of [qualified, replied, unsubscribed, neutral]
- "summary": one concise sentence in Chinese describing the reply.

Definitions:
- qualified: prospect asks for samples, prices, catalog, or shows clear buying intent.
- replied: polite acknowledgment or non-committal response.
- unsubscribed: wants to stop receiving emails.
- neutral: unclear or no actionable content."""
    user = f"Subject: {subject}\n\nBody:\n{body[:1500]}"
    content = await call_mavis_llm(system=system, user=user, temperature=0.2, max_tokens=256)
    data = extract_json_from_text(content or "")
    if isinstance(data, dict) and data.get("category"):
        return str(data["category"]).lower(), str(data.get("summary", ""))
    return None


async def classify_reply(subject: str, body: str) -> tuple[str, str, str]:
    """返回 (category, summary, engine)。"""
    llm_result = await _llm_classify(subject, body)
    if llm_result:
        return llm_result[0], llm_result[1], "llm"
    text_lower = (subject + " " + body).lower()
    category, confidence = _keyword_classify(text_lower)
    summary = f"关键词分类：{category}（置信度 {confidence:.0%}）"
    return category, summary, "keyword"


def _build_order_requirement(lead: Lead, reply_body: str, category: str) -> str:
    """把潜客回复转成 aiagent-comms 订单的 requirement。"""
    base = f"来自 {lead.company_name} ({lead.country}) 的潜客回复：{reply_body[:300]}"
    if category == "qualified":
        base += "\n需求：请跟进样品确认或报价协商。"
    elif category == "replied":
        base += "\n需求：礼貌回复并推进下一步。"
    return base


async def create_order_from_lead(lead: Lead, reply_body: str) -> Order:
    """为合格潜客创建订单并启动后台协商。"""
    now = datetime.utcnow()
    order_id = f"ord_out_{uuid.uuid4().hex[:8]}"
    requirement = _build_order_requirement(lead, reply_body, "qualified")
    # 解析意图
    intents = await parse_intent(requirement, None, lead.scenario or "sample_confirm", lead.industry)
    order = Order(
        id=order_id,
        organization=lead.company_name,
        contact_number=lead.email,  # 邮件拓客用邮箱作为 contact_number
        requirement=requirement,
        constraints=None,
        target_language=_detect_language(reply_body),
        preferred_channel=Channel.SMS,
        scenario=lead.scenario or "sample_confirm",
        state=OrderState.INIT,
        status=OrderStatus.PENDING,
        intents=intents,
        dialogue=[],
        result=None,
        org_id=lead.org_id,
        user_id=lead.user_id,
        user_email=lead.email,
        created_at=now,
        updated_at=now,
    )
    await storage.create_order(order)

    # 启动协商引擎（mock 通道，异步运行）
    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    async def _run():
        try:
            updated = await engine.run(order)
            await storage.update_order(updated)
        except Exception as e:
            log.error(f"outbound order negotiation failed: {e}")

    import asyncio
    asyncio.create_task(_run())
    return order


async def handle_inbound_email(raw_email_bytes: bytes) -> dict:
    """处理一封 inbound 邮件，返回处理结果。"""
    parser = EmailParser()
    parsed = parser.parse(raw_email_bytes)
    from_email = parsed.from_email.lower().strip()

    # 只处理来自 leads 的邮件
    lead = await storage.get_lead_by_email(from_email)
    if not lead:
        return {"handled": False, "reason": "email not found in leads", "from": from_email}

    category, summary, engine = await classify_reply(parsed.subject, parsed.instruction)
    lead.reply_summary = summary
    lead.updated_at = datetime.utcnow()

    order_id = None
    if category == "unsubscribed":
        lead.status = LeadStatus.UNSUBSCRIBED
    elif category == "qualified":
        lead.status = LeadStatus.QUALIFIED
        order = await create_order_from_lead(lead, parsed.instruction)
        order_id = order.id
        lead.order_id = order_id
        lead.status = LeadStatus.ORDER_CREATED
    else:
        lead.status = LeadStatus.REPLIED

    await storage.update_lead(lead)
    return {
        "handled": True,
        "lead_id": lead.id,
        "category": category,
        "summary": summary,
        "engine": engine,
        "order_id": order_id,
    }
