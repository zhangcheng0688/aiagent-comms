"""FastAPI 入口 + 路由。

整合 V1.0 基础 + A1 评估 + A2 鉴权 + A4 可观测性。
"""
from __future__ import annotations
import uuid
import time
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .config import HOST, PORT
from .models import Order, OrderCreate, OrderState, OrderStatus, NegotiationProposal, IntentSlot, DialogueTurn
from .storage_backend import storage, get_storage_backend
from .core.intent_parser import parse_intent, detect_target_language, detect_scenario
from .core.dialogue import DialogueEngine
from .core.evaluator import evaluate_order, score_to_dict
from .channels.voice import VoiceChannel, handle_twilio_gather_webhook
from .channels.sms import SmsChannel
from .core.translator import translate
from .auth import (
    Org, User, AuthToken, RegisterRequest, LoginRequest, AuthResponse,
    hash_password, verify_password, issue_token, verify_token,
)
from .ws_manager import ws_manager, WSEvent
from .domains import get_domain_loader

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# === A4 可观测性：loguru 替 print ===
class _JsonFormatter(logging.Formatter):
    def format(self, record):
        return (
            f'{{"ts":"{datetime.utcnow().isoformat()}","level":"{record.levelname}",'
            f'"logger":"{record.name}","msg":"{record.getMessage().replace(chr(34), chr(92)+chr(34))}"}}'
        )

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("aiagent")
startup_time = time.time()

voice = VoiceChannel()
sms = SmsChannel()

# 1.7.5 实时进度回调：每轮对话结束后写 DB + 推 WS
async def _on_dialogue_turn(order):
    await storage.update_order(order)
    if order.dialogue:
        last = order.dialogue[-1]
        await ws_manager.broadcast(
            order.id,
            WSEvent.dialogue_turn(
                order.id,
                speaker=last.speaker,
                text=(last.translated or last.original or "")[:200],
                turn_id=last.turn_id,
            ),
        )

engine = DialogueEngine(voice=voice, sms=sms, on_turn=_on_dialogue_turn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.init()
    log.info(f"🚀 AI 全权代办沟通 V2.1 启动 http://{HOST}:{PORT}")
    log.info(f"   前台: /static/submit.html  后台: /static/admin.html")
    yield


app = FastAPI(title="AI 全权代办沟通", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === A4: 简单请求日志中间件 ===
@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    elapsed_ms = int((time.time() - t0) * 1000)
    if request.url.path.startswith("/api/") and elapsed_ms > 200:
        log.info(f"{request.method} {request.url.path} → {response.status_code} {elapsed_ms}ms")
    return response


# === A2: 鉴权依赖 ===
async def current_user(authorization: str | None = Header(default=None)) -> tuple[User, Org]:
    """Bearer token 鉴权依赖。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "需要 Bearer token")
    raw = authorization[7:].strip()
    h = __import__("hashlib").sha256(raw.encode()).hexdigest()
    token = await storage.get_token(h)
    if not token:
        raise HTTPException(401, "无效 token")
    if token.expires_at < datetime.utcnow():
        raise HTTPException(401, "token 已过期")
    user = await storage.get_user(token.user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    org = await storage.get_org(token.org_id)
    if not org:
        raise HTTPException(401, "组织不存在")
    await storage.touch_token(h)
    return user, org


async def optional_user(authorization: str | None = Header(default=None)) -> tuple[User, Org] | None:
    """可选鉴权 - 不强制，方便前端渐进。"""
    if not authorization:
        return None
    try:
        return await current_user(authorization)
    except HTTPException:
        return None


# === A2: Auth 路由 ===
@app.post("/api/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest):
    existing = await storage.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(400, "邮箱已注册")
    org = Org(
        id=f"org_{uuid.uuid4().hex[:8]}",
        name=payload.org_name,
        plan="free",
        created_at=datetime.utcnow(),
    )
    await storage.create_org(org)
    ph, salt = hash_password(payload.password)
    user = User(
        id=f"usr_{uuid.uuid4().hex[:8]}",
        org_id=org.id,
        email=payload.email,
        name=payload.name,
        password_hash=ph,
        password_salt=salt,
        role="admin",
        created_at=datetime.utcnow(),
    )
    await storage.create_user(user)
    raw, h = issue_token()
    token = AuthToken(
        token_hash=h,
        user_id=user.id,
        org_id=org.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    await storage.create_token(token)
    return AuthResponse(
        user=user.model_dump(exclude={"password_hash", "password_salt"}),
        org=org.model_dump(),
        token=raw,
        expires_at=token.expires_at,
    )


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    user = await storage.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user.password_hash, user.password_salt):
        raise HTTPException(401, "邮箱或密码错误")
    org = await storage.get_org(user.org_id)
    if not org:
        raise HTTPException(500, "组织不存在")
    raw, h = issue_token()
    token = AuthToken(
        token_hash=h, user_id=user.id, org_id=org.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    await storage.create_token(token)
    return AuthResponse(
        user=user.model_dump(exclude={"password_hash", "password_salt"}),
        org=org.model_dump(),
        token=raw,
        expires_at=token.expires_at,
    )


@app.get("/api/auth/me")
async def me(auth: tuple[User, Org] = Depends(current_user)):
    user, org = auth
    return {
        "user": user.model_dump(exclude={"password_hash", "password_salt"}),
        "org": org.model_dump(),
    }


# === 订单 API ===
@app.post("/api/orders")
async def create_order(
    payload: OrderCreate,
    bg: BackgroundTasks,
    auth: tuple[User, Org] | None = Depends(optional_user),
):
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    target_lang = detect_target_language(payload.contact_number, payload.organization)
    scenario = payload.scenario
    if scenario == "hotel" or not scenario:
        scenario = detect_scenario(payload.requirement, payload.organization)

    intents = await parse_intent(payload.requirement, payload.constraints, scenario)

    order = Order(
        id=order_id,
        organization=payload.organization,
        contact_number=payload.contact_number,
        requirement=payload.requirement,
        constraints=payload.constraints,
        target_language=target_lang,
        preferred_channel=payload.preferred_channel,
        scenario=scenario,
        state=OrderState.INIT,
        status=OrderStatus.PENDING,
        intents=intents,
        dialogue=[],
        result=None,
        org_id=auth[0].org_id if auth else None,
        user_id=auth[0].id if auth else None,
        user_email=payload.user_email,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await storage.create_order(order)
    bg.add_task(_run_order_in_background, order_id)
    log.info(f"order.created id={order_id} scenario={scenario} org={order.org_id or 'anon'}")

    return {
        "order_id": order_id,
        "scenario": scenario,
        "intents": [i.model_dump() for i in intents],
        "target_language": target_lang,
        "status_url": f"/api/orders/{order_id}",
    }


async def _run_order_in_background(order_id: str):
    """后台：跑全流程 + 跑 V2.1 评估 + 实时推 WS。"""
    order = await storage.get_order(order_id)
    if not order:
        return
    try:
        order.status = OrderStatus.IN_PROGRESS
        await storage.update_order(order)
        await ws_manager.broadcast(order_id, WSEvent.status_changed(order_id, "in_progress"))
        t0 = time.time()
        updated = await engine.run(order)
        await storage.update_order(updated)
        elapsed = int((time.time() - t0) * 1000)
        log.info(f"order.dialogue_done id={order_id} status={updated.status.value} elapsed={elapsed}ms")
        await ws_manager.broadcast(order_id, WSEvent.status_changed(order_id, updated.status.value))

        # A1: 跑评估（异步，不阻塞订单本身）
        try:
            score = await evaluate_order(updated)
            result = dict(updated.result or {})
            result["evaluation"] = score_to_dict(score)
            updated.result = result
            await storage.update_order(updated)
            log.info(f"order.evaluated id={order_id} total={score.total} engine={score.engine}")
            await ws_manager.broadcast(order_id, WSEvent.evaluation_ready(order_id, score_to_dict(score)))
        except Exception as e:
            log.warning(f"order.evaluate_failed id={order_id} err={e}")

    except Exception as e:
        order.status = OrderStatus.FAILED
        order.result = {"error": str(e)}
        await storage.update_order(order)
        log.error(f"order.failed id={order_id} err={e}")
        await ws_manager.broadcast(order_id, WSEvent.status_changed(order_id, "failed"))


@app.get("/api/orders/{order_id}")
async def get_order(order_id: str, auth: tuple[User, Org] | None = Depends(optional_user)):
    order = await storage.get_order(order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    # 鉴权：org 隔离
    if auth and order.org_id and order.org_id != auth[1].id:
        raise HTTPException(403, "无权查看此订单")
    return order.model_dump(mode="json")


@app.get("/api/orders")
async def list_orders(
    limit: int = 20,
    auth: tuple[User, Org] | None = Depends(optional_user),
):
    org_id = auth[1].id if auth else None
    orders = await storage.list_orders(limit=limit, org_id=org_id)
    return [o.model_dump(mode="json") for o in orders]


@app.post("/api/orders/{order_id}/resolve-proposal")
async def resolve_proposal(order_id: str, payload: dict, auth: tuple[User, Org] | None = Depends(optional_user)):
    order = await storage.get_order(order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    if auth and order.org_id and order.org_id != auth[1].id:
        raise HTTPException(403, "无权操作此订单")
    if order.state != OrderState.AWAIT_USER:
        raise HTTPException(400, f"当前状态不是 AWAIT_USER，是 {order.state}")

    choice = payload.get("choice")
    proposal = (order.result or {}).get("proposal", {})

    if choice == "abort":
        order.state = OrderState.CLOSING_FAILURE
        order.status = OrderStatus.FAILED
        order.result = {**(order.result or {}), "user_choice": "abort"}
        await storage.update_order(order)
        return order.model_dump(mode="json")

    chosen = next((opt for opt in proposal.get("options", []) if opt.get("option_id") == choice), None)
    if not chosen:
        raise HTTPException(400, f"无效选项 {choice}")

    order.state = OrderState.NEGOTIATING
    order.status = OrderStatus.IN_PROGRESS
    order.intents.append(IntentSlot(
        slot_id=f"user_choice_{choice}",
        type="modify",
        description=f"用户选择：{chosen.get('label')}",
        target_value=chosen.get("label"),
        confirmed_value=chosen.get("label"),
        priority=99,
    ))
    order.result = {**(order.result or {}), "user_choice": choice, "chosen_option": chosen}
    await storage.update_order(order)

    lang = order.target_language
    ai_continue = f"了解しました。オプション{choice}でお願いします。" if lang == "ja" else (
        f"네, {choice}번 옵션으로 진행하겠습니다." if lang == "ko"
        else f"Okay, let's go with option {choice}."
    )
    merchant_reply = await voice.call(order.contact_number, ai_continue, lang) if order.preferred_channel.value == "voice" else await sms.send(order.contact_number, ai_continue)
    order.dialogue.append(DialogueTurn(
        turn_id=len(order.dialogue) + 1, speaker="ai", original=ai_continue, translated=ai_continue,
        timestamp=datetime.utcnow()
    ))
    order.dialogue.append(DialogueTurn(
        turn_id=len(order.dialogue) + 1, speaker="merchant", original=merchant_reply,
        translated=await translate(merchant_reply, "zh", lang), timestamp=datetime.utcnow()
    ))
    order.state = OrderState.CLOSING_SUCCESS
    order.status = OrderStatus.SUCCESS
    order.result = {**(order.result or {}), "summary": f"已按用户选择{chosen.get('label')}完成", "confirmed_intents": [i.model_dump() for i in order.intents]}
    await storage.update_order(order)
    return order.model_dump(mode="json")


# === A4: 健康检查 + 指标 ===
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "V2.1",
        "uptime_seconds": int(time.time() - startup_time),
        "ts": datetime.utcnow().isoformat(),
    }


@app.get("/api/metrics")
async def metrics(auth: tuple[User, Org] | None = Depends(optional_user)):
    """组织级运营指标。anon 模式返全局。"""
    org_id = auth[1].id if auth else None
    total = await storage.count_orders(org_id=org_id)
    by_status = await storage.count_orders_by_status(org_id=org_id)
    avg_eval = await storage.avg_evaluation_total(org_id=org_id)
    return {
        "orders": {
            "total": total,
            "by_status": by_status,
            "success_rate": round(by_status.get("success", 0) / total * 100, 1) if total > 0 else 0,
        },
        "ai_quality": {
            "avg_evaluation_total": avg_eval,
            "samples": "未实现",
        },
        "scope": "org" if org_id else "global",
    }


# 静态前端
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# === Twilio Webhook ===
@app.post("/webhooks/twilio/init")
async def twilio_init_webhook():
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    resp.say("Hello, this is a test call.", voice="alice")
    resp.gather(input_="speech", timeout=5, action="/webhooks/twilio/gather", method="POST")
    resp.hangup()
    return Response(content=str(resp), media_type="application/xml")


@app.post("/webhooks/twilio/gather")
async def twilio_gather_webhook(request: Request):
    from twilio.twiml.voice_response import VoiceResponse
    form = await request.form()
    call_sid = form.get("CallSid", "")
    speech = form.get("SpeechResult", "")
    confidence = form.get("Confidence", "0")
    log.info(f"twilio.gather call_sid={call_sid} conf={confidence}")
    handle_twilio_gather_webhook(call_sid, speech)
    resp = VoiceResponse()
    resp.hangup()
    return Response(content=str(resp), media_type="application/xml")


@app.get("/")
async def root():
    return RedirectResponse(url="/static/submit.html")


@app.get("/order/{order_id}")
async def order_page(order_id: str):
    return RedirectResponse(url=f"/static/order.html?id={order_id}")


@app.get("/negotiate/{order_id}")
async def negotiate_page(order_id: str):
    return RedirectResponse(url=f"/static/negotiate.html?id={order_id}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, order_id: str = ""):
    """WebSocket 端点：客户端订阅订单状态变化。

    连接 URL: ws://host:port/ws?order_id=ord_xxx
    """
    await websocket.accept()
    if not order_id:
        await websocket.send_json({"type": "error", "message": "missing order_id"})
        await websocket.close()
        return
    await ws_manager.connect(order_id, websocket)
    try:
        # 推送当前订单状态
        order = await storage.get_order(order_id)
        if order:
            await websocket.send_json(WSEvent.status_changed(
                order_id, order.status.value,
                result=order.result or {},
            ))
        # 接收客户端消息（心跳）
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(order_id, websocket)
    except Exception as e:
        log.warning(f"ws.error: {e}")
        await ws_manager.disconnect(order_id, websocket)


# === V3.0 行业 API ===
@app.get("/api/industries")
async def list_industries():
    """列出所有行业。"""
    loader = get_domain_loader()
    return {
        "industries": [
            {"key": k, "label": (loader.get_industry(k) or {}).get("label", k),
             "scenario_count": len((loader.get_industry(k) or {}).get("scenarios", {}))}
            for k in loader.list_industries()
        ]
    }


@app.get("/api/industries/{industry}/scenarios")
async def list_scenarios(industry: str):
    """列出某行业的所有场景。"""
    loader = get_domain_loader()
    ind = loader.get_industry(industry)
    if not ind:
        raise HTTPException(404, f"未知行业: {industry}")
    return {
        "industry": industry,
        "label": ind.get("label"),
        "scenarios": [
            {"key": k,
             "label": v.get("scenario_label", k),
             "desc": v.get("scenario_desc", ""),
             "phrasebook_languages": list({p["lang"] for p in v.get("phrasebook", [])})}
            for k, v in ind.get("scenarios", {}).items()
        ]
    }


@app.post("/api/industries/detect")
async def detect_industry(payload: dict):
    """根据文本自动检测行业 + 场景。"""
    text = payload.get("text", "")
    industry = get_domain_loader().detect_industry(text)
    scenario = None
    if industry:
        scenario = get_domain_loader().detect_scenario(text, industry)
    return {"text": text, "industry": industry, "scenario": scenario}


@app.get("/api/industries/{industry}/prompt-injection")
async def get_prompt_injection(industry: str, scenario: str = "sample_confirm", lang: str = "en"):
    """获取某 (行业, 场景, 语种) 的 Prompt 注入片段。"""
    loader = get_domain_loader()
    text = loader.build_prompt_injection(industry, scenario, lang)
    return {"industry": industry, "scenario": scenario, "lang": lang, "injection": text}


@app.get("/admin")
async def admin_page():
    return FileResponse(FRONTEND_DIR / "admin.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)
