import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

from apps.api.core.measurements import (
    ContractValidationError,
    StaleResultError,
    compute_result_fingerprint,
    parse_result,
    serialize_result,
    validate_result_against_current_inputs,
)
from apps.api.core.measurements.result_contract import UnsupportedContractVersion
from apps.api.core.measurements.result_contract import load_contract_schema


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "cmr" / "fixtures"
GENERATOR = ROOT / "scripts" / "cmr" / "generate_result_types.py"
GENERATED_TYPES = ROOT / "apps" / "web" / "src" / "shared" / "cmr-result.generated.ts"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CmrResultContractTest(unittest.TestCase):
    def setUp(self):
        self.scalar = load_fixture("result-scalar.valid.json")

    def assert_invalid(self, payload, message_fragment=None):
        with self.assertRaises(ContractValidationError) as caught:
            parse_result(payload)
        if message_fragment:
            self.assertIn(message_fragment, str(caught.exception))

    def test_valid_synthetic_fixtures_round_trip_without_loss(self):
        for name in (
            "result-scalar.valid.json",
            "result-dimensionless.valid.json",
            "result-artifact.valid.json",
        ):
            with self.subTest(name=name):
                payload = load_fixture(name)
                parsed = parse_result(payload)
                self.assertEqual(json.loads(serialize_result(parsed)), payload)

    def test_aggregate_selectors_survive_round_trip(self):
        payload = load_fixture("result-artifact.valid.json")
        parsed = json.loads(serialize_result(payload))
        self.assertEqual(parsed["sources"]["selectors"], payload["sources"]["selectors"])
        self.assertEqual(len(parsed["sources"]["series"]), 2)

    def test_dimensionless_uses_ucum_one_not_empty_unit(self):
        payload = load_fixture("result-dimensionless.valid.json")
        self.assertEqual(parse_result(payload)["value"]["unit"], {"system": "UCUM", "code": "1"})
        payload["value"]["unit"]["code"] = ""
        self.assert_invalid(payload, "minLength")

    def test_missing_unit_is_rejected(self):
        del self.scalar["value"]["unit"]
        self.assert_invalid(self.scalar, "unit")

    def test_missing_source_series_is_rejected(self):
        del self.scalar["sources"]["series"]
        self.assert_invalid(self.scalar, "series")

    def test_geometry_without_coordinate_frame_is_rejected(self):
        geometry = self.scalar["geometry_context"]["geometry_refs"][0]
        geometry["coordinates"] = [[1.0, 2.0], [3.0, 4.0]]
        del geometry["coordinate_frame"]
        self.assert_invalid(self.scalar, "coordinate_frame")

    def test_coordinate_axes_and_units_are_not_implicit(self):
        frame = self.scalar["geometry_context"]["geometry_refs"][0]["coordinate_frame"]
        frame["axis_order"] = ["row", "column"]
        self.assert_invalid(self.scalar, "axis_order")

    def test_missing_algorithm_version_is_rejected(self):
        del self.scalar["provenance"]["algorithm"]["algorithm_version"]
        self.assert_invalid(self.scalar, "algorithm_version")

    def test_invalid_quality_severity_is_rejected(self):
        self.scalar["quality"] = {
            "assessment_status": "completed",
            "overall_disposition": "warn",
            "flags": [
                {
                    "code": "cine.synthetic_issue",
                    "severity": "critical",
                    "scope": "result",
                    "blocks": [],
                }
            ],
        }
        self.assert_invalid(self.scalar, "allowed shape")

    def test_missing_human_review_is_rejected(self):
        del self.scalar["review"]
        self.assert_invalid(self.scalar, "review")

    def test_unknown_major_version_fails_closed(self):
        self.scalar["contract_version"] = "2.0.0"
        with self.assertRaises(UnsupportedContractVersion):
            parse_result(self.scalar)

    def test_same_major_extension_version_is_accepted(self):
        self.scalar["contract_version"] = "1.9.0"
        self.scalar.setdefault("extensions", {})["cine_function.future"] = {"opaque": 1}
        self.scalar["result_fingerprint"] = compute_result_fingerprint(self.scalar)
        parse_result(self.scalar)

    def test_unavailable_state_cannot_hide_null_value(self):
        self.scalar["value"] = {
            "state": "not_applicable",
            "unit": {"system": "UCUM", "code": "%"},
            "reason_code": "metric.not_applicable",
            "scalar": None,
        }
        self.assert_invalid(self.scalar, "allowed shape")

    def test_roi_change_marks_old_result_stale(self):
        current = copy.deepcopy(self.scalar["provenance"]["lineage"])
        validate_result_against_current_inputs(self.scalar, current)
        for item in current:
            if item["kind"] == "roi":
                item["version"] = "contours-v4"
        with self.assertRaises(StaleResultError):
            validate_result_against_current_inputs(self.scalar, current)

    def test_algorithm_version_change_marks_old_result_stale(self):
        current = copy.deepcopy(self.scalar["provenance"]["lineage"])
        for item in current:
            if item["kind"] == "algorithm":
                item["version"] = "1.3.0"
        with self.assertRaises(StaleResultError):
            validate_result_against_current_inputs(self.scalar, current)

    def test_human_edit_invalidates_previous_review(self):
        fingerprint = self.scalar["result_fingerprint"]
        self.scalar["review"] = {
            "status": "reviewed",
            "revision": 1,
            "reviewed_result_fingerprint": fingerprint,
            "review_event_ref": "syn-review-event-001",
        }
        parse_result(self.scalar)
        self.scalar["metric"]["display_name"] = "Edited synthetic result"
        self.assert_invalid(self.scalar, "canonical result revision")
        self.scalar["result_fingerprint"] = compute_result_fingerprint(self.scalar)
        self.assert_invalid(self.scalar, "different result revision")

    def test_quality_does_not_upgrade_human_review(self):
        parsed = parse_result(self.scalar)
        self.assertEqual(parsed["quality"]["overall_disposition"], "pass")
        self.assertEqual(parsed["review"]["status"], "not_reviewed")

    def test_module_extensions_require_namespace(self):
        self.scalar["extensions"] = {"private_payload": {"value": 1}}
        self.assert_invalid(self.scalar, "pattern")

    def test_frontend_types_are_generated_from_current_schema(self):
        subprocess.run(
            ["python3", str(GENERATOR), "--check"],
            cwd=ROOT,
            check=True,
        )

        spec = importlib.util.spec_from_file_location("cmr_type_generator", GENERATOR)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        expected = module.render_types(
            (ROOT / "contracts" / "cmr" / "result-envelope.schema.json").read_bytes()
        )
        self.assertEqual(GENERATED_TYPES.read_text(encoding="utf-8"), expected)
        self.assertIn("flags: [];", expected)
        self.assertNotEqual(GENERATED_TYPES.read_text(encoding="utf-8") + "// drift\n", expected)

    def test_backend_recognizes_every_schema_keyword(self):
        schema = load_contract_schema()
        schema["unsupportedFutureKeyword"] = True
        from apps.api.core.measurements import result_contract

        with self.assertRaises(ContractValidationError):
            result_contract._assert_supported_schema(schema)


if __name__ == "__main__":
    unittest.main()
