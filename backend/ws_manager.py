"""V3.0 WebSocket 服务：订单状态变化时实时推客户端。

设计：
- 房间模式：每订单一个 room (key = order_id)
- 服务端广播：订单状态变化触发 broadcast
- 鉴权：可选 Bearer token（生产路径必须；demo 允许匿名）
- 优雅降级：ws 挂了不影响主流程
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional
from collections import defaultdict

log = logging.getLogger("aiagent.ws")


class WebSocketManager:
    """轻量 WebSocket 房间管理。"""

    def __init__(self):
        self._rooms: dict[str, set] = defaultdict(set)  # order_id -> {websocket}
        self._lock = asyncio.Lock()

    async def connect(self, order_id: str, websocket) -> None:
        async with self._lock:
            self._rooms[order_id].add(websocket)
        log.info(f"ws.connect order={order_id} total={len(self._rooms[order_id])}")

    async def disconnect(self, order_id: str, websocket) -> None:
        async with self._lock:
            if order_id in self._rooms:
                self._rooms[order_id].discard(websocket)
                if not self._rooms[order_id]:
                    del self._rooms[order_id]

    async def broadcast(self, order_id: str, event: dict) -> int:
        """广播事件到某订单的所有 ws 客户端。返回收到数。"""
        async with self._lock:
            sockets = list(self._rooms.get(order_id, set()))
        if not sockets:
            return 0
        msg = json.dumps(event, ensure_ascii=False, default=str)
        delivered = 0
        for ws in sockets:
            try:
                await ws.send_text(msg)
                delivered += 1
            except Exception as e:
                log.warning(f"ws.send failed: {e}")
                await self.disconnect(order_id, ws)
        return delivered

    def room_count(self, order_id: str) -> int:
        return len(self._rooms.get(order_id, set()))


# 全局单例
ws_manager = WebSocketManager()


# === 事件类型 ===
class WSEvent:
    """标准 WebSocket 事件格式。"""
    @staticmethod
    def status_changed(order_id: str, status: str, **extra) -> dict:
        return {"type": "status_changed", "order_id": order_id, "status": status, **extra}

    @staticmethod
    def evaluation_ready(order_id: str, evaluation: dict) -> dict:
        return {"type": "evaluation_ready", "order_id": order_id, "evaluation": evaluation}

    @staticmethod
    def dialogue_turn(order_id: str, speaker: str, text: str, turn_id: int) -> dict:
        return {"type": "dialogue_turn", "order_id": order_id,
                "speaker": speaker, "text": text, "turn_id": turn_id}

    @staticmethod
    def escalated(order_id: str, reason: str) -> dict:
        return {"type": "escalated", "order_id": order_id, "reason": reason}
