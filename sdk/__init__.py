"""V3.0 Python SDK · 供第三方调用。

用法：
```python
from sdk import AiagClient

client = AiagClient(base_url="http://localhost:8766", token="xxx")
order = client.create_order(
    organization="Hertz Honolulu",
    contact_number="+18084373000",
    requirement="I need an economy car 3 days",
    scenario="car_rental",
)
client.wait_for_completion(order["order_id"], timeout=120)
result = client.get_order(order["order_id"])
```
"""
from __future__ import annotations
import time
from typing import Optional, Literal
import httpx


class AiagError(Exception):
    """SDK 自定义异常。"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"[{status_code}] {message}")


class AiagClient:
    """V3.0 SDK 主类。"""

    def __init__(self, base_url: str = "http://localhost:8766", token: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, path: str, **kwargs):
        r = self._client.request(method, path, headers=self._headers(), **kwargs)
        if r.status_code >= 400:
            try:
                msg = r.json().get("detail", r.text)
            except Exception:
                msg = r.text
            raise AiagError(r.status_code, msg)
        return r.json() if r.text else {}

    def health(self) -> dict:
        return self._request("GET", "/api/health")

    def metrics(self) -> dict:
        return self._request("GET", "/api/metrics")

    def register(self, org_name: str, email: str, password: str, name: str) -> dict:
        r = self._request("POST", "/api/auth/register",
                          json={"org_name": org_name, "email": email, "password": password, "name": name})
        self.token = r["token"]
        return r

    def login(self, email: str, password: str) -> dict:
        r = self._request("POST", "/api/auth/login", json={"email": email, "password": password})
        self.token = r["token"]
        return r

    def me(self) -> dict:
        return self._request("GET", "/api/auth/me")

    def create_order(
        self,
        organization: str,
        contact_number: str,
        requirement: str,
        *,
        scenario: str = "hotel",
        constraints: Optional[str] = None,
        preferred_channel: Literal["voice", "sms"] = "sms",
        industry: Optional[str] = None,
    ) -> dict:
        """创建订单。

        industry: 可选 - 行业词库 V3.0（cable/machinery/textile/logistics），不指定时自动检测
        """
        payload = {
            "organization": organization,
            "contact_number": contact_number,
            "requirement": requirement,
            "scenario": scenario,
            "preferred_channel": preferred_channel,
        }
        if constraints:
            payload["constraints"] = constraints
        return self._request("POST", "/api/orders", json=payload)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/api/orders/{order_id}")

    def list_orders(self, limit: int = 20) -> list:
        return self._request("GET", f"/api/orders?limit={limit}")

    def wait_for_completion(self, order_id: str, timeout: float = 120.0, poll_interval: float = 1.0) -> dict:
        """轮询等订单完成。"""
        elapsed = 0.0
        while elapsed < timeout:
            order = self.get_order(order_id)
            if order["status"] in ("success", "failed", "needs_user"):
                return order
            time.sleep(poll_interval)
            elapsed += poll_interval
        raise AiagError(408, f"timeout waiting for {order_id} after {timeout}s")

    def evaluate(self, order_id: str) -> dict:
        """获取 V2.1 评估结果。"""
        order = self.get_order(order_id)
        ev = (order.get("result") or {}).get("evaluation")
        if not ev:
            raise AiagError(404, f"order {order_id} has no evaluation yet")
        return ev

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# === 异步版 SDK ===
class AiagAsyncClient:
    """异步 SDK（适合长跑/批处理）。"""

    def __init__(self, base_url: str = "http://localhost:8766", token: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(self, method: str, path: str, **kwargs):
        r = await self._client.request(method, path, headers=self._headers(), **kwargs)
        if r.status_code >= 400:
            try:
                msg = r.json().get("detail", r.text)
            except Exception:
                msg = r.text
            raise AiagError(r.status_code, msg)
        return r.json() if r.text else {}

    async def health(self) -> dict:
        return await self._request("GET", "/api/health")

    async def create_order(self, **kwargs) -> dict:
        return await self._request("POST", "/api/orders", json=kwargs)

    async def get_order(self, order_id: str) -> dict:
        return await self._request("GET", f"/api/orders/{order_id}")

    async def list_orders(self, limit: int = 20) -> list:
        return await self._request("GET", f"/api/orders?limit={limit}")

    async def aclose(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
