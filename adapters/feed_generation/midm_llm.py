from dataclasses import dataclass

from openai import AsyncOpenAI

from agents.feed_generation.exceptions import CaptionGenerationError


@dataclass
class MidmLLM:
    model: str
    base_url: str
    api_key: str = "EMPTY"
    temperature: float = 0.7

    async def generate(self, prompt: str) -> str:
        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            raise CaptionGenerationError(str(exc)) from exc
