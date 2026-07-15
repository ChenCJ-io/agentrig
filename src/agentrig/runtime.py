"""进程级运行时单例：共享 proxy 组件（mock hub / trace / backend registry）。

app / execution / sampling 通过 get_runtime() 拿同一组实例，避免各处自建。
测试用 reset_runtime() 注入自定义实例或清空隔离。get_runtime 用 double-checked
locking，线程安全（FastAPI sync endpoint 进线程池时无 TOCTOU 竞态）。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from .mock import ToolMockHub
from .proxy import BackendRegistry, TraceSink


@dataclass
class Runtime:
    """proxy 共享组件容器。"""

    hub: ToolMockHub
    trace: TraceSink
    registry: BackendRegistry


_runtime: Runtime | None = None
_lock = threading.Lock()


def get_runtime() -> Runtime:
    """懒建并返回进程级 Runtime 单例（double-checked locking，线程安全）。"""
    global _runtime
    if _runtime is None:
        with _lock:
            if _runtime is None:
                _runtime = Runtime(
                    hub=ToolMockHub(),
                    trace=TraceSink(),
                    registry=BackendRegistry(),
                )
    return _runtime


def reset_runtime(rt: Runtime | None = None) -> None:
    """重置单例：传 None 清空（下次 get_runtime 重建），传 rt 注入自定义实例。"""
    global _runtime
    with _lock:
        _runtime = rt
