from dataclasses import dataclass, field

from openai import AsyncOpenAI

from agents.feed_generation.exceptions import CaptionGenerationError


@dataclass
class MidmLLM:
    model: str
    base_url: str
    api_key: str = "EMPTY"
    temperature: float = 0.7
    _client: AsyncOpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            content = response.choices[0].message.content
            if not content:
                raise CaptionGenerationError("Mi:dm 응답에 content가 없습니다")
            return content.strip()
        except CaptionGenerationError:
            raise
        except Exception as exc:
            raise CaptionGenerationError(str(exc)) from exc
