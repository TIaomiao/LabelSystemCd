import json
import re
import unittest
from pathlib import Path

from apps.api.modules import MODULE_STATUSES


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_STATES = {
    "planned",
    "demo_only",
    "technically_verified",
    "doctor_reviewed",
    "accepted",
}


class CmrModuleLayoutTest(unittest.TestCase):
    def test_registered_modules_have_packages_and_allowed_states(self):
        for module_id, state in MODULE_STATUSES.items():
            self.assertIn(state, ALLOWED_STATES)
            self.assertTrue((ROOT / "apps" / "api" / "modules" / module_id / "__init__.py").is_file())

    def test_module_manifests_match_registry_and_schema(self):
        schema_path = ROOT / "contracts" / "cmr" / "module-manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["title"], "CMR module manifest")
        self.assertEqual(set(schema["properties"]["module_id"]["enum"]), set(MODULE_STATUSES))
        self.assertEqual(set(schema["properties"]["delivery_state"]["enum"]), ALLOWED_STATES)

        required = set(schema["required"])
        allowed_keys = set(schema["properties"])
        version_pattern = re.compile(schema["properties"]["contract_version"]["pattern"])

        for module_id, state in MODULE_STATUSES.items():
            manifest_path = ROOT / "apps" / "api" / "modules" / module_id / "module-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(required.issubset(manifest), manifest_path)
            self.assertTrue(set(manifest).issubset(allowed_keys), manifest_path)
            self.assertEqual(manifest["module_id"], module_id)
            self.assertEqual(manifest["delivery_state"], state)
            self.assertRegex(manifest["contract_version"], version_pattern)

    def test_contract_and_program_documents_exist(self):
        for name in (
            "README.md",
            "ARCHITECTURE.md",
            "ROADMAP.md",
            "GIT_WORKFLOW.md",
            "SESSION_REGISTRY.md",
            "HANDOFF_CONTRACT.md",
            "CLOUD_PROJECT_INSTRUCTIONS.md",
        ):
            self.assertTrue((ROOT / "docs" / "cmr" / name).is_file())
        self.assertTrue((ROOT / "docs" / "cmr" / "plans" / "README.md").is_file())
        self.assertTrue((ROOT / ".github" / "workflows" / "cmr-governance-ci.yml").is_file())
        self.assertTrue((ROOT / ".github" / "ISSUE_TEMPLATE" / "cmr_feature_plan.md").is_file())


if __name__ == "__main__":
    unittest.main()
