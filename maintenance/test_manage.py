"""Exercise deployment and rollback only in an isolated temporary copy."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='math-skills-test-') as tmp:
        root = Path(tmp) / 'source'
        shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git', 'backups', '__pycache__'))
        spec = importlib.util.spec_from_file_location('sandbox_manage', root / 'maintenance/manage.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        target = Path(tmp) / 'installed'
        for name in m.NAMES:
            if name != 'write':
                shutil.copytree(root / name, target / name)
        page = root / 'teacher/SKILL.md'
        page.write_text(page.read_text(encoding='utf-8') + '\nSandbox revision.\n', encoding='utf-8')
        state = root / 'maintenance/installed-state.json'
        state.write_text(json.dumps({'target': str(target.resolve()), 'files': m.inventory(target)}), encoding='utf-8')
        before = m.inventory(target)
        (root / 'teacher/references/sandbox-added.md').write_text('Sandbox addition\n', encoding='utf-8')

        def run(command, *extra, success=True):
            result = subprocess.run([sys.executable, '-X', 'utf8', str(root / 'maintenance/manage.py'),
                                     command, '--target', str(target), *extra], capture_output=True, text=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr

        run('check')
        run('deploy')
        assert m.inventory(target) == m.inventory(root)
        backup = next((root / 'maintenance/backups').iterdir())
        live = target / 'coach/SKILL.md'
        previous = live.read_bytes()
        live.write_bytes(previous + b'\nConcurrent edit\n')
        run('deploy', success=False)
        run('restore', '--backup', str(backup), success=False)
        assert live.read_bytes() != previous  # Failed commands preserve the new edit.
        live.write_bytes(previous)
        run('restore', '--backup', str(backup))
        assert m.inventory(target) == before
        # A clean checkout carries no machine-specific state file.
        state.unlink()
        fresh = Path(tmp) / 'fresh-install'
        untouched = fresh / 'unrelated/SKILL.md'
        untouched.parent.mkdir(parents=True)
        untouched.write_text('unrelated skill\n', encoding='utf-8')
        known_backups = set((root / 'maintenance/backups').iterdir())
        run('deploy', '--target', str(fresh))
        assert m.inventory(fresh) == m.inventory(root)
        new_backup, = set((root / 'maintenance/backups').iterdir()) - known_backups
        run('restore', '--target', str(fresh), '--backup', str(new_backup))
        assert m.inventory(fresh) == {}
        assert untouched.read_text(encoding='utf-8') == 'unrelated skill\n'
        shared = root / 'coach/references/collaboration.md'
        shared.write_bytes(shared.read_bytes() + b'\nDrift\n')
        run('check', success=False)
        print('PASS: check; deploy hashes; external-edit refusal; restore refusal; restore hashes; clean-checkout install and restore; unrelated skill preserved; shared-reference drift')


if __name__ == '__main__':
    main()
