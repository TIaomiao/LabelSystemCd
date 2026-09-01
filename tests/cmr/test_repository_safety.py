import re
import subprocess
import unittest
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_FILES = (
    "AGENTS.md",
    ".github/copilot-instructions.md",
    ".github/pull_request_template.md",
)
CMR_SCOPES = (
    *GOVERNANCE_FILES,
    ".github/ISSUE_TEMPLATE",
    ".github/workflows/cmr-governance-ci.yml",
    "apps/api/core",
    "apps/api/modules",
    "apps/web/src/features",
    "contracts/cmr",
    "docs/cmr",
    "scripts/cmr",
    "tests/cmr",
)
DISALLOWED_NAMES = {".env", "secret_key", "id_rsa", "id_ed25519"}
DISALLOWED_SUFFIXES = (
    ".dcm",
    ".nii",
    ".nii.gz",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pem",
    ".key",
    ".p12",
    ".pt",
    ".pth",
    ".onnx",
)
HIGH_RISK_PATTERNS = (
    re.compile("-----BEGIN " + r"(?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


def tracked_cmr_files():
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *CMR_SCOPES],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [PurePosixPath(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


class CmrRepositorySafetyTest(unittest.TestCase):
    def test_governance_workflow_watches_governance_files(self):
        workflow = (ROOT / ".github/workflows/cmr-governance-ci.yml").read_text(
            encoding="utf-8"
        )
        for relative_path in GOVERNANCE_FILES:
            with self.subTest(path=relative_path):
                self.assertIn(f"- '{relative_path}'", workflow)

    def test_no_disallowed_tracked_artifact_types(self):
        violations = []
        for path in tracked_cmr_files():
            lowered = path.as_posix().lower()
            if path.name.lower() in DISALLOWED_NAMES or lowered.endswith(DISALLOWED_SUFFIXES):
                violations.append(path.as_posix())
        self.assertEqual(violations, [])

    def test_no_high_risk_secret_signatures(self):
        violations = []
        for relative_path in tracked_cmr_files():
            path = ROOT / relative_path.as_posix()
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(content) for pattern in HIGH_RISK_PATTERNS):
                violations.append(relative_path.as_posix())
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
