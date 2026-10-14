"""
Runtime patches for upstream FastAPI compatibility issues.

FastAPI 0.121.1 + Pydantic v2 crashes while generating OpenAPI when a schema
definition lacks a ``"$ref"`` key. The upstream project fixed this in
FastAPI 0.123.1 (see release notes: "Avoid accessing non-existing `$ref` key
for Pydantic v2 compat remapping"). We mirror that fix here so we don't have
to bump the framework version immediately.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from fastapi._compat import v2 as fastapi_v2
from fastapi.types import ModelNameMap
from typing_extensions import Literal

JsonSchemaValue = fastapi_v2.JsonSchemaValue
ModelField = fastapi_v2.ModelField


def patch_openapi_ref_handling() -> None:
    """
    Backport FastAPI's `$ref` guard for OpenAPI generation.

    Without this, ``/openapi.json`` raises ``KeyError: '$ref'`` whenever a
    schema entry doesn't include a reference key. That breaks the Swagger UI
    and all client generation flows.
    """

    def _safe_remap_definitions_and_field_mappings(
        *,
        model_name_map: ModelNameMap,
        definitions: Dict[str, Any],
        field_mapping: Dict[
            Tuple[ModelField, Literal["validation", "serialization"]], JsonSchemaValue
        ],
    ) -> Tuple[
        Dict[Tuple[ModelField, Literal["validation", "serialization"]], JsonSchemaValue],
        Dict[str, Any],
    ]:
        old_name_to_new_name_map: Dict[str, str] = {}
        for field_key, schema in field_mapping.items():
            model = field_key[0].type_
            # Guard that was added upstream in 0.123.1
            if model not in model_name_map or "$ref" not in schema:
                continue
            new_name = model_name_map[model]
            old_name = schema["$ref"].split("/")[-1]
            if old_name in {f"{new_name}-Input", f"{new_name}-Output"}:
                continue
            old_name_to_new_name_map[old_name] = new_name

        new_field_mapping: Dict[
            Tuple[ModelField, Literal["validation", "serialization"]],
            JsonSchemaValue,
        ] = {}
        for field_key, schema in field_mapping.items():
            new_schema = fastapi_v2._replace_refs(
                schema=schema,
                old_name_to_new_name_map=old_name_to_new_name_map,
            )
            new_field_mapping[field_key] = new_schema

        new_definitions: Dict[str, Any] = {}
        for key, value in definitions.items():
            new_key = old_name_to_new_name_map.get(key, key)
            new_value = fastapi_v2._replace_refs(
                schema=value,
                old_name_to_new_name_map=old_name_to_new_name_map,
            )
            new_definitions[new_key] = new_value

        return new_field_mapping, new_definitions

    fastapi_v2._remap_definitions_and_field_mappings = _safe_remap_definitions_and_field_mappings
