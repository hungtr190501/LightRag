"""Adapter kết nối với vLLM server (OpenAI-compatible API).

vLLM expose OpenAI-compatible endpoint nên dùng openai async client.
Không phụ thuộc OpenAI cloud — chạy hoàn toàn local.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

VLLM_BASE_URL = os.getenv("LLM_BINDING_HOST", "http://localhost:8000/v1")
VLLM_API_KEY = os.getenv("LLM_BINDING_API_KEY", "not-needed")
VLLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=VLLM_BASE_URL, api_key=VLLM_API_KEY)
    return _client


async def vllm_complete(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    **kwargs,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = await _get_client().chat.completions.create(
        model=VLLM_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    return response.choices[0].message.content or ""


async def vllm_batch_complete(
    prompts: list[str],
    system_prompt: Optional[str] = None,
    max_tokens: int = 512,
    concurrency: int = 16,
    temperature: float = 0.1,
) -> list[str]:
    """Batch completion với semaphore để tận dụng vLLM continuous batching.

    Lỗi per-prompt (vd: context too long) trả về chuỗi rỗng thay vì crash toàn batch.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(p: str) -> str:
        async with semaphore:
            try:
                return await vllm_complete(p, system_prompt, max_tokens, temperature)
            except Exception as e:
                # Context length exceeded hoặc lỗi tạm thời — bỏ qua chunk này
                logger.warning("vllm_complete failed (skipping chunk): %s", e)
                return ""

    return await asyncio.gather(*[_one(p) for p in prompts])
