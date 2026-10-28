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
NAMES = ('learn', 'think', 'log', 'write', 'manage')
LEGACY_MAP = {'teacher': 'learn', 'coach': 'think', 'registrar': 'log', 'administrator': 'manage'}
ALL_NAMES = NAMES + tuple(LEGACY_MAP)


def inventory(root, names=NAMES):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in names for p in sorted((root / name).rglob('*')) if p.is_file()}


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
    for filename, names in [('library-format.md', ('log', 'write', 'manage')),
                            ('collaboration.md', NAMES)]:
        values = {(ROOT / name / 'references' / filename).read_bytes() for name in names}
        assert len(values) == 1, f'Shared reference drift: {filename}'
    for name, relative, origin in [('log', 'assets/note.md', 'automatic'),
                                   ('write', 'assets/self-note.md', 'self_written')]:
        data = yaml.safe_load((ROOT / name / relative).read_text(encoding='utf-8').split('---', 2)[1])
        assert data['type'] == 'note' and data['note_origin'] == origin
        assert data['schema'] == 'math-learning/v2'
    print('PASS: five skills, YAML, references, shared rules and note-origin templates')


def differences(left, right):
    return [p for p in sorted(left.keys() | right.keys()) if left.get(p) != right.get(p)]


def save_backup(target, before, after):
    backup = ROOT / 'maintenance/backups' / uuid.uuid4().hex
    backup.mkdir(parents=True)
    shutil.copy2(ROOT / 'maintenance/installed-state.json', backup / 'installed-state.json')
    for name in ALL_NAMES:
        folder = target / name
        assert folder.resolve().parent == target, f'Linked skill directory is unsupported: {folder}'
        if folder.exists():
            shutil.copytree(folder, backup / name)
    assert inventory(backup, ALL_NAMES) == before, 'Backup verification failed; installed files unchanged'
    (backup / 'restore-manifest.json').write_text(json.dumps({
        'target': str(target), 'before': before, 'after': after,
        'added': sorted(after.keys() - before.keys())}, ensure_ascii=False, indent=2), encoding='utf-8')
    return backup


def migrate_names(target):
    """Explicitly migrate the four old names, preserving a recoverable snapshot."""
    check()
    for old, new in LEGACY_MAP.items():
        assert (target / old).is_dir(), f'Expected legacy skill: {old}'
        assert not (target / new).exists(), f'New name already exists: {new}; reconcile first'
    expected_path = ROOT / 'maintenance/installed-state.json'
    assert expected_path.exists(), 'Migration needs the local baseline from the previous installation'
    expected = json.loads(expected_path.read_text(encoding='utf-8'))
    before = inventory(target, ALL_NAMES)
    assert expected['target'] == str(target) and expected['files'] == before, 'Installed content changed; reconcile before migration'
    after = inventory(ROOT)
    backup = save_backup(target, before, after)
    assert inventory(target, ALL_NAMES) == before, 'Concurrent edit detected'
    for relative in after:
        dst = target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dst)
    assert inventory(target) == after, f'New installation incomplete; backup: {backup}'
    legacy_before = {p: value for p, value in before.items() if p.split('/')[0] in LEGACY_MAP}
    assert inventory(target, tuple(LEGACY_MAP)) == legacy_before, 'Legacy files changed during migration; preserved'
    retired = backup / 'retired'
    retired.mkdir()
    for old in LEGACY_MAP:
        source = (target / old).resolve()
        destination = (retired / old).resolve()
        assert source.parent == target and destination.parent == retired.resolve()
        source.rename(destination)
    assert inventory(target, ALL_NAMES) == after, 'Migration verification failed'
    expected_path.write_text(json.dumps({'target': str(target), 'files': after}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Renamed and installed five skills; SHA256 verified; backup: {backup}')


def deploy(target):
    check()
    expected_path = ROOT / 'maintenance/installed-state.json'
    source = inventory(ROOT)
    current = inventory(target, ALL_NAMES)
    assert not any((target / name).exists() for name in LEGACY_MAP), 'Legacy names detected; run migrate-names with the existing baseline'
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
    backup = save_backup(target, current, source)
    # Recheck immediately before writes; multi-file copying is not a transaction.
    assert inventory(target, ALL_NAMES) == current, 'Concurrent edit detected'
    for relative in changed:
        dst = target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dst)
    assert inventory(target, ALL_NAMES) == source, f'Copy incomplete; backup: {backup}'
    expected_path.write_text(json.dumps({'target': str(target), 'files': source},
                                      ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Deployed {len(changed)} files; SHA256 verified; backup: {backup}')


def restore(target, folder):
    backup = folder.resolve()
    manifest = json.loads((backup / 'restore-manifest.json').read_text(encoding='utf-8'))
    assert str(target) == manifest['target'], 'Restore target differs'
    assert all((target / name).resolve().parent == target for name in ALL_NAMES), 'Linked skill directories are unsupported'
    assert inventory(target, ALL_NAMES) == manifest['after'], 'Installed files changed after deployment; reconcile before restoring'
    assert inventory(backup, ALL_NAMES) == manifest['before'], 'Backup content differs from recorded hashes'
    for relative in manifest['before'].keys() | manifest['after'].keys():
        path = (target / relative).resolve()
        assert path.is_relative_to(target) and path.parts[len(target.parts)] in ALL_NAMES
    for relative in manifest['added']:
        path = (target / relative).resolve()
        assert path.is_relative_to(target) and path.parts[len(target.parts)] in ALL_NAMES
        path.unlink()
    for relative in manifest['before']:
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / relative, target / relative)
    # Remove only empty managed directories created by this deployment.
    for name in ALL_NAMES:
        if any(p.startswith(name + '/') for p in manifest['before']):
            continue
        folder = target / name
        if folder.exists():
            for child in sorted((p for p in folder.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                assert child.resolve().is_relative_to(target)
                child.rmdir()
            folder.rmdir()
    assert inventory(target, ALL_NAMES) == manifest['before'], 'Restore incomplete'
    shutil.copy2(backup / 'installed-state.json', ROOT / 'maintenance/installed-state.json')
    print('Restored installed files; source files unchanged')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'status', 'deploy', 'restore', 'migrate-names'))
    parser.add_argument('--target', type=Path, default=Path.home() / '.codex/skills')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    target = args.target.resolve()
    if args.command == 'check':
        check()
    elif args.command == 'status':
        changed = differences(inventory(ROOT), inventory(target, ALL_NAMES))
        print(json.dumps({'target': str(target), 'different_files': changed}, ensure_ascii=False, indent=2))
    elif args.command == 'deploy':
        deploy(target)
    elif args.command == 'migrate-names':
        migrate_names(target)
    else:
        assert args.backup, 'restore requires --backup'
        restore(target, args.backup)


if __name__ == '__main__':
    main()
