"""需求拆解器：用大模型把中文需求拆成结构化 IntentSlot。

V3.0：支持行业词库（cable/machinery/textile/logistics）。
- 先 detect industry/scenario
- 自动注入行业术语 + 商务套话 + 升级阈值到 prompt
"""
from __future__ import annotations
import json
import os
import re
import uuid
import httpx
from ..config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from ..models import IntentSlot, OrderCreate
from ..domains import get_domain_loader


SYSTEM_PROMPT = """你是一个跨境出行需求拆解助手。用户会给你一段中文自然语言需求（关于酒店/租车/机票的咨询/修改/取消/加服务），请拆解为结构化 JSON 数组。

每个 intent 必须有：
- slot_id: 短标识符（snake_case）
- type: 必须是以下四种之一：
  - "info": 信息咨询
  - "modify": 修改现有预订
  - "cancel": 取消预订
  - "add_service": 增加服务
- description: 人类可读的中文描述
- target_value: 用户期望的值（如果可量化）
- priority: 1=最高优先级，数字越小越优先

只返回 JSON 数组，不要其他文字、不要 markdown 代码块。"""


async def parse_intent(
    requirement: str,
    constraints: str | None = None,
    scenario: str = "hotel",
    industry: str | None = None,
) -> list[IntentSlot]:
    """调用大模型拆解需求为 IntentSlot 列表。

    Args:
        scenario: 旧版场景（hotel/car_rental/flight）或新版行业（cable/machinery/textile/logistics）
        industry: 显式行业（V3.0），None 时从 requirement 自动检测

    V3.0 流程：
        1. detect industry (如未指定)
        2. detect scenario within industry
        3. 注入行业词库到 LLM prompt
        4. LLM 拆解 + 离线规则兜底
    """
    intents: list[IntentSlot] = []
    loader = get_domain_loader()

    # V3.0 行业检测
    if industry is None and scenario in loader.list_industries():
        industry = scenario
        scenario_in_ind = loader.detect_scenario(requirement, industry)
        if scenario_in_ind:
            scenario = scenario_in_ind

    # 自动 industry 检测
    if industry is None:
        auto = loader.detect_industry(requirement)
        if auto:
            industry = auto
            scenario_in_ind = loader.detect_scenario(requirement, industry)
            if scenario_in_ind:
                scenario = scenario_in_ind

    # V3.0 行业词库注入 prompt
    industry_block = ""
    if industry and industry in loader.list_industries():
        # 取候选 scenario 列表（行业第一个默认 + 全部）
        ind = loader.get_industry(industry)
        scenarios = list(ind.get("scenarios", {}).keys()) if ind else []
        target_sc = scenario if scenario in scenarios else (scenarios[0] if scenarios else "sample_confirm")
        industry_block = loader.build_prompt_injection(industry, target_sc, "zh")

    try:
        user_prompt = f"[场景：{scenario}]\n[行业：{industry or '通用'}]\n需求：{requirement}"
        if constraints:
            user_prompt += f"\n约束：{constraints}"
        if industry_block:
            user_prompt += f"\n\n{industry_block}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{LLM_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    intents.append(IntentSlot(
                        slot_id=item.get("slot_id") or f"slot_{uuid.uuid4().hex[:6]}",
                        type=item.get("type", "info"),
                        description=item.get("description", ""),
                        target_value=item.get("target_value"),
                        priority=item.get("priority", 1),
                    ))
    except Exception:
        intents = _offline_parse(requirement, constraints, scenario)

    return intents


def _offline_parse(requirement: str, constraints: str | None, scenario: str) -> list[IntentSlot]:
    """LLM 不可用时的离线规则拆解。"""
    if scenario == "car_rental":
        return _parse_car_rental(requirement, constraints)
    if scenario == "flight":
        return _parse_flight(requirement, constraints)
    return _parse_hotel(requirement, constraints)


def _parse_hotel(requirement: str, constraints: str | None) -> list[IntentSlot]:
    intents: list[IntentSlot] = []
    text = requirement

    if any(kw in text for kw in ["改入住", "改到", "改日期", "改时间", "改单", "改期"]):
        m = re.search(r"(\d{1,2}[\./\-月]\d{1,2}(?:日)?)", text)
        date = m.group(1) if m else None
        intents.append(IntentSlot(
            slot_id="change_date", type="modify", description="改入住日期",
            target_value=date, priority=1,
        ))

    if any(kw in text for kw in ["双床", "大床", "房型", "改房", "升级"]):
        m = re.search(r"(双床|大床|单人|家庭|豪华|行政|标准)", text)
        bed = m.group(1) if m else "双床"
        intents.append(IntentSlot(
            slot_id="change_room", type="modify", description=f"房型改为{bed}",
            target_value=bed, priority=2,
        ))

    if any(kw in text for kw in ["早餐", "早饭", "早饭"]):
        intents.append(IntentSlot(
            slot_id="breakfast", type="info", description="确认是否含早餐",
            target_value="是（含）", priority=3,
        ))

    if any(kw in text for kw in ["取消", "退订", "不去了"]):
        intents.append(IntentSlot(
            slot_id="cancel_booking", type="cancel", description="取消该预订", priority=1,
        ))

    if any(kw in text for kw in ["加床", "加一张床", "加餐", "儿童早餐"]):
        intents.append(IntentSlot(
            slot_id="add_bed", type="add_service", description="加床或儿童餐", priority=2,
        ))

    if not intents:
        intents.append(IntentSlot(
            slot_id="slot_fallback", type="info", description=requirement,
            target_value=None, priority=1,
        ))
    return intents


def _parse_car_rental(requirement: str, constraints: str | None) -> list[IntentSlot]:
    intents: list[IntentSlot] = []
    text = requirement

    # 车型
    if any(kw in text for kw in ["车型", "什么车", "租", "SUV", "经济型", "豪华车", "compact", "economy"]):
        m = re.search(r"(紧凑|经济|中型|中大型|豪华|SUV|商务|compact|economy|midsize|fullsize|luxury|SUV|premium)", text, re.IGNORECASE)
        car = m.group(1) if m else "经济型"
        intents.append(IntentSlot(
            slot_id="car_type", type="info", description="确认车型",
            target_value=car, priority=1,
        ))

    # 取车日期
    if any(kw in text for kw in ["取车", "提车", "租车日期", "起租"]):
        m = re.search(r"(\d{1,2}[\./\-月]\d{1,2}(?:日)?)", text)
        date = m.group(1) if m else None
        intents.append(IntentSlot(
            slot_id="pickup_date", type="modify", description="确认取车日期",
            target_value=date, priority=2,
        ))

    # 还车日期
    if any(kw in text for kw in ["还车", "归还", "退车"]):
        m = re.search(r"(\d{1,2}[\./\-月]\d{1,2}(?:日)?)", text)
        date = m.group(1) if m else None
        intents.append(IntentSlot(
            slot_id="return_date", type="modify", description="确认还车日期",
            target_value=date, priority=3,
        ))

    # 取车地点
    if any(kw in text for kw in ["取车地点", "门店", "机场取", "市区取", "酒店取"]):
        intents.append(IntentSlot(
            slot_id="pickup_location", type="info", description="确认取车地点",
            priority=2,
        ))

    # 异地还车
    if any(kw in text for kw in ["异地还", "异地归还", "异地还车", "异地退", "异地还"]):
        intents.append(IntentSlot(
            slot_id="one_way", type="modify", description="确认异地还车（可能加价）",
            target_value="是", priority=2,
        ))

    # 保险
    if any(kw in text for kw in ["保险", "全险", "基本险", "CDW", "LDW", "全保", "不计免赔"]):
        intents.append(IntentSlot(
            slot_id="insurance", type="info", description="确认保险类型与价格",
            priority=1,
        ))

    # 驾照
    if any(kw in text for kw in ["驾照", "国际驾照", "IDP", "中国驾照", "翻译件"]):
        intents.append(IntentSlot(
            slot_id="driver_license", type="info", description="确认驾照/国际翻译件要求",
            priority=1,
        ))

    # 里程
    if any(kw in text for kw in ["里程", "不限里程", "公里", "英里", "mileage"]):
        intents.append(IntentSlot(
            slot_id="mileage", type="info", description="确认里程限制",
            priority=2,
        ))

    # 加驾
    if any(kw in text for kw in ["加驾", "额外司机", "副驾"]):
        intents.append(IntentSlot(
            slot_id="extra_driver", type="add_service", description="加额外驾驶员",
            priority=3,
        ))

    if not intents:
        intents.append(IntentSlot(
            slot_id="slot_fallback", type="info", description=requirement,
            target_value=None, priority=1,
        ))
    return intents


def _parse_flight(requirement: str, constraints: str | None) -> list[IntentSlot]:
    intents: list[IntentSlot] = []
    text = requirement

    # 改签
    if any(kw in text for kw in ["改签", "改期", "改日期", "改时间", "改航班"]):
        m = re.search(r"(\d{1,2}[\./\-月]\d{1,2}(?:日)?)", text)
        date = m.group(1) if m else None
        intents.append(IntentSlot(
            slot_id="change_flight", type="modify", description="改签航班",
            target_value=date, priority=1,
        ))

    # 退票
    if any(kw in text for kw in ["退票", "退款", "取消航班", "不飞了"]):
        intents.append(IntentSlot(
            slot_id="refund", type="cancel", description="退票申请",
            priority=1,
        ))

    # 选座
    if any(kw in text for kw in ["选座", "座位", "靠窗", "靠过道", "前排", "紧急出口"]):
        intents.append(IntentSlot(
            slot_id="seat", type="add_service", description="提前选座",
            priority=2,
        ))

    # 餐食
    if any(kw in text for kw in ["餐食", "特殊餐", "素食", "清真", "无麸质", "儿童餐"]):
        intents.append(IntentSlot(
            slot_id="meal", type="add_service", description="特殊餐食预订",
            priority=3,
        ))

    # 行李
    if any(kw in text for kw in ["行李", "超重", "额外行李", "托运"]):
        intents.append(IntentSlot(
            slot_id="baggage", type="add_service", description="购买额外行李额",
            priority=2,
        ))

    # 升舱
    if any(kw in text for kw in ["升舱", "升级舱位", "商务舱", "头等舱", "超级经济舱"]):
        m = re.search(r"(经济舱|商务舱|头等舱|超级经济舱|经济|商务|头等|premium economy|business|first)", text, re.IGNORECASE)
        cabin = m.group(1) if m else "商务舱"
        intents.append(IntentSlot(
            slot_id="upgrade_cabin", type="modify", description=f"升舱至{cabin}",
            target_value=cabin, priority=1,
        ))

    # 改名
    if any(kw in text for kw in ["改名", "更名", "变更乘客", "改乘机人"]):
        intents.append(IntentSlot(
            slot_id="name_change", type="modify", description="乘机人姓名变更",
            priority=1,
        ))

    # 航班状态/时刻
    if any(kw in text for kw in ["状态", "几点", "延误", "取消", "登机口", "航站楼", "起飞", "降落"]):
        intents.append(IntentSlot(
            slot_id="flight_status", type="info", description="查询航班实时状态",
            priority=1,
        ))

    if not intents:
        intents.append(IntentSlot(
            slot_id="slot_fallback", type="info", description=requirement,
            target_value=None, priority=1,
        ))
    return intents


def detect_scenario(requirement: str, organization: str = "") -> str:
    """根据需求文本 + 机构名推断场景。"""
    text = (requirement + " " + organization).lower()
    # 租车关键词
    if any(kw in text for kw in ["租车", "rent", "rental", "hertz", "avis", "sixt", "门店", "取车", "还车", "车型", "里程", "保险", "cdw"]):
        return "car_rental"
    # 机票关键词
    if any(kw in text for kw in ["机票", "航班", "航班号", "改签", "退票", "升舱", "选座", "登机口", "起飞", "降落", "航站楼", "ana", "jal", "大韩", "韩亚", "united", "delta", "国航", "东航", "南航", "厦航"]):
        return "flight"
    # 酒店关键词
    if any(kw in text for kw in ["酒店", "hotel", "旅馆", "民宿", "入住", "退房", "房型", "早餐", "床", "加床"]):
        return "hotel"
    return "hotel"  # 默认酒店（V1.0 主场景）


def detect_target_language(contact_number: str, organization: str) -> str:
    """根据号码区号 + 机构名粗略判断目标语种。"""
    cn_map = {
        "+81": "ja",   # 日本
        "+82": "ko",   # 韩国
        "+1": "en",    # 美国/加拿大
        "+44": "en",   # 英国
        "+61": "en",   # 澳洲
        "+852": "zh",  # 香港
        "+853": "zh",  # 澳门
        "+886": "zh",  # 台湾
        "+65": "en",   # 新加坡
        "+66": "th",   # 泰国
    }
    for prefix, lang in cn_map.items():
        if contact_number.startswith(prefix):
            return lang
    return "en"
