import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(BACKEND_DIR))

import codex_feedback_executor as executor


def git_result(stdout='', returncode=0, stderr=''):
    return subprocess.CompletedProcess(['git'], returncode, stdout=stdout, stderr=stderr)


class ControlledFeedbackExecutorTests(unittest.TestCase):
    @patch.object(executor, 'resolve_codex_binary', return_value='/usr/bin/codex')
    def test_command_is_workspace_write_ephemeral_and_fail_closed(self, _binary):
        command = executor.build_execution_command(Path('/tmp/worktree'), Path('/tmp/summary'), 'gpt-test')
        self.assertIn('workspace-write', command)
        self.assertIn('never', command)
        self.assertIn('--ephemeral', command)
        self.assertIn('--ignore-user-config', command)
        self.assertIn('--strict-config', command)
        self.assertIn('shell_environment_policy.inherit="none"', command)
        self.assertNotIn('danger-full-access', command)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', command)
        self.assertNotIn('--add-dir', command)

    def test_environment_drops_server_credentials_and_database_paths(self):
        source = {
            'PATH': '/usr/bin',
            'HOME': '/home/test',
            'LABELSYSTEM_DATABASE_URI': 'sqlite:////secret.db',
            'SSH_AUTH_SOCK': '/tmp/ssh.sock',
            'AWS_SECRET_ACCESS_KEY': 'secret',
            'LABELSYSTEM_CODEX_API_KEY': 'codex-key',
        }
        with patch.dict(os.environ, source, clear=True), patch.object(executor, 'LLM_GATEWAY_CONFIG_PATH', Path('/does/not/exist')):
            env = executor.execution_environment()
        self.assertEqual(env['CODEX_API_KEY'], 'codex-key')
        self.assertEqual(env['OPENAI_API_KEY'], 'codex-key')
        self.assertNotIn('LABELSYSTEM_DATABASE_URI', env)
        self.assertNotIn('SSH_AUTH_SOCK', env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)

    def test_dirty_or_untracked_repository_is_rejected(self):
        sha = 'a' * 40
        with patch.object(executor, '_run_git', side_effect=[
            git_result(),
            git_result(stdout=f'{sha}\n'),
            git_result(stdout='?? apps/web/\n'),
        ]):
            with self.assertRaisesRegex(executor.CodexExecutionError, '未提交或未跟踪'):
                executor.validate_clean_execution_base(sha)

    def test_invalid_base_sha_is_rejected_before_git(self):
        with patch.object(executor, '_run_git') as run_git:
            with self.assertRaisesRegex(executor.CodexExecutionError, '40 位'):
                executor.validate_clean_execution_base('main')
            run_git.assert_not_called()

    def test_protected_runtime_and_data_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for path in ('.env', '.github/workflows/deploy.yml', 'backend/instance/token.json', 'case.dcm', 'deployment/start.sh'):
                with self.subTest(path=path):
                    with self.assertRaises(executor.CodexExecutionError):
                        executor.validate_changed_files(root, [path])

    def test_tests_directory_does_not_bypass_approved_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(executor.CodexExecutionError, '超出批准'):
                executor.validate_changed_files(Path(temp_dir), ['tests/test_unapproved.py'], ['backend/app.py'])

    def test_symlink_is_rejected_before_resolve(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'target.txt').write_text('target', encoding='utf-8')
            (root / 'link.txt').symlink_to('target.txt')
            with self.assertRaisesRegex(executor.CodexExecutionError, '符号链接'):
                executor.validate_changed_files(root, ['link.txt'], ['link.txt'])

    def test_rename_parser_keeps_both_old_and_new_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            subprocess.run(['git', 'init'], cwd=repository, check=True, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repository, check=True)
            (repository / 'old.txt').write_text('value\n', encoding='utf-8')
            subprocess.run(['git', 'add', 'old.txt'], cwd=repository, check=True)
            subprocess.run(['git', 'commit', '-m', 'base'], cwd=repository, check=True, capture_output=True)
            subprocess.run(['git', 'mv', 'old.txt', 'new.txt'], cwd=repository, check=True)
            self.assertEqual(set(executor._changed_files(repository)), {'old.txt', 'new.txt'})

    def test_containment_does_not_mount_server_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / 'repo'
            repository.mkdir()
            subprocess.run(['git', 'init'], cwd=repository, check=True, capture_output=True)
            sandbox_tmp = root / 'sandbox'
            sandbox_tmp.mkdir()
            with patch.object(executor, 'PROJECT_ROOT', repository):
                command = executor._contained_command(
                    repository,
                    sandbox_tmp,
                    ['/usr/bin/true'],
                    cwd=repository,
                    network=False,
                    include_frontend_dependencies=False,
                )
            pairs = list(zip(command, command[1:]))
            self.assertNotIn(('/', '/'), pairs)
            self.assertIn('--unshare-net', command)
            self.assertIn('--die-with-parent', command)

    @unittest.skipIf(os.environ.get('LABELSYSTEM_NESTED_SANDBOX') == '1', 'outer verification sandbox already active')
    def test_required_feedback_suite_runs_in_minimal_sandbox(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / 'controller.log'
            tests, passed = executor._run_verification(repository, [], log_path, require_feedback_tests=True)
        self.assertTrue(passed)
        self.assertTrue(any(item['id'] == 'feedback_unit_tests' and item['passed'] for item in tests['commands']))

    def test_prompt_freezes_scope_and_forbids_production_actions(self):
        prompt = executor.build_execution_prompt(
            {'id': 9, 'title': 'test'},
            {'codex_brief': 'fix it'},
            'b' * 40,
        )
        self.assertIn('isolated Git worktree', prompt)
        self.assertIn('Do not access patient/DICOM/runtime data', prompt)
        self.assertIn('Do not start/stop services, deploy, push', prompt)
        self.assertIn('"id": 9', prompt)

    def test_merge_is_fast_forward_only_and_requires_exact_parent(self):
        base = 'c' * 40
        candidate = 'd' * 40
        calls = []
        head_reads = 0

        def fake_git(*args, **kwargs):
            nonlocal head_reads
            calls.append(args)
            if args[:2] == ('branch', '--show-current'):
                return git_result(stdout='main\n')
            if args[:2] == ('rev-parse', f'{candidate}^'):
                return git_result(stdout=f'{base}\n')
            if args[:2] == ('rev-parse', 'HEAD'):
                head_reads += 1
                return git_result(stdout=f'{base if head_reads == 1 else candidate}\n')
            return git_result()

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(executor, 'PROJECT_ROOT', Path(temp_dir) / 'repository'), patch.object(executor, 'repository_is_clean', return_value=True), patch.object(executor, '_run_git', side_effect=fake_git):
            merged = executor.merge_candidate(base, candidate, 'main')
        self.assertEqual(merged, candidate)
        self.assertIn(('merge', '--ff-only', candidate), calls)

    @unittest.skipIf(os.environ.get('LABELSYSTEM_NESTED_SANDBOX') == '1', 'nested bubblewrap is covered by the outer controller test')
    def test_end_to_end_fake_codex_creates_reviewable_single_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / 'repository'
            repository.mkdir()
            subprocess.run(['git', 'init', '-b', 'main'], cwd=repository, check=True, capture_output=True)
            subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repository, check=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repository, check=True)
            (repository / 'sample.txt').write_text('before\n', encoding='utf-8')
            subprocess.run(['git', 'add', 'sample.txt'], cwd=repository, check=True)
            subprocess.run(['git', 'commit', '-m', 'base'], cwd=repository, check=True, capture_output=True)
            base_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True, capture_output=True, check=True).stdout.strip()

            fake_codex = root / 'fake-codex'
            fake_codex.write_text(
                '#!/usr/bin/python3\n'
                'import pathlib, sys\n'
                'args = sys.argv[1:]\n'
                'summary = pathlib.Path(args[args.index("-o") + 1])\n'
                'pathlib.Path("sample.txt").write_text("before\\nafter\\n", encoding="utf-8")\n'
                'summary.write_text("changed sample safely", encoding="utf-8")\n'
                'print("{\\"type\\":\\"item.completed\\"}")\n',
                encoding='utf-8',
            )
            fake_codex.chmod(0o755)
            artifact_dir = root / 'artifacts' / '1'
            worktree_root = root / 'worktrees'

            with patch.object(executor, 'PROJECT_ROOT', repository), patch.object(executor, 'resolve_codex_binary', return_value=str(fake_codex)):
                try:
                    result = executor.run_controlled_execution(
                        1,
                        {'id': 9, 'title': 'fake'},
                        {'codex_brief': 'change sample', 'allowed_paths': ['sample.txt']},
                        base_sha=base_sha,
                        artifact_dir=artifact_dir,
                        worktree_root=worktree_root,
                        model='fake-model',
                        timeout_seconds=120,
                        require_feedback_tests=False,
                    )
                except executor.CodexExecutionError as exc:
                    log_path = artifact_dir / 'controller.log'
                    details = log_path.read_text(encoding='utf-8', errors='replace') if log_path.is_file() else ''
                    self.fail(f'{exc}\n{details}')

            self.assertTrue(result['tests_passed'])
            self.assertEqual(result['changed_files'], ['sample.txt'])
            parent = subprocess.run(
                ['git', 'rev-parse', f"{result['candidate_sha']}^"],
                cwd=repository,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(parent, base_sha)
            self.assertIn('+after', (artifact_dir / 'changes.diff').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
