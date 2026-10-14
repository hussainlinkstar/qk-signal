from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

from report_schema import (  # noqa: E402
    AEO_EXPERT_SCHEMA,
    CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA,
    GEO_EXPERT_SCHEMA,
    SEO_EXPERT_SCHEMA,
    SYNTHESIZER_SCHEMA,
)
from services.ai_engine import AIFactory  # noqa: E402


async def _check_schema(
    factory: AIFactory,
    *,
    provider: str,
    model: str,
    schema_name: str,
    schema: dict,
) -> tuple[bool, str]:
    system_prompt = "Return valid JSON that matches the schema exactly."
    user_prompt = [f"Schema validation probe for {schema_name}. Return the smallest valid payload."]
    try:
        await factory._generate_with_provider(
            provider,
            model,
            system_prompt,
            user_prompt,
            schema=schema,
        )
    except Exception as exc:  # pragma: no cover - live validation helper
        return False, str(exc)
    return True, "ok"


async def main() -> int:
    factory = AIFactory()
    checks: list[tuple[str, str, str, dict]] = []

    anthropic_model = factory.get_model_instance("anthropic", "smart")
    openai_model = factory.get_model_instance("openai", "fast")

    if anthropic_model:
        checks.extend(
            [
                ("anthropic", anthropic_model[1], "SEO_EXPERT_SCHEMA", SEO_EXPERT_SCHEMA),
                ("anthropic", anthropic_model[1], "GEO_EXPERT_SCHEMA", GEO_EXPERT_SCHEMA),
                ("anthropic", anthropic_model[1], "AEO_EXPERT_SCHEMA", AEO_EXPERT_SCHEMA),
                (
                    "anthropic",
                    anthropic_model[1],
                    "CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA",
                    CANONICAL_AUDIT_ANALYSIS_JSON_SCHEMA,
                ),
            ]
        )

    if openai_model:
        checks.append(("openai", openai_model[1], "SYNTHESIZER_SCHEMA", SYNTHESIZER_SCHEMA))

    if not checks:
        print("No configured providers found. Nothing to validate.")
        return 0

    failures = 0
    for provider, model, schema_name, schema in checks:
        ok, detail = await _check_schema(
            factory,
            provider=provider,
            model=model,
            schema_name=schema_name,
            schema=schema,
        )
        status = "PASS" if ok else "FAIL"
        print(f"{status} {provider}/{model} {schema_name}: {detail}")
        if not ok:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - manual validation helper
    raise SystemExit(asyncio.run(main()))
