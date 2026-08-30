import json
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

    def test_contract_and_program_documents_exist(self):
        schema_path = ROOT / "contracts" / "cmr" / "module-manifest.schema.json"
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["title"], "CMR module manifest")
        for name in ("README.md", "ARCHITECTURE.md", "ROADMAP.md", "GIT_WORKFLOW.md", "SESSION_REGISTRY.md"):
            self.assertTrue((ROOT / "docs" / "cmr" / name).is_file())


if __name__ == "__main__":
    unittest.main()
