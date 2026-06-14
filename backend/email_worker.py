"""V3.0 邮件 worker：方案 C 邮件转发接入层。

功能：
- IMAP 持续轮询收件箱
- 解析邮件（指令 + 附件 + 对话链）
- 白名单校验
- 调后端 API 创建订单 + 跑 AI
- SMTP 回复（纪要 + 评估）

零外部依赖：imaplib / smtplib / email 标准库。

用法：
    python -m backend.email_worker

环境变量：
    IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD
    SMTP_HOST, SMTP_PORT (465/587), SMTP_USER, SMTP_PASSWORD
    AIAGENT_API_BASE (default http://127.0.0.1:8766)
    EMAIL_POLL_INTERVAL (default 30s)
    APPROVED_SENDERS (逗号分隔白名单)
"""
from __future__ import annotations
import asyncio
import email
import imaplib
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import (
    HOST, PORT,
)

log = logging.getLogger("aiagent.email")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# === 配置 ===
IMAP_HOST = os.getenv("IMAP_HOST", "imap.qq.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", IMAP_USER)
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", IMAP_PASSWORD)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "AI 外贸代办")

API_BASE = os.getenv("AIAGENT_API_BASE", f"http://{HOST}:{PORT}")
POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", "30"))
APPROVED_SENDERS = set(s.strip().lower() for s in os.getenv("APPROVED_SENDERS", "").split(",") if s.strip())


# === 解析出的订单数据 ===
@dataclass
class ParsedOrder:
    """从邮件里解析出的代办订单。"""
    from_email: str
    from_name: str
    subject: str
    instruction: str              # 客户指令正文
    constraints: Optional[str]    # 客户约束（"不可加价"等）
    organization: Optional[str]   # 目标商家
    contact_number: Optional[str] # 商家电话
    scenario: str = "hotel"        # 场景
    industry: Optional[str] = None # 行业
    thread: list[dict] = None      # 对话历史
    message_id: str = ""           # 用于回信追踪
    in_reply_to: str = ""

    def __post_init__(self):
        if self.thread is None:
            self.thread = []


# === 邮件解析器 ===
class EmailParser:
    """从一封邮件解析出 ParsedOrder。"""

    # 中文电话正则（容错各种分隔符）
    PHONE_PATTERNS = [
        re.compile(r"\+\d{1,3}(?:[\s\-]?\d+){1,4}"),  # +国码-...，可多段
        re.compile(r"(?<!\d)(?:\d[\s\-]?){7,15}\d(?!\d)"),  # 通用 8-16 位，可有分隔
        re.compile(r"\b\d{3,4}[\s\-]?\d{3,4}[\s\-]?\d{4}\b"),  # 常见区号-号段-号段
    ]

    # 中文场景关键词 → scenario
    SCENARIO_KEYWORDS = {
        "hotel": ["酒店", "宾馆", "旅馆", "入住", "退房", "房型", "床型", "加床", "早餐", "hotel"],
        "car_rental": ["租车", "租一辆", "取车", "还车", "车型", "保险", "异地还", "SUV", "轿车", "car rental"],
        "flight": ["机票", "航班", "改签", "退票", "起飞", "到达", "舱位", "行李", "航班号", "flight"],
        # 通用外贸场景（V3.0）
        "price_negotiation": ["询价", "报价", "谈价", "价格", "优惠", "折扣", "压价", "还价", "price", "quote", "discount"],
        "order_modify": ["修改订单", "改单", "改地址", "改数量", "变更", "调整", "修改", "modify", "change"],
        "claim_dispute": ["投诉", "索赔", "纠纷", "争议", "退货", "退款", "不合格", "complaint", "refund", "claim"],
        "sample_confirm": ["样品", "样板", "打样", "sample", "样件"],
        "reconciliation": ["对账", "账单", "结算", "发票", "余额", "reconciliation", "invoice", "statement"],
    }

    # 行业关键词（V3.0）
    INDUSTRY_KEYWORDS = {
        "cable": ["电缆", "线缆", "导线", "导体", "绝缘", "护套", "阻燃", "截面积", "XLPE", "PVC"],
        "machinery": ["机加工", "CNC", "数控", "车床", "铣床", "注塑", "热处理", "锻造", "machinery", "机加工"],
        "textile": ["纺织", "面料", "布", "纱线", "克重", "GSM", "涤纶", "棉", "印染", "textile"],
        "logistics": ["海运", "空运", "货代", "集装箱", "提单", "舱位", "清关", "船公司", "FCL", "LCL"],
    }

    def parse(self, raw_email_bytes: bytes) -> ParsedOrder:
        from email import policy
        msg = email.message_from_bytes(raw_email_bytes, policy=policy.default)
        from_name, from_addr = self._parseaddr_robust(msg.get("From", ""))
        subject = self._decode_header(msg.get("Subject", ""))
        message_id = str(msg.get("Message-ID", ""))
        in_reply_to = str(msg.get("In-Reply-To", ""))

        # 提取正文
        instruction, attachments, thread_eml = self._extract_body(msg)
        thread = self._parse_thread(thread_eml)

        # 提取组织/电话
        organization = self._find_organization(subject + " " + instruction)
        contact_number = self._find_phone(instruction)

        # 提取约束
        constraints = self._find_constraints(instruction)

        # 推断场景
        scenario = self._detect_scenario(instruction + " " + subject)

        # 推断行业
        industry = self._detect_industry(instruction + " " + subject)

        return ParsedOrder(
            from_email=from_addr,
            from_name=from_name or from_addr,
            subject=subject,
            instruction=instruction,
            constraints=constraints,
            organization=organization,
            contact_number=contact_number,
            scenario=scenario,
            industry=industry,
            thread=thread,
            message_id=message_id,
            in_reply_to=in_reply_to,
        )

    @staticmethod
    def _decode_header(value) -> str:
        """RFC 2047 解码邮件 header。

        兼容 4 种形式：
        - 真的 =?utf-8?b?...=?>  → 走 decode_header
        - 已经 unicode 字符串     → 直接返回（必要时做 latin-1→utf-8 再解码）
        - bytes                  → utf-8 解码
        - email.header.Header    → str() 后按上面规则
        """
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                s = value.decode("utf-8")
            except Exception:
                s = value.decode("latin-1", errors="replace")
        else:
            s = str(value)

        # 判 RFC 2047 编码 (=?charset?...?=)
        if "=?" in s and "?=" in s:
            from email.header import decode_header, make_header
            try:
                return str(make_header(decode_header(s)))
            except Exception:
                return s

        # 启发式：如果字符串含 latin-1 范围外的字符（说明被错误按 latin-1 解了），
        # 尝试按 utf-8 / gbk 重解
        if any(ord(c) > 0x7F for c in s):
            try:
                fixed = s.encode("latin-1").decode("utf-8")
                # 检查重解后是否合理（含常见汉字范围）
                if any("\u4e00" <= c <= "\u9fff" for c in fixed):
                    return fixed
            except Exception:
                pass
            try:
                fixed = s.encode("latin-1").decode("gbk", errors="replace")
                if any("\u4e00" <= c <= "\u9fff" for c in fixed):
                    return fixed
            except Exception:
                pass
        return s

    @staticmethod
    def _parseaddr_robust(from_header) -> tuple[str, str]:
        """比 email.utils.parseaddr 更稳，能处理中文 quoted-printable 名字。
        返回 (name, email)。name 和 email 都做了 RFC 2047 解码。"""
        if not from_header:
            return "", ""
        s = EmailParser._decode_header(from_header).strip()

        # 1) 优先从 <...> 抓邮箱，剩余部分作为名字
        import re
        m = re.search(r"<([^<>]+@[^<>]+)>", s)
        if m:
            email = m.group(1).strip().lower()
            name = s[:m.start()].strip().strip('"').strip("'").strip()
            if not name:
                name = email
            return name, email

        # 2) 退路：纯邮箱
        m = re.search(r"[\w.+-]+@[\w.-]+", s)
        if m:
            return m.group(0), m.group(0).lower()

        return "", ""

    def _extract_body(self, msg) -> tuple[str, list, bytes | None]:
        """提取纯文本正文 + 附件列表 + 邮件链字节（如果有 .eml 附件或 message/rfc822 part）。"""
        text_parts = []
        attachments = []
        thread_eml = None

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                filename = part.get_filename()

                # 1) .eml 附件
                if filename and filename.lower().endswith(".eml"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        thread_eml = payload
                        continue

                # 2) message/rfc822 附件（QQ 邮箱常见）
                if ctype == "message/rfc822":
                    sub = part.get_payload()
                    if isinstance(sub, list) and sub:
                        sub_msg = sub[0]
                        try:
                            thread_eml = sub_msg.as_bytes()
                            attachments.append({
                                "filename": filename or "thread.eml",
                                "size": len(thread_eml),
                            })
                            continue
                        except Exception:
                            pass
                    elif isinstance(sub, str):
                        thread_eml = sub.encode("utf-8", errors="replace")
                        continue

                # 3) 常规文件附件
                if filename:
                    payload_bytes = part.get_payload(decode=True) or b""
                    attachments.append({
                        "filename": filename,
                        "size": len(payload_bytes),
                    })
                elif ctype == "text/plain":
                    try:
                        text_parts.append(part.get_payload(decode=True).decode("utf-8", errors="replace"))
                    except Exception:
                        pass
                elif ctype == "text/html":
                    # 简化处理：剥 HTML 标签
                    try:
                        html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        import re
                        text_parts.append(re.sub(r"<[^>]+>", " ", html))
                    except Exception:
                        pass
        else:
            ctype = msg.get_content_type()
            if ctype == "text/plain":
                text_parts.append(msg.get_payload(decode=True).decode("utf-8", errors="replace"))

        return "\n".join(text_parts).strip(), attachments, thread_eml

    def _parse_thread(self, thread_eml: bytes | None) -> list[dict]:
        """从 .eml 附件里解析邮件链。"""
        if not thread_eml:
            return []
        try:
            thread_msg = email.message_from_bytes(thread_eml)
            return [{
                "from": thread_msg.get("From", ""),
                "to": thread_msg.get("To", ""),
                "subject": thread_msg.get("Subject", ""),
                "date": thread_msg.get("Date", ""),
                "body": self._extract_body(thread_msg)[0][:1000],
            }]
        except Exception as e:
            log.warning(f"thread parse failed: {e}")
            return []

    def _find_organization(self, text: str) -> Optional[str]:
        """从文本里提取目标商家/工厂/酒店名（启发式）。"""
        # 1) 引号中的名称
        m = re.search(r"[""']([^""'」》]{3,40})[""']", text)
        if m:
            name = m.group(1)
            # 引号里如果是"不可加价"之类过滤
            if not any(kw in name for kw in ("不可", "不能", "加价", "涨价", "价格")):
                return name

        # 2) "帮(我)(给)X打电话/致电/联系" 模式 → 抓 X（X 直到电话/，/厂/店/酒店/工厂等）
        # 改进：在"打电话/致电/联系"前加锚点
        m = re.search(
            r"帮(?:我)?(?:给)?([^，。,\s]{2,30}?(?:酒店|宾馆|旅馆|工厂|厂|店|公司|集团|商行|商超|商厦|market|hotel|factory|store))",
            text,
        )
        if m:
            return m.group(1)

        # 3) "联系X" 直接抓
        m = re.search(
            r"(?:联系|致电|拨打|打给|打电话给|打电话)([^，。,\s]{2,30}?(?:酒店|宾馆|旅馆|工厂|厂|店|公司|集团|商行))",
            text,
        )
        if m:
            return m.group(1)

        # 4) "X酒店" / "X厂" / "X公司" 等单独
        m = re.search(
            r"([^\s，。,\d]{2,20}(?:酒店|宾馆|旅馆|工厂|厂|有限公司|集团|公司))",
            text,
        )
        if m:
            return m.group(1)

        return None

    def _find_phone(self, text: str) -> Optional[str]:
        for pat in self.PHONE_PATTERNS:
            m = pat.search(text)
            if m:
                return m.group(0).replace(" ", "").replace("-", "")
        return None

    def _find_constraints(self, text: str) -> Optional[str]:
        """提取约束（不可加价/尽量不加价/...）。"""
        patterns = [
            (r"(不可加价|不能加价|不准加价|价格不变|不涨价)", "不可加价"),
            (r"(尽量不加价|尽量不涨|价格压低)", "尽量不加价"),
            (r"(可以加价.{0,5}?[0-9]+%|加价不超过[0-9]+%)", None),  # 提取
        ]
        for pat, default in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0) if m.lastindex else default
        return None

    def _detect_scenario(self, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for scenario, kws in self.SCENARIO_KEYWORDS.items():
            scores[scenario] = sum(1 for kw in kws if kw.lower() in text_lower)
        if not scores or max(scores.values()) == 0:
            return "hotel"  # 默认
        return max(scores, key=scores.get)

    def _detect_industry(self, text: str) -> Optional[str]:
        """从文本里检测行业（独立于场景）。"""
        text_lower = text.lower()
        scores = {}
        for ind, kws in self.INDUSTRY_KEYWORDS.items():
            scores[ind] = sum(1 for kw in kws if kw.lower() in text_lower)
        if not scores or max(scores.values()) == 0:
            return None
        return max(scores, key=scores.get)


# === IMAP 客户端 ===
class IMAPClient:
    def __init__(self):
        self.imap: Optional[imaplib.IMAP4_SSL] = None

    def connect(self):
        log.info(f"imap.connect {IMAP_HOST}:{IMAP_PORT} user={IMAP_USER}")
        ctx = ssl.create_default_context()
        self.imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
        self.imap.login(IMAP_USER, IMAP_PASSWORD)
        self.imap.select("INBOX")

    def fetch_unseen(self, batch: int = 10) -> list[tuple[bytes, str, str]]:
        """取未读邮件。返回 [(原始 bytes, imap_uid, message_id), ...]。

        智能过滤：如果设置了 APPROVED_SENDERS，只从白名单发件人里取，避免被
        大量 postmaster 通知淹没（老邮箱常态）。

        关键：返回 IMAP UID（数字）供 mark_seen 用，不是 RFC822 Message-ID。
        """
        if not self.imap:
            self.connect()

        def _fetch_uid(uid: bytes) -> tuple[bytes, str, str] | None:
            typ, msg_data = self.imap.fetch(uid, "(RFC822 UID)")
            if typ != "OK" or not msg_data:
                return None
            # 找带 UID 的 fetch response
            uid_str = uid.decode()
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2:
                    # response 形如 b'1 (UID 12345 BODY[] {size}' 或 b')'
                    meta = part[0].decode() if isinstance(part[0], bytes) else part[0]
                    import re
                    m = re.search(r"UID (\d+)", meta)
                    if m:
                        uid_str = m.group(1)
                    raw = part[1]
                    if raw:
                        try:
                            msg = email.message_from_bytes(raw)
                            mid = str(msg.get("Message-ID", uid_str))
                        except Exception:
                            mid = uid_str
                        return raw, uid_str, mid
            return None

        # 白名单模式：按发件人逐个查，命中即收
        if APPROVED_SENDERS:
            results = []
            for sender in APPROVED_SENDERS:
                try:
                    typ, data = self.imap.search(None, "FROM", f'"{sender}"', "UNSEEN")
                except Exception:
                    typ, data = self.imap.search(None, "FROM", sender, "UNSEEN")
                if typ != "OK" or not data or not data[0]:
                    continue
                for msg_id in data[0].split()[:batch]:
                    res = _fetch_uid(msg_id)
                    if res:
                        results.append(res)
            return results

        # 无白名单：走老的 UNSEEN 全抓
        typ, data = self.imap.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        results = []
        for msg_id in data[0].split()[:batch]:
            res = _fetch_uid(msg_id)
            if res:
                results.append(res)
        return results

    def mark_seen(self, msg_id: str):
        """标邮件已读。msg_id 可以是 IMAP sequence number 或 UID，QQ IMAP 都兼容 sequence。"""
        if not self.imap or not msg_id:
            return
        try:
            # QQ IMAP IMAP4_SSL 默认模式：STORE 接 sequence 数字
            # 尝试 UID STORE first（如果传的是 UID），fallback sequence
            import re
            if msg_id.isdigit() and len(msg_id) < 8:
                # 大概率是 sequence number（QQ INBOX 万级）
                self.imap.store(msg_id, "+FLAGS", "\\Seen")
            else:
                self.imap.uid("STORE", msg_id, "+FLAGS", "\\Seen")
        except Exception as e:
            log.warning(f"imap.mark_seen failed for {msg_id[:30]}: {e}")
            # 终极退路：再用另一种方式
            try:
                self.imap.store(msg_id, "+FLAGS.SILENT", "\\Seen")
            except Exception as e2:
                log.error(f"imap.mark_seen FINAL fallback failed: {e2}")

    def close(self):
        if self.imap:
            try:
                self.imap.close()
                self.imap.logout()
            except Exception:
                pass
            self.imap = None


# === SMTP 客户端 ===
class SMTPClient:
    def __init__(self):
        self.smtp: Optional[smtplib.SMTP_SSL] = None

    def connect(self):
        log.info(f"smtp.connect {SMTP_HOST}:{SMTP_PORT} user={SMTP_USER}")
        ctx = ssl.create_default_context()
        self.smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30)
        self.smtp.login(SMTP_USER, SMTP_PASSWORD)

    def send(self, from_email: str, to_email: str, subject: str, body_text: str, body_html: Optional[str] = None, in_reply_to: Optional[str] = None):
        """发送邮件。"""
        if not self.smtp:
            self.connect()
        msg = EmailMessage()
        msg["From"] = f"{SMTP_FROM_NAME} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        self.smtp.send_message(msg)
        log.info(f"smtp.sent to={to_email} subject={subject}")

    def close(self):
        if self.smtp:
            try:
                self.smtp.quit()
            except Exception:
                pass
            self.smtp = None


# === API 客户端 ===
class BackendClient:
    """调后端 API 创建订单。"""

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self._client = httpx.Client(base_url=API_BASE, timeout=60)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def create_order(self, parsed: ParsedOrder) -> dict:
        """创建订单。返回 dict 带 order_id / status / scenario / intents。"""
        # 拼 requirement = instruction + thread 摘要
        req = parsed.instruction[:500]
        if parsed.thread:
            req += "\n\n[历史邮件摘要]\n" + parsed.thread[0].get("body", "")[:300]

        payload = {
            "organization": parsed.organization or "(待 AI 识别)",
            "contact_number": parsed.contact_number or "+10000000000",
            "requirement": req,
            "preferred_channel": "sms",  # 邮件→跨境用 SMS 触发
            "scenario": parsed.scenario if parsed.scenario in ("hotel", "car_rental", "flight") else "hotel",
            "user_email": parsed.from_email,  # 1.7.4: 进度通知回这个邮箱
        }
        if parsed.constraints:
            payload["constraints"] = parsed.constraints

        r = self._client.post("/api/orders", headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def get_order(self, order_id: str) -> dict:
        r = self._client.get(f"/api/orders/{order_id}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def wait_for_completion(self, order_id: str, timeout: int = 180) -> dict:
        """轮询等订单完成。"""
        elapsed = 0
        while elapsed < timeout:
            order = self.get_order(order_id)
            if order["status"] in ("success", "failed", "needs_user"):
                return order
            time.sleep(5)
            elapsed += 5
        return self.get_order(order_id)


# === 回复模板 ===
def _format_duration(seconds: int) -> str:
    """秒数 → 人话。"""
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"


def _status_emoji_and_label(status: str) -> tuple[str, str, str]:
    """状态 → (emoji, 中文标签, 副标题)。"""
    return {
        "success":     ("✅", "已成交",     "AI 替您办妥了，可以省心了"),
        "failed":      ("❌", "未能成交",   "AI 尽了最大努力，但没拿下。需要您介入或换策略"),
        "needs_user":  ("⚠️", "请您定夺",  "AI 谈到了一个关键节点，等您一句话就能推进"),
        "in_progress": ("⏳", "进行中",     "AI 正在与商家沟通，请稍候"),
    }.get(status, ("❓", status, "状态待定"))


def _eval_human_label(total: int) -> str:
    """评分 → 人类话术。"""
    if total >= 90: return "比 5 年经验的采购老手还稳"
    if total >= 80: return "有专业采购的范儿"
    if total >= 70: return "基本在线，个别环节可以更圆滑"
    if total >= 60: return "勉强及格，下次能更好"
    return "这次表现欠佳，已记录改进"


def build_reply(parsed: ParsedOrder, order: dict) -> tuple[str, str]:
    """生成纪要邮件 (纯文本 + HTML)。

    设计目标：让客户觉得这是一件「难搞的事」被 AI 漂亮解决了。
    关键改造：
    1. 顶部"任务报告"风格，类甲方交付单
    2. 任务量可视化（沟通轮数 / 商家响应 / 节省时间）
    3. 人类话术评价，不是"AI 评分 X/100"
    4. 强结论、收尾引导下一步
    """
    result = order.get("result") or {}
    summary = result.get("summary", "")
    evaluation = result.get("evaluation")
    tried_strategies = result.get("tried_strategies", [])
    dialogue = order.get("dialogue", [])[-6:]

    status = order["status"]
    emoji, status_label, status_subtitle = _status_emoji_and_label(status)

    # === 任务量统计 ===
    rounds = len([t for t in order.get("dialogue", []) if t.get("speaker") == "ai"])
    merchant_responses = len([t for t in order.get("dialogue", []) if t.get("speaker") != "ai"])
    elapsed = result.get("elapsed_seconds", rounds * 15 + 10)
    saved_minutes = max(8, rounds * 4)  # 估算 AI 帮客户省的时间

    # === 主体业务字段 ===
    org = order.get("organization", "")
    scenario_zh = {"hotel": "酒店", "car_rental": "租车", "flight": "机票",
                   "price_negotiation": "议价", "order_modify": "改单",
                   "claim_dispute": "客诉", "sample_confirm": "样品确认",
                   "reconciliation": "对账"}.get(order.get("scenario", ""), "代办")
    eval_total = evaluation.get("total", 0) if evaluation else 0

    # === 时间戳（人类话术） ===
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    time_str = now.strftime("%m月%d日 %H:%M")

    # ===== 纯文本版 =====
    text_lines = [
        f"{emoji} {status_label} · {org}",
        "",
        f"{status_subtitle}。",
        "",
        f"────── 任务报告 ──────",
        f"📌 任务：{scenario_zh}代办 · {org}",
        f"📅 完成时间：{time_str}",
        f"⏱️  用时：{_format_duration(int(elapsed))}（约为您手动处理需 {saved_minutes} 分钟）",
        f"💬 与商家沟通 {rounds} 轮，商家回复 {merchant_responses} 次",
        f"🎯 策略：{', '.join(tried_strategies) if tried_strategies else '标准流程'}",
        "",
    ]

    if evaluation:
        text_lines.extend([
            f"────── AI 表现 ──────",
            f"综合评分：{eval_total}/100 · {_eval_human_label(eval_total)}",
        ])
        for k, v in evaluation.get("dimensions", {}).items():
            text_lines.append(f"  · {v.get('label', k)}：{v.get('score', 0)}/{v.get('max', 0)}")
        if evaluation.get("suggestions"):
            text_lines.append("")
            text_lines.append("下次可以更好：")
            for s in evaluation["suggestions"][:2]:
                text_lines.append(f"  · {s}")
        text_lines.append("")

    if summary:
        text_lines.extend([
            f"────── 核心摘要 ──────",
            summary,
            "",
        ])

    if dialogue:
        text_lines.extend([
            f"────── 关键对话 ──────",
        ])
        for t in dialogue[-4:]:
            speaker = "AI" if t["speaker"] == "ai" else "商家"
            text_lines.append(f"[{speaker}] {t.get('translated', t.get('original', ''))[:240]}")
        text_lines.append("")

    if status == "success":
        text_lines.extend([
            f"────── 下一步 ──────",
            f"这事 AI 替您办妥了，您可以放心了。",
            f"如需追加订单 / 修改 / 转人工，直接回这封邮件即可。",
            "",
        ])
    elif status == "needs_user":
        text_lines.extend([
            f"────── 等您一句话 ──────",
            f"AI 已经把价格/条款谈到这儿了，再推进需要您拍板：",
            f"  · 回复「确认」→ AI 替您发确认给商家",
            f"  · 回复「取消」→ AI 终止此单",
            f"  · 回复「转人工」→ 安排真人客服接手",
            "",
        ])
    elif status == "failed":
        text_lines.extend([
            f"────── 下一步 ──────",
            f"AI 跑了 {rounds} 轮未能成交。已记录失败原因。",
            f"您可以：回复「重试」/「换商家」/「转人工」",
            "",
        ])

    text_lines.extend([
        "─" * 50,
        f"📎 完整记录：订单 {order['id']} · 您的 AI 外贸助理",
        f"⚡ 24h 在线 · 全程双语文 · 一封邮件的活儿",
    ])
    text = "\n".join(text_lines)

    # ===== HTML 版（更专业） =====
    # 状态色
    if status == "success":
        banner_bg = "linear-gradient(135deg, #2fd47e 0%, #1ba860 100%)"
        banner_text = "#0a3a26"
    elif status == "failed":
        banner_bg = "linear-gradient(135deg, #ff5e5e 0%, #c93030 100%)"
        banner_text = "#3a0a0a"
    else:  # needs_user
        banner_bg = "linear-gradient(135deg, #f5a524 0%, #d97a00 100%)"
        banner_text = "#3a2200"

    # 任务量数字块
    stat_blocks = "".join([
        f"""<div style='flex:1;background:#14181f;padding:14px;border-radius:8px;text-align:center;'>
  <div style='font-size:24px;font-weight:700;color:#4f8cff;'>{rounds}</div>
  <div style='font-size:11px;color:#8a93a6;margin-top:4px;'>AI 沟通轮数</div>
</div>""",
        f"""<div style='flex:1;background:#14181f;padding:14px;border-radius:8px;text-align:center;'>
  <div style='font-size:24px;font-weight:700;color:#7c5cff;'>{merchant_responses}</div>
  <div style='font-size:11px;color:#8a93a6;margin-top:4px;'>商家回应次数</div>
</div>""",
        f"""<div style='flex:1;background:#14181f;padding:14px;border-radius:8px;text-align:center;'>
  <div style='font-size:24px;font-weight:700;color:#2fd47e;'>≈{saved_minutes}<span style='font-size:14px;'>分</span></div>
  <div style='font-size:11px;color:#8a93a6;margin-top:4px;'>为您省下</div>
</div>""",
    ])

    # 评分表
    eval_html = ""
    if evaluation:
        dims = evaluation.get("dimensions", {})
        rows = "".join(
            f"""<tr>
  <td style='padding:8px 0;color:#c5cdd9;font-size:13px;width:35%;'>{v.get('label', k)}</td>
  <td style='padding:8px 0;font-weight:600;font-size:13px;width:15%;'>{v.get('score', 0)}/{v.get('max', 0)}</td>
  <td style='padding:8px 0;width:50%;'><div style='background:#1c2230;height:6px;border-radius:3px;'>
    <div style='background:linear-gradient(90deg,#4f8cff,#7c5cff);height:6px;border-radius:3px;width:{v.get('score', 0) / max(v.get('max', 1), 1) * 100:.0f}%;'></div>
  </div></td>
</tr>"""
            for k, v in dims.items()
        )
        eval_html = f"""
<div style='background:#0b0d12;border:1px solid #1c2230;border-radius:8px;padding:18px;margin:18px 0;'>
  <div style='display:flex;align-items:baseline;justify-content:space-between;margin-bottom:12px;'>
    <h3 style='font-size:14px;color:#e6ebf3;margin:0;'>🧠 AI 表现</h3>
    <div>
      <span style='font-size:24px;font-weight:700;color:#4f8cff;'>{eval_total}</span>
      <span style='color:#8a93a6;font-size:12px;'>/100</span>
    </div>
  </div>
  <div style='font-size:13px;color:#7c5cff;margin-bottom:12px;font-style:italic;'>"{_eval_human_label(eval_total)}"</div>
  <table style='width:100%;border-collapse:collapse;'>{rows}</table>
</div>"""

    # 对话回放
    dialogue_html = ""
    if dialogue:
        items = "".join(
            f"""<div style='padding:10px 12px;margin:6px 0;border-radius:6px;
background:{'rgba(79,140,255,0.08);border-left:3px solid #4f8cff;' if t['speaker']=='ai' else 'rgba(245,165,36,0.08);border-left:3px solid #f5a524;'}'>
  <div style='font-size:11px;color:#8a93a6;margin-bottom:4px;font-weight:600;'>
    {'🤖 AI 外贸助理' if t['speaker']=='ai' else '🏨 ' + (org or '商家')}
  </div>
  <div style='color:#c5cdd9;font-size:13px;line-height:1.6;'>{t.get('translated', t.get('original', ''))[:280]}</div>
</div>"""
            for t in dialogue[-4:]
        )
        dialogue_html = f"""
<div style='background:#0b0d12;border:1px solid #1c2230;border-radius:8px;padding:18px;margin:18px 0;'>
  <h3 style='font-size:14px;color:#e6ebf3;margin:0 0 12px;'>💬 关键对话回放</h3>
  {items}
</div>"""

    # 下一步 CTA
    cta_html = ""
    if status == "success":
        cta_html = f"""
<div style='background:rgba(47,212,126,0.08);border:1px solid rgba(47,212,126,0.3);border-radius:8px;padding:18px;margin:18px 0;'>
  <div style='font-size:16px;font-weight:600;color:#2fd47e;margin-bottom:6px;'>这事 AI 替您办妥了 ✓</div>
  <div style='font-size:13px;color:#c5cdd9;line-height:1.6;'>
    您可以放心了。需要追加订单 / 修改 / 转人工，直接回复这封邮件即可。
  </div>
</div>"""
    elif status == "needs_user":
        cta_html = f"""
<div style='background:rgba(245,165,36,0.08);border:1px solid rgba(245,165,36,0.3);border-radius:8px;padding:18px;margin:18px 0;'>
  <div style='font-size:16px;font-weight:600;color:#f5a524;margin-bottom:10px;'>⚡ 等您一句话</div>
  <div style='font-size:13px;color:#c5cdd9;line-height:1.8;'>
    AI 已经把价格/条款谈到这儿了，再推进需要您拍板：<br/>
    <span style='color:#f5a524;'>·</span> 回复 <b>「确认」</b> → AI 替您发确认给商家<br/>
    <span style='color:#f5a524;'>·</span> 回复 <b>「取消」</b> → AI 终止此单<br/>
    <span style='color:#f5a524;'>·</span> 回复 <b>「转人工」</b> → 安排真人客服接手
  </div>
</div>"""
    elif status == "failed":
        cta_html = f"""
<div style='background:rgba(255,94,94,0.08);border:1px solid rgba(255,94,94,0.3);border-radius:8px;padding:18px;margin:18px 0;'>
  <div style='font-size:16px;font-weight:600;color:#ff5e5e;margin-bottom:10px;'>AI 跑了 {rounds} 轮未能成交</div>
  <div style='font-size:13px;color:#c5cdd9;line-height:1.6;'>
    已记录失败原因。您可以回复 <b>「重试」</b> / <b>「换商家」</b> / <b>「转人工」</b>。
  </div>
</div>"""

    # 策略块
    strategy_html = ""
    if tried_strategies:
        chips = "".join(
            f"<span style='display:inline-block;padding:4px 10px;background:rgba(79,140,255,0.12);"
            f"color:#4f8cff;border-radius:12px;font-size:12px;margin:2px;'>{s}</span>"
            for s in tried_strategies
        )
        strategy_html = f"""
<div style='margin:12px 0;'>
  <span style='font-size:12px;color:#8a93a6;'>🤝 协商策略：</span>{chips}
</div>"""

    # 摘要块
    summary_html = ""
    if summary:
        summary_html = f"""
<div style='background:linear-gradient(135deg,rgba(79,140,255,0.08),rgba(124,92,255,0.08));
border-left:3px solid #4f8cff;padding:16px 18px;border-radius:6px;margin:18px 0;'>
  <div style='font-size:12px;color:#7c5cff;font-weight:600;margin-bottom:6px;'>📋 核心摘要</div>
  <div style='color:#e6ebf3;font-size:14px;line-height:1.7;'>{summary}</div>
</div>"""

    # 任务量可视化
    stats_html = f"""
<div style='display:flex;gap:10px;margin:18px 0;'>
  {stat_blocks}
</div>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0b0d12;font-family:-apple-system,BlinkMacSystemFont,'SF Pro SC','PingFang SC','Helvetica Neue',sans-serif;">
<div style="max-width:680px;margin:0 auto;padding:24px;color:#e6ebf3;">

  <!-- 状态横幅 -->
  <div style="background:{banner_bg};padding:24px 28px;border-radius:12px;margin-bottom:0;color:{banner_text};">
    <div style="font-size:36px;margin-bottom:6px;">{emoji}</div>
    <div style="font-size:24px;font-weight:700;margin-bottom:6px;">{status_label}</div>
    <div style="font-size:14px;opacity:0.85;">{status_subtitle}</div>
  </div>

  <div style="background:#0b0d12;padding:20px 24px;border-left:1px solid #1c2230;border-right:1px solid #1c2230;">
    <div style="font-size:12px;color:#8a93a6;margin-bottom:4px;">📌 任务</div>
    <div style="font-size:18px;font-weight:600;margin-bottom:12px;">{scenario_zh}代办 · {org}</div>
    <div style="font-size:12px;color:#8a93a6;">📅 {time_str} · 订单 <code style="background:#1c2230;padding:2px 6px;border-radius:3px;">{order['id']}</code></div>
  </div>

  <div style="background:#0b0d12;padding:20px 24px 24px;border:1px solid #1c2230;border-top:0;border-radius:0 0 12px 12px;">
    {stats_html}
    {strategy_html}
    {summary_html}
    {eval_html}
    {dialogue_html}
    {cta_html}

    <!-- 页脚 -->
    <div style="border-top:1px solid #1c2230;padding-top:16px;margin-top:24px;font-size:12px;color:#8a93a6;line-height:1.6;">
      <div style="font-weight:600;color:#c5cdd9;margin-bottom:4px;">AI 外贸助理 · 您的 24h 双语秘书</div>
      <div>一封邮件的活儿 · 跨语言、跨时区、跨文化 · 不接就不收费</div>
      <div style="margin-top:8px;">
        <a href="mailto:aiagent@qq.com?subject=Re:{order['id']}" style="color:#4f8cff;text-decoration:none;">📩 回复这封邮件继续沟通</a>
      </div>
    </div>
  </div>

</div>
</body></html>"""
    return text, html


# === Worker 主循环 ===
async def process_one(imap: IMAPClient, smtp: SMTPClient, api: BackendClient, raw_email: bytes, imap_uid: str, message_id: str):
    """处理一封邮件。imap_uid 用于标已读，message_id 用于回信追踪。"""
    parser = EmailParser()
    parsed = parser.parse(raw_email)

    # 白名单（理论上 fetch_unseen 已过滤，这里再保险一次）
    from_lower = (parsed.from_email or "").lower()
    if APPROVED_SENDERS and from_lower not in APPROVED_SENDERS:
        log.info(f"skip non-whitelisted sender: {parsed.from_email}")
        imap.mark_seen(imap_uid)  # 标已读别再处理
        return False

    log.info(f"process email from={parsed.from_email} subject={parsed.subject[:60]}")
    log.info(f"  parsed: org={parsed.organization} phone={parsed.contact_number} scenario={parsed.scenario} industry={parsed.industry}")

    # 创建订单
    try:
        order = api.create_order(parsed)
        order_id = order["order_id"]
        log.info(f"  order.created id={order_id}")
    except Exception as e:
        log.error(f"  create_order failed: {e}")
        imap.mark_seen(imap_uid)  # 失败也标已读，避免死循环
        return False

    # 等待完成
    final = api.wait_for_completion(order_id, timeout=300)
    log.info(f"  order.done status={final['status']}")

    # 回信
    text, html = build_reply(parsed, final)
    smtp.send(
        from_email=SMTP_USER,
        to_email=parsed.from_email,
        subject=f"Re: {parsed.subject}",
        body_text=text,
        body_html=html,
        in_reply_to=message_id or None,
    )

    imap.mark_seen(imap_uid)
    return True


async def main():
    if not IMAP_USER or not IMAP_PASSWORD:
        log.error("IMAP_USER / IMAP_PASSWORD not set")
        return
    if not APPROVED_SENDERS:
        log.warning("APPROVED_SENDERS not set, will process ALL senders (demo only!)")

    imap = IMAPClient()
    smtp = SMTPClient()
    api = BackendClient()

    log.info(f"email_worker started, poll every {POLL_INTERVAL}s")

    while True:
        try:
            unseen = imap.fetch_unseen(batch=5)
            for raw, imap_uid, message_id in unseen:
                await process_one(imap, smtp, api, raw, imap_uid, message_id)
        except Exception as e:
            log.error(f"loop error: {e}")
            # 重连
            try:
                imap.close()
            except Exception:
                pass
            imap = IMAPClient()
            try:
                smtp.close()
            except Exception:
                pass
            smtp = SMTPClient()

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
