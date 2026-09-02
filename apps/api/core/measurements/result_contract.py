"""Validation and round-trip helpers for the canonical CMR result contract.

This module intentionally contains no clinical algorithms. It evaluates the
small JSON Schema subset used by ``contracts/cmr/result-envelope.schema.json``
with the Python standard library, then applies cross-reference rules that JSON
Schema cannot express cleanly (lineage and staleness checks).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPPORTED_CONTRACT_MAJOR = 1
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "additionalProperties",
    "required",
    "properties",
    "propertyNames",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "const",
    "enum",
    "pattern",
    "minLength",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "items",
}
CONTRACT_PATH = (
    Path(__file__).resolve().parents[4]
    / "contracts"
    / "cmr"
    / "result-envelope.schema.json"
)


class ContractValidationError(ValueError):
    """The payload does not satisfy the shared CMR result contract."""


class UnsupportedContractVersion(ContractValidationError):
    """The payload declares an incompatible contract major version."""


class StaleResultError(ContractValidationError):
    """A current upstream input no longer matches the recorded lineage."""


def load_contract_schema() -> dict[str, Any]:
    """Load the single normative result schema from the repository."""

    schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    _assert_supported_schema(schema)
    return schema


def _assert_supported_schema(schema: Mapping[str, Any], path: str = "$") -> None:
    unknown = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unknown:
        raise ContractValidationError(
            f"{path}: unsupported schema keywords {sorted(unknown)!r}"
        )
    for container_key in ("$defs", "properties"):
        for name, child in schema.get(container_key, {}).items():
            _assert_supported_schema(child, f"{path}.{container_key}.{name}")
    for list_key in ("allOf", "anyOf", "oneOf"):
        for index, child in enumerate(schema.get(list_key, [])):
            _assert_supported_schema(child, f"{path}.{list_key}[{index}]")
    for child_key in (
        "additionalProperties",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "items",
    ):
        child = schema.get(child_key)
        if isinstance(child, Mapping):
            _assert_supported_schema(child, f"{path}.{child_key}")


def compute_result_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash the result revision, excluding the digest and review decision.

    Review is excluded to avoid a recursive digest. Quality remains included,
    so changing a quality-bearing result invalidates an earlier review.
    """

    fingerprint_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"result_fingerprint", "review"}
    }
    canonical = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _error(path: str, message: str) -> None:
    raise ContractValidationError(f"{path}: {message}")


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ContractValidationError(f"unsupported non-local schema reference: {ref}")
    node: Any = root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or part not in node:
            raise ContractValidationError(f"unresolvable schema reference: {ref}")
        node = node[part]
    if not isinstance(node, Mapping):
        raise ContractValidationError(f"schema reference is not an object: {ref}")
    return node


def _matches(instance: Any, schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    try:
        _validate(instance, schema, root, "$")
    except ContractValidationError:
        return False
    return True


def _validate_type(instance: Any, expected: str, path: str) -> None:
    if expected == "object":
        valid = isinstance(instance, Mapping)
    elif expected == "array":
        valid = isinstance(instance, list)
    elif expected == "string":
        valid = isinstance(instance, str)
    elif expected == "integer":
        valid = isinstance(instance, int) and not isinstance(instance, bool)
    elif expected == "number":
        valid = (
            isinstance(instance, (int, float))
            and not isinstance(instance, bool)
            and math.isfinite(instance)
        )
    elif expected == "boolean":
        valid = isinstance(instance, bool)
    elif expected == "null":
        valid = instance is None
    else:
        raise ContractValidationError(f"unsupported schema type: {expected}")
    if not valid:
        _error(path, f"expected {expected}")


def _validate(
    instance: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> None:
    if "$ref" in schema:
        _validate(instance, _resolve_ref(root, schema["$ref"]), root, path)
        return

    if "allOf" in schema:
        for branch in schema["allOf"]:
            _validate(instance, branch, root, path)
    if "anyOf" in schema:
        if not any(_matches(instance, branch, root) for branch in schema["anyOf"]):
            _error(path, "does not match any allowed shape")
    if "oneOf" in schema:
        match_count = 0
        branch_errors = []
        for branch in schema["oneOf"]:
            try:
                _validate(instance, branch, root, path)
            except ContractValidationError as exc:
                branch_errors.append(str(exc))
            else:
                match_count += 1
        if match_count != 1:
            detail = "; ".join(branch_errors[:3])
            suffix = f"; branch failures: {detail}" if detail else ""
            _error(
                path,
                f"must match exactly one allowed shape (matched {match_count}){suffix}",
            )
    if "not" in schema and _matches(instance, schema["not"], root):
        _error(path, "matches a forbidden shape")
    if "if" in schema:
        branch = schema.get("then") if _matches(instance, schema["if"], root) else schema.get("else")
        if branch is not None:
            _validate(instance, branch, root, path)

    if "const" in schema and instance != schema["const"]:
        _error(path, f"must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        _error(path, f"must be one of {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, list):
            if not any(
                _matches(instance, {"type": item}, root) for item in expected_type
            ):
                _error(path, f"expected one of types {expected_type!r}")
        else:
            _validate_type(instance, expected_type, path)

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            _error(path, "string is shorter than minLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            _error(path, f"does not match pattern {pattern!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            _error(path, f"must be >= {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            _error(path, f"must be <= {schema['maximum']}")

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            _error(path, "array is shorter than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            _error(path, "array is longer than maxItems")
        if schema.get("uniqueItems"):
            normalized = [
                json.dumps(item, sort_keys=True, ensure_ascii=False) for item in instance
            ]
            if len(normalized) != len(set(normalized)):
                _error(path, "array items must be unique")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                _validate(item, item_schema, root, f"{path}[{index}]")

    if isinstance(instance, Mapping):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                _error(path, f"missing required property {key!r}")

        properties = schema.get("properties", {})
        property_names = schema.get("propertyNames")
        if property_names is not None:
            for key in instance:
                _validate(key, property_names, root, f"{path}.<property-name>")

        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child_path = f"{path}.{key}"
            if key in properties:
                _validate(value, properties[key], root, child_path)
            elif additional is False:
                _error(child_path, "additional property is not allowed")
            elif isinstance(additional, Mapping):
                _validate(value, additional, root, child_path)


def _lineage_map(items: Sequence[Mapping[str, Any]], path: str) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for index, item in enumerate(items):
        key = (str(item["kind"]), str(item["ref"]))
        if key in result:
            _error(f"{path}[{index}]", f"duplicate lineage identity {key!r}")
        result[key] = str(item["version"])
    return result


def _validate_coordinate_frame(frame: Mapping[str, Any], path: str) -> None:
    expected = {
        "pixel_index_2d": (["column", "row"], "px"),
        "image_physical_2d": (["x", "y"], "mm"),
        "patient_lps_3d": (["left", "posterior", "superior"], "mm"),
    }
    axes, unit = expected[str(frame["frame"])]
    if frame["axis_order"] != axes:
        _error(path, f"axis_order for {frame['frame']} must be {axes!r}")
    if frame["length_unit"] != unit:
        _error(path, f"length_unit for {frame['frame']} must be {unit!r}")


def _validate_semantics(payload: Mapping[str, Any]) -> None:
    series_versions: dict[str, str] = {}
    for index, source in enumerate(payload["sources"]["series"]):
        ref = source["series_ref"]
        if ref in series_versions:
            _error(f"$.sources.series[{index}]", f"duplicate series_ref {ref!r}")
        series_versions[ref] = source["series_version"]

    for index, selector in enumerate(payload["sources"]["selectors"]):
        if selector["series_ref"] not in series_versions:
            _error(
                f"$.sources.selectors[{index}].series_ref",
                "selector references an undeclared source series",
            )
        for dimension in ("slices", "phases"):
            selected = selector[dimension]
            if selected["mode"] == "range" and selected["start"] > selected["end"]:
                _error(
                    f"$.sources.selectors[{index}].{dimension}",
                    "range start must not exceed end",
                )

    geometry_versions: dict[str, str] = {}
    if payload["geometry_context"]["usage"] == "referenced":
        for index, geometry in enumerate(payload["geometry_context"]["geometry_refs"]):
            ref = geometry["geometry_ref"]
            if ref in geometry_versions:
                _error(
                    f"$.geometry_context.geometry_refs[{index}]",
                    f"duplicate geometry_ref {ref!r}",
                )
            geometry_versions[ref] = geometry["geometry_version"]
            _validate_coordinate_frame(
                geometry["coordinate_frame"],
                f"$.geometry_context.geometry_refs[{index}].coordinate_frame",
            )

    roi_versions: dict[str, str] = {}
    if payload["roi_context"]["usage"] == "referenced":
        if payload["geometry_context"]["usage"] != "referenced":
            _error(
                "$.geometry_context",
                "ROI references require an explicit referenced geometry context",
            )
        for index, roi in enumerate(payload["roi_context"]["roi_refs"]):
            ref = roi["roi_ref"]
            if ref in roi_versions:
                _error(
                    f"$.roi_context.roi_refs[{index}]", f"duplicate roi_ref {ref!r}"
                )
            roi_versions[ref] = roi["roi_version"]
            if roi["geometry_ref"] not in geometry_versions:
                _error(
                    f"$.roi_context.roi_refs[{index}].geometry_ref",
                    "ROI references an undeclared geometry",
                )

    lineage = _lineage_map(payload["provenance"]["lineage"], "$.provenance.lineage")
    expected: dict[tuple[str, str], str] = {}
    expected.update({("series", ref): version for ref, version in series_versions.items()})
    expected.update({("roi", ref): version for ref, version in roi_versions.items()})
    expected.update(
        {("geometry", ref): version for ref, version in geometry_versions.items()}
    )
    algorithm = payload["provenance"]["algorithm"]
    expected[("algorithm", algorithm["algorithm_id"])] = algorithm["algorithm_version"]
    if "parameters_manifest_ref" in algorithm:
        expected[("parameters_manifest", algorithm["parameters_manifest_ref"])] = algorithm[
            "parameters_manifest_version"
        ]

    for key, version in expected.items():
        if lineage.get(key) != version:
            _error(
                "$.provenance.lineage",
                f"missing or mismatched lineage for {key[0]} {key[1]!r}",
            )

    quality = payload["quality"]
    if quality["assessment_status"] == "completed":
        flags = quality["flags"]
        disposition = quality["overall_disposition"]
        blocking = any(flag["blocks"] for flag in flags)
        concerning = any(flag["severity"] in {"warning", "error"} for flag in flags)
        if disposition == "pass" and (blocking or concerning):
            _error("$.quality", "pass cannot contain warning/error or blocking flags")
        if disposition == "warn" and (not flags or blocking):
            _error("$.quality", "warn requires non-blocking quality flags")
        if disposition == "fail" and not (
            blocking or any(flag["severity"] == "error" for flag in flags)
        ):
            _error("$.quality", "fail requires an error or blocking flag")

    expected_fingerprint = compute_result_fingerprint(payload)
    if payload["result_fingerprint"] != expected_fingerprint:
        _error(
            "$.result_fingerprint",
            "does not match the canonical result revision",
        )

    review = payload["review"]
    if "reviewed_result_fingerprint" in review:
        if review["reviewed_result_fingerprint"] != payload["result_fingerprint"]:
            _error(
                "$.review.reviewed_result_fingerprint",
                "review applies to a different result revision",
            )


def parse_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached, JSON-safe result mapping.

    Unknown incompatible major versions fail before field validation. Minor and
    patch versions within major 1 are compatible only through the stable root
    shape and namespaced extension object defined by the schema.
    """

    if not isinstance(payload, Mapping):
        raise ContractValidationError("$: expected object")
    try:
        detached = json.loads(
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"$: payload is not finite JSON: {exc}") from exc

    version = detached.get("contract_version")
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", str(version or ""))
    if match is None:
        raise ContractValidationError("$.contract_version: expected semantic version")
    if int(match.group(1)) != SUPPORTED_CONTRACT_MAJOR:
        raise UnsupportedContractVersion(
            f"$.contract_version: unsupported major {match.group(1)}"
        )

    schema = load_contract_schema()
    _validate(detached, schema, schema, "$")
    _validate_semantics(detached)
    return detached


def serialize_result(payload: Mapping[str, Any]) -> str:
    """Validate and serialize without implicit conversions or information loss."""

    parsed = parse_result(payload)
    serialized = json.dumps(
        parsed,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if parse_result(json.loads(serialized)) != parsed:
        raise ContractValidationError("$: result changed during round-trip")
    return serialized


def validate_result_against_current_inputs(
    payload: Mapping[str, Any],
    current_inputs: Sequence[Mapping[str, str]],
) -> None:
    """Fail when a recorded upstream input is missing or has a new version.

    Callers obtain ``current_inputs`` from their own repositories. This shared
    layer compares opaque identities and versions only; it does not read DICOM,
    contours, databases or artifact contents.
    """

    parsed = parse_result(payload)
    current = _lineage_map(current_inputs, "$.current_inputs")
    recorded = _lineage_map(parsed["provenance"]["lineage"], "$.provenance.lineage")
    stale = [
        (kind, ref, version, current.get((kind, ref)))
        for (kind, ref), version in recorded.items()
        if current.get((kind, ref)) != version
    ]
    if stale:
        kind, ref, recorded_version, current_version = stale[0]
        raise StaleResultError(
            f"stale {kind} {ref!r}: recorded={recorded_version!r}, "
            f"current={current_version!r}"
        )
