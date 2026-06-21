from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMPort(Protocol):
    async def generate(self, prompt: str) -> str: ...


@dataclass
class Ports:
    llm: LLMPort
