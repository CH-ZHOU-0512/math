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
        page = root / 'learn/SKILL.md'
        page.write_text(page.read_text(encoding='utf-8') + '\nSandbox revision.\n', encoding='utf-8')
        state = root / 'maintenance/installed-state.json'
        state.write_text(json.dumps({'target': str(target.resolve()), 'files': m.inventory(target)}), encoding='utf-8')
        before = m.inventory(target)
        (root / 'learn/references/sandbox-added.md').write_text('Sandbox addition\n', encoding='utf-8')

        def run(command, *extra, success=True):
            result = subprocess.run([sys.executable, '-X', 'utf8', str(root / 'maintenance/manage.py'),
                                     command, '--target', str(target), *extra], capture_output=True, text=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr

        run('check')
        run('deploy')
        assert m.inventory(target) == m.inventory(root)
        backup = next((root / 'maintenance/backups').iterdir())
        live = target / 'think/SKILL.md'
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
        legacy = Path(tmp) / 'legacy-install'
        reverse = {value: key for key, value in m.LEGACY_MAP.items()}
        for name in m.NAMES:
            old = reverse.get(name, name)
            shutil.copytree(root / name, legacy / old)
            entry = legacy / old / 'SKILL.md'
            entry.write_text(entry.read_text(encoding='utf-8').replace('name: ' + name, 'name: ' + old), encoding='utf-8')
        legacy_before = m.inventory(legacy, m.ALL_NAMES)
        state.write_text(json.dumps({'target': str(legacy.resolve()), 'files': legacy_before}), encoding='utf-8')
        collision = legacy / 'learn/SKILL.md'
        collision.parent.mkdir()
        collision.write_text('existing unrelated learn skill\n', encoding='utf-8')
        run('migrate-names', '--target', str(legacy), success=False)
        assert collision.read_text(encoding='utf-8') == 'existing unrelated learn skill\n'
        collision.unlink()
        collision.parent.rmdir()
        edited = legacy / 'coach/SKILL.md'
        old_bytes = edited.read_bytes()
        edited.write_bytes(old_bytes + b'\nConcurrent edit\n')
        run('migrate-names', '--target', str(legacy), success=False)
        assert edited.read_bytes() != old_bytes
        edited.write_bytes(old_bytes)
        known_backups = set((root / 'maintenance/backups').iterdir())
        run('migrate-names', '--target', str(legacy))
        assert m.inventory(legacy, m.ALL_NAMES) == m.inventory(root)
        assert not any((legacy / old).exists() for old in m.LEGACY_MAP)
        rename_backup, = set((root / 'maintenance/backups').iterdir()) - known_backups
        run('restore', '--target', str(legacy), '--backup', str(rename_backup))
        assert m.inventory(legacy, m.ALL_NAMES) == legacy_before
        assert not any((legacy / new).exists() for new in m.LEGACY_MAP.values())
        shared = root / 'think/references/collaboration.md'
        shared.write_bytes(shared.read_bytes() + b'\nDrift\n')
        run('check', success=False)
        print('PASS: deploy/restore; external edits; clean install; unrelated skills; name collisions; legacy rename/restore hashes; shared-reference drift')


if __name__ == '__main__':
    main()
