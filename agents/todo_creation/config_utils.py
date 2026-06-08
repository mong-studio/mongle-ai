from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig


def get_ports(config: RunnableConfig) -> Any:
    configurable = config.get("configurable") or {}
    ports = configurable.get("ports")
    if ports is None:
        raise KeyError("RunnableConfig.configurable.ports is required")
    return ports
