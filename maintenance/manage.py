"""Check, compare and deploy the mathematics toolbox. Run with Python + PyYAML."""
import argparse
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('teacher', 'coach', 'registrar', 'write', 'administrator')


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in NAMES for p in sorted((root / name).rglob('*')) if p.is_file()}


def check():
    for name in NAMES:
        folder = ROOT / name
        entry = (folder / 'SKILL.md').read_text(encoding='utf-8')
        meta = yaml.safe_load(entry.split('---', 2)[1])
        assert meta['name'] == name and isinstance(meta['description'], str) and meta['description']
        yaml.safe_load((folder / 'agents/openai.yaml').read_text(encoding='utf-8'))
        for page in folder.rglob('*.md'):
            for ref in re.findall(r'\]\(([^)]+)\)', page.read_text(encoding='utf-8')):
                if '://' not in ref and not ref.startswith('#'):
                    assert (page.parent / ref.split('#')[0]).is_file(), f'Missing reference: {page}: {ref}'
    for filename, names in [('library-format.md', ('registrar', 'write', 'administrator')),
                            ('collaboration.md', NAMES)]:
        values = {(ROOT / name / 'references' / filename).read_bytes() for name in names}
        assert len(values) == 1, f'Shared reference drift: {filename}'
    for name, relative, origin in [('registrar', 'assets/note.md', 'automatic'),
                                   ('write', 'assets/self-note.md', 'self_written')]:
        data = yaml.safe_load((ROOT / name / relative).read_text(encoding='utf-8').split('---', 2)[1])
        assert data['type'] == 'note' and data['note_origin'] == origin
        assert data['schema'] == 'math-learning/v2'
    print('PASS: five skills, YAML, references, shared rules and note-origin templates')


def differences(left, right):
    return [p for p in sorted(left.keys() | right.keys()) if left.get(p) != right.get(p)]


def deploy(target):
    check()
    expected_path = ROOT / 'maintenance/installed-state.json'
    source = inventory(ROOT)
    current = inventory(target)
    if not expected_path.exists():
        assert not current or current == source, 'Existing installation differs; inspect and reconcile before first deployment'
        expected_path.write_text(json.dumps({'target': str(target), 'files': current},
                                           ensure_ascii=False, indent=2), encoding='utf-8')
    expected = json.loads(expected_path.read_text(encoding='utf-8'))
    assert str(target) == expected['target'], 'Target differs from baseline; capture its baseline first'
    assert current == expected['files'], 'Installed files changed: inspect status and reconcile before deployment'
    assert not (current.keys() - source.keys()), 'Removing installed files needs an explicit migration'
    changed = differences(current, source)
    if not changed:
        print('Already synchronized')
        return
    backup = ROOT / 'maintenance/backups' / uuid.uuid4().hex
    backup.mkdir(parents=True)
    shutil.copy2(expected_path, backup / 'installed-state.json')
    for name in NAMES:
        if (target / name).exists():
            shutil.copytree(target / name, backup / name)
    assert inventory(backup) == current, 'Backup verification failed; installed files unchanged'
    (backup / 'restore-manifest.json').write_text(json.dumps({
        'target': str(target), 'before': current, 'after': source,
        'added': sorted(source.keys() - current.keys())}, ensure_ascii=False, indent=2), encoding='utf-8')
    # Recheck immediately before writes; multi-file copying is not a transaction.
    assert inventory(target) == current, 'Concurrent edit detected'
    for relative in changed:
        dst = target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dst)
    assert inventory(target) == source, f'Copy incomplete; backup: {backup}'
    expected_path.write_text(json.dumps({'target': str(target), 'files': source},
                                      ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Deployed {len(changed)} files; SHA256 verified; backup: {backup}')


def restore(target, folder):
    backup = folder.resolve()
    manifest = json.loads((backup / 'restore-manifest.json').read_text(encoding='utf-8'))
    assert str(target) == manifest['target'], 'Restore target differs'
    assert inventory(target) == manifest['after'], 'Installed files changed after deployment; reconcile before restoring'
    assert inventory(backup) == manifest['before'], 'Backup content differs from recorded hashes'
    for relative in manifest['added']:
        path = (target / relative).resolve()
        assert path.is_relative_to(target) and path.parts[len(target.parts)] in NAMES
        path.unlink()
    for relative in manifest['before']:
        shutil.copy2(backup / relative, target / relative)
    assert inventory(target) == manifest['before'], 'Restore incomplete'
    shutil.copy2(backup / 'installed-state.json', ROOT / 'maintenance/installed-state.json')
    print('Restored installed files; source files unchanged')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'status', 'deploy', 'restore'))
    parser.add_argument('--target', type=Path, default=Path.home() / '.codex/skills')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    target = args.target.resolve()
    if args.command == 'check':
        check()
    elif args.command == 'status':
        changed = differences(inventory(ROOT), inventory(target))
        print(json.dumps({'target': str(target), 'different_files': changed}, ensure_ascii=False, indent=2))
    elif args.command == 'deploy':
        deploy(target)
    else:
        assert args.backup, 'restore requires --backup'
        restore(target, args.backup)


if __name__ == '__main__':
    main()
