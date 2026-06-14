"""V3.0 统一可观测性：loguru + OpenTelemetry trace。

策略：
- 默认 loguru 接管所有 logging（已有）
- OTel 只在 ENABLE_OTEL=1 时启用（生产路径）
- 兼容 OTel collector / Jaeger / Datadog
"""
from __future__ import annotations
import os
import logging
import sys
import time
from typing import Optional

log = logging.getLogger("aiagent.observability")

OTEL_ENABLED = os.getenv("ENABLE_OTEL", "0") == "1"
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")


def init_logging(level: str = "INFO") -> None:
    """初始化日志。"""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
        format=fmt,
        force=True,
    )
    log.info(f"logging initialized level={level}")


def init_otel(service_name: str = "aiagent-comms") -> None:
    """初始化 OpenTelemetry（可选）。"""
    if not OTEL_ENABLED:
        log.info("OTel disabled (set ENABLE_OTEL=1 to enable)")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider = TracerProvider()
        exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        log.info(f"OTel enabled endpoint={OTEL_ENDPOINT} service={service_name}")
    except ImportError:
        log.warning("OTel libs not installed, skipping")


def traced(operation: str):
    """装饰器：简单 trace 计时。"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = int((time.time() - t0) * 1000)
                log.info(f"op={operation} elapsed={elapsed_ms}ms status=ok")
                return result
            except Exception as e:
                elapsed_ms = int((time.time() - t0) * 1000)
                log.error(f"op={operation} elapsed={elapsed_ms}ms status=err err={e}")
                raise
        return wrapper
    return decorator
