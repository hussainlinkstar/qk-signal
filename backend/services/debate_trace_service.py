from __future__ import annotations

import json
from typing import Any

import models
from sqlalchemy.orm import Session


_PIPELINE_LAYER_CONFIG: dict[str, dict[int, tuple[str, bool]]] = {
    "fast_3step": {
        1: ("Generation", False),
        2: ("Critique", False),
        3: ("Synthesis", False),
    },
    "smart_5step": {
        1: ("Specialized Generation", True),
        2: ("Centralized Critique", False),
        3: ("Synthesis", False),
        4: ("Magistrate Review", False),
    },
    "delta_flow": {
        1: ("Specialized Generation", True),
        2: ("Domain Critique", True),
        3: ("Consolidation", False),
        4: ("Global Magistrate", False),
    },
    "legacy_3step": {
        1: ("Generation", False),
        2: ("Critique", False),
        3: ("Synthesis", False),
    },
    "legacy_high_confidence": {
        1: ("Generation", False),
        2: ("Critique", False),
        3: ("Judgment", False),
    },
}


def _load_json_text(value: str | None) -> Any:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _coerce_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if limit is None or len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _trace_claim_count(trace: models.DebateTrace) -> int:
    packet = trace.output_claim_ledger if isinstance(trace.output_claim_ledger, dict) else {}
    for key in ("claim_ledger", "challenge_ledger", "consolidated_claim_disposition"):
        value = packet.get(key)
        if isinstance(value, list):
            return len(value)

    judge_summary = packet.get("judge_summary")
    if isinstance(judge_summary, dict):
        return sum(int(judge_summary.get(key) or 0) for key in judge_summary)
    return 0


def _trace_preview(trace: models.DebateTrace) -> str:
    packet = trace.output_claim_ledger if isinstance(trace.output_claim_ledger, dict) else {}
    parsed_output = _load_json_text(trace.output_raw)

    if isinstance(parsed_output, dict):
        for key in ("summary", "synthesis_reasoning", "counter_argument"):
            candidate = _coerce_text(parsed_output.get(key), limit=160)
            if candidate:
                return candidate

    claim_ledger = packet.get("claim_ledger")
    if isinstance(claim_ledger, list):
        for item in claim_ledger:
            if isinstance(item, dict):
                candidate = _coerce_text(item.get("claim_text"), limit=160)
                if candidate:
                    return candidate

    challenge_ledger = packet.get("challenge_ledger")
    if isinstance(challenge_ledger, list):
        for item in challenge_ledger:
            if isinstance(item, dict):
                candidate = _coerce_text(
                    item.get("counter_argument") or item.get("target_claim"), limit=160
                )
                if candidate:
                    return candidate

    dispositions = packet.get("consolidated_claim_disposition")
    if isinstance(dispositions, list):
        for item in dispositions:
            if isinstance(item, dict):
                candidate = _coerce_text(
                    item.get("critique_reference") or item.get("claim_id"), limit=160
                )
                if candidate:
                    return candidate

    if isinstance(parsed_output, str):
        return _coerce_text(parsed_output, limit=160)
    return ""


def _match_claim_text(
    trace: models.DebateTrace, claim_id: str, claim_text: str
) -> dict[str, Any] | None:
    packet = trace.output_claim_ledger if isinstance(trace.output_claim_ledger, dict) else {}

    claim_ledger = packet.get("claim_ledger")
    if isinstance(claim_ledger, list):
        for item in claim_ledger:
            if not isinstance(item, dict):
                continue
            if str(item.get("claim_id") or "").strip() == claim_id:
                return {"source": "claim_ledger", "item": item}

    challenges = packet.get("challenge_ledger")
    if isinstance(challenges, list) and claim_text:
        for item in challenges:
            if not isinstance(item, dict):
                continue
            if _coerce_text(item.get("target_claim")) == claim_text:
                return {"source": "challenge_ledger", "item": item}

    dispositions = packet.get("consolidated_claim_disposition")
    if isinstance(dispositions, list):
        for item in dispositions:
            if not isinstance(item, dict):
                continue
            if str(item.get("claim_id") or "").strip() == claim_id:
                return {"source": "consolidated_claim_disposition", "item": item}

    input_payload = _load_json_text(trace.input_payload_raw)
    if claim_id and isinstance(input_payload, dict):
        joined_prompt = json.dumps(input_payload, ensure_ascii=True, default=str)
        if claim_id in joined_prompt:
            return {"source": "input_payload", "item": {}}

    return None


def _layer_descriptor(pipeline_type: str, layer: int) -> tuple[str, bool]:
    config = _PIPELINE_LAYER_CONFIG.get(pipeline_type) or _PIPELINE_LAYER_CONFIG["legacy_3step"]
    return config.get(layer, (f"Layer {layer}", False))


class DebateTraceService:
    def persist_trace_records(
        self,
        *,
        db: Session,
        audit: models.Audit,
        trace_records: list[dict[str, Any]] | None,
    ) -> int:
        if audit is None or not trace_records:
            return 0

        db.query(models.DebateTrace).filter(models.DebateTrace.audit_id == audit.id).delete(
            synchronize_session=False
        )

        inserted = 0
        for item in trace_records:
            if not isinstance(item, dict):
                continue
            db.add(
                models.DebateTrace(
                    audit_id=audit.id,
                    agent_role=_coerce_text(item.get("agent_role"), limit=64) or "unknown",
                    agent_layer=max(0, int(item.get("agent_layer") or 0)),
                    pipeline_type=_coerce_text(item.get("pipeline_type"), limit=32)
                    or "legacy_3step",
                    provider=_coerce_text(item.get("provider"), limit=32) or "unknown",
                    model=_coerce_text(item.get("model"), limit=128),
                    input_payload_hash=_coerce_text(item.get("input_payload_hash"), limit=64),
                    input_payload_chars=max(0, int(item.get("input_payload_chars") or 0)),
                    input_summary=_coerce_text(item.get("input_summary"), limit=500) or None,
                    input_payload_raw=_coerce_text(item.get("input_payload_raw")),
                    output_raw=_coerce_text(item.get("output_raw")) or "{}",
                    output_claim_ledger=(
                        item.get("output_claim_ledger")
                        if isinstance(item.get("output_claim_ledger"), dict)
                        else None
                    ),
                    latency_ms=max(0, int(item.get("latency_ms") or 0)),
                    cost_usd=float(item["cost_usd"]) if item.get("cost_usd") is not None else None,
                    prompt_tokens=int(item["prompt_tokens"])
                    if item.get("prompt_tokens") is not None
                    else None,
                    completion_tokens=(
                        int(item["completion_tokens"])
                        if item.get("completion_tokens") is not None
                        else None
                    ),
                    status=_coerce_text(item.get("status"), limit=16) or "completed",
                    error_message=_coerce_text(item.get("error_message")) or None,
                )
            )
            inserted += 1
        return inserted

    def get_timeline(
        self,
        *,
        db: Session,
        audit: models.Audit,
    ) -> dict[str, Any]:
        traces = (
            db.query(models.DebateTrace)
            .filter(models.DebateTrace.audit_id == audit.id)
            .order_by(
                models.DebateTrace.agent_layer.asc(),
                models.DebateTrace.created_at.asc(),
                models.DebateTrace.id.asc(),
            )
            .all()
        )

        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
        debate = metadata.get("debate") if isinstance(metadata.get("debate"), dict) else {}
        pipeline_type = (
            traces[0].pipeline_type
            if traces
            else _coerce_text(debate.get("pipeline_type"), limit=32) or "legacy_3step"
        )

        layers: dict[int, dict[str, Any]] = {}
        for trace in traces:
            layer_number = int(trace.agent_layer or 0)
            layer_name, parallel = _layer_descriptor(trace.pipeline_type, layer_number)
            layer_payload = layers.setdefault(
                layer_number,
                {
                    "layer": layer_number,
                    "name": layer_name,
                    "parallel": parallel,
                    "traces": [],
                },
            )
            layer_payload["traces"].append(
                {
                    "agent_role": trace.agent_role,
                    "provider": trace.provider,
                    "model": trace.model,
                    "status": trace.status,
                    "latency_ms": int(trace.latency_ms or 0),
                    "cost_usd": float(trace.cost_usd or 0.0)
                    if trace.cost_usd is not None
                    else None,
                    "input_chars": int(trace.input_payload_chars or 0),
                    "output_preview": _trace_preview(trace),
                    "claim_count": _trace_claim_count(trace),
                    "prompt_tokens": int(trace.prompt_tokens or 0)
                    if trace.prompt_tokens is not None
                    else None,
                    "completion_tokens": int(trace.completion_tokens or 0)
                    if trace.completion_tokens is not None
                    else None,
                    "error_message": trace.error_message,
                }
            )

        return {
            "audit_id": audit.id,
            "pipeline_type": pipeline_type,
            "total_agents": len(traces),
            "total_latency_ms": sum(int(trace.latency_ms or 0) for trace in traces),
            "total_cost_usd": round(
                sum(float(trace.cost_usd or 0.0) for trace in traces if trace.cost_usd is not None),
                6,
            ),
            "layers": [layers[key] for key in sorted(layers)],
        }

    def get_agent_output(
        self,
        *,
        db: Session,
        audit_id: int,
        role: str,
    ) -> dict[str, Any] | None:
        trace = (
            db.query(models.DebateTrace)
            .filter(
                models.DebateTrace.audit_id == audit_id,
                models.DebateTrace.agent_role == role,
            )
            .order_by(models.DebateTrace.created_at.desc(), models.DebateTrace.id.desc())
            .first()
        )
        if trace is None:
            return None

        return {
            "audit_id": audit_id,
            "agent_role": trace.agent_role,
            "agent_layer": int(trace.agent_layer or 0),
            "pipeline_type": trace.pipeline_type,
            "provider": trace.provider,
            "model": trace.model,
            "status": trace.status,
            "latency_ms": int(trace.latency_ms or 0),
            "cost_usd": float(trace.cost_usd or 0.0) if trace.cost_usd is not None else None,
            "prompt_tokens": int(trace.prompt_tokens or 0)
            if trace.prompt_tokens is not None
            else None,
            "completion_tokens": int(trace.completion_tokens or 0)
            if trace.completion_tokens is not None
            else None,
            "input_payload_hash": trace.input_payload_hash,
            "input_payload_chars": int(trace.input_payload_chars or 0),
            "input_summary": trace.input_summary,
            "input_payload": _load_json_text(trace.input_payload_raw),
            "output_raw": _load_json_text(trace.output_raw),
            "output_claim_ledger": trace.output_claim_ledger
            if isinstance(trace.output_claim_ledger, dict)
            else None,
            "error_message": trace.error_message,
            "created_at": trace.created_at.isoformat() if trace.created_at else None,
        }

    def get_claim_journey(
        self,
        *,
        db: Session,
        audit: models.Audit,
        claim_id: str,
    ) -> dict[str, Any]:
        traces = (
            db.query(models.DebateTrace)
            .filter(models.DebateTrace.audit_id == audit.id)
            .order_by(
                models.DebateTrace.agent_layer.asc(),
                models.DebateTrace.created_at.asc(),
                models.DebateTrace.id.asc(),
            )
            .all()
        )

        claim_text = ""
        claim_domain = None
        for trace in traces:
            packet = (
                trace.output_claim_ledger if isinstance(trace.output_claim_ledger, dict) else {}
            )
            claim_ledger = packet.get("claim_ledger")
            if not isinstance(claim_ledger, list):
                continue
            for item in claim_ledger:
                if not isinstance(item, dict):
                    continue
                if str(item.get("claim_id") or "").strip() == claim_id:
                    claim_text = _coerce_text(item.get("claim_text"))
                    claim_domain = _coerce_text(item.get("domain"), limit=16) or None
                    break
            if claim_text:
                break

        journey: list[dict[str, Any]] = []
        for trace in traces:
            match = _match_claim_text(trace, claim_id, claim_text)
            if not match:
                continue

            source = match["source"]
            item = match["item"]
            entry: dict[str, Any] = {
                "layer": int(trace.agent_layer or 0),
                "agent": trace.agent_role,
                "provider": trace.provider,
                "model": trace.model,
                "status": trace.status,
            }
            if source == "claim_ledger":
                entry["action"] = (
                    "generated"
                    if "generator" in trace.agent_role or trace.agent_role == "proposer"
                    else "retained"
                )
                if isinstance(item, dict):
                    confidence = item.get("confidence")
                    if isinstance(confidence, (int, float)):
                        entry["confidence"] = float(confidence)
                    recommendation = _coerce_text(item.get("recommended_action"), limit=200)
                    if recommendation:
                        entry["recommended_action"] = recommendation
            elif source == "challenge_ledger":
                entry["action"] = "challenged"
                if isinstance(item, dict):
                    critique = _coerce_text(item.get("counter_argument"), limit=240)
                    if critique:
                        entry["critique"] = critique
                    severity = _coerce_text(item.get("severity"), limit=16)
                    if severity:
                        entry["severity"] = severity
                    suggested = _coerce_text(item.get("suggested_disposition"), limit=32)
                    if suggested:
                        entry["suggested_disposition"] = suggested
            elif source == "consolidated_claim_disposition":
                entry["action"] = "consolidated"
                if isinstance(item, dict):
                    disposition = _coerce_text(item.get("disposition"), limit=32)
                    if disposition:
                        entry["disposition"] = disposition
                    critique_reference = _coerce_text(item.get("critique_reference"), limit=200)
                    if critique_reference:
                        entry["critique_reference"] = critique_reference
                    post_critique_confidence = item.get("post_critique_confidence")
                    if isinstance(post_critique_confidence, (int, float)):
                        entry["new_confidence"] = float(post_critique_confidence)
            else:
                entry["action"] = "reviewed"

            journey.append(entry)

        return {
            "audit_id": audit.id,
            "claim_id": claim_id,
            "claim_text": claim_text or None,
            "claim_domain": claim_domain,
            "journey": journey,
        }


debate_trace_service = DebateTraceService()
