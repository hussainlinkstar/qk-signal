from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Awaitable, Callable

from core.bedrock_text import bedrock_available, bedrock_generate_text

URL_PATTERN = re.compile(r"https?://[^\s\]\)>'\"}]+", re.IGNORECASE)

_GEO_SYSTEM_PROMPT = (
    "You are an AI search assistant. Answer the user's query factually and "
    "concisely, citing source URLs where relevant."
)


class GeoVisibilityService:
    def __init__(
        self,
        provider_callable: Callable[[str], Awaitable[str | dict[str, Any]]] | None = None,
    ) -> None:
        self.provider_callable = provider_callable
        # GEO visibility measurement runs on AWS Bedrock (single-vendor cutover).
        self.provider = os.getenv("GEO_LLM_PROVIDER", "bedrock").strip().lower()
        self.request_timeout = float(os.getenv("GEO_LLM_TIMEOUT_SECONDS", "30"))
        self.tier = os.getenv("GEO_LLM_TIER", "fast").strip().lower()

    async def _run_prompt(self, prompt: str) -> str | dict[str, Any]:
        if self.provider_callable:
            return await self.provider_callable(prompt)

        if self.provider != "bedrock":
            raise ValueError(
                f"Unsupported GEO LLM provider '{self.provider}'. Only 'bedrock' is supported."
            )
        if not bedrock_available():
            raise ValueError("AWS Bedrock is required for GEO visibility (no Bedrock client).")

        return await asyncio.to_thread(
            bedrock_generate_text,
            _GEO_SYSTEM_PROMPT,
            prompt,
            tier=self.tier,
            temperature=0,
            use_case="geo_visibility",
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.lower().split())

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        return URL_PATTERN.findall(text or "")

    def _response_to_parts(self, response: str | dict[str, Any]) -> tuple[str, list[str]]:
        if isinstance(response, str):
            text = response
            citations = self._extract_urls(response)
            return text, citations

        text = str(response.get("answer") or response.get("text") or response.get("content") or "")
        raw_citations = response.get("citations") or response.get("sources") or []
        citations = [str(citation) for citation in raw_citations if citation]
        if not citations:
            citations = self._extract_urls(text)
        return text, citations

    def _is_visible(
        self, brand_name: str, text: str, citations: list[str]
    ) -> tuple[bool, bool, bool]:
        brand = self._normalize_text(brand_name)
        normalized_text = self._normalize_text(text)
        brand_mentioned = bool(brand and brand in normalized_text)
        brand_cited = bool(
            brand and any(brand in self._normalize_text(citation) for citation in citations)
        )
        visible = brand_mentioned or brand_cited
        return visible, brand_mentioned, brand_cited

    async def compute_visibility_index(self, brand_name: str, prompts: list[str]) -> dict[str, Any]:
        normalized_brand = brand_name.strip()
        controlled_prompts = [prompt.strip() for prompt in prompts if prompt and prompt.strip()]

        if not normalized_brand:
            raise ValueError("brand_name is required")
        if not controlled_prompts:
            raise ValueError("At least one controlled prompt is required")

        results: list[dict[str, Any]] = []
        visible_count = 0

        for prompt in controlled_prompts:
            try:
                provider_response = await self._run_prompt(prompt)
                response_text, citations = self._response_to_parts(provider_response)
                visible, brand_mentioned, brand_cited = self._is_visible(
                    normalized_brand, response_text, citations
                )
                if visible:
                    visible_count += 1

                results.append(
                    {
                        "prompt": prompt,
                        "response_excerpt": response_text[:1000],
                        "citations": citations,
                        "brand_mentioned": brand_mentioned,
                        "brand_cited": brand_cited,
                        "visible": visible,
                        "status": "ok",
                        "error": None,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "prompt": prompt,
                        "response_excerpt": "",
                        "citations": [],
                        "brand_mentioned": False,
                        "brand_cited": False,
                        "visible": False,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        total_prompts = len(controlled_prompts)
        visibility_index = (visible_count / total_prompts) * 100 if total_prompts else 0.0

        return {
            "brand_name": normalized_brand,
            "total_prompts": total_prompts,
            "visible_prompts": visible_count,
            "visibility_index": round(visibility_index, 2),
            "results": results,
        }
