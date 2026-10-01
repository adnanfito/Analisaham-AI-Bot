"""
Groq Client
"""

from __future__ import annotations

from market_sentiment.core.config import GROQ_MODEL


# ---------------------------------------------------------------------------
# Groq Client
# ---------------------------------------------------------------------------


class GroqClient:
    def __init__(self, api_key: str) -> None:
        from groq import Groq

        self._client = Groq(api_key=api_key)

    def chat(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 2048
    ) -> str:
        resp = self._client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=GROQ_MODEL,
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
