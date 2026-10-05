"""Compare module/CIL grants and compile against the captured target ROM.

Only reads ROM input and emits local reports. Never installs live policy.
"""
from pathlib import Path
import json
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT.parent / 'tools' / 'OplusOriginPatcher'
sys.path.insert(0, str(TOOLS))
from sources import RomSource
from cil_policy import compile_chain, inputs, policy_version

DOMAINS = {'init', 'vendor_init', 'system_server', 'surfaceflinger',
           'hal_graphics_composer_default'}
TYPES = {'sysfs_graphics_ffl', 'oppo_log_sysfs', 'alpha_sysfs'}


def module_grants():
    grants = set()
    for raw in (ROOT / 'module_files' / 'sepolicy.rule').read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'allow (\w+) (\w+) (\w+) (?:\{ ([\w ]+) \}|(\w+))', line)
        if not match:
            raise ValueError(f'Unsupported rule syntax: {line}')
        domain, target, cls, multiple, single = match.groups()
        grants.update((domain, target, cls, perm) for perm in (multiple or single).split())
    return grants


def cil_grants(filename='display_nodes.cil'):
    grants = set()
    for raw in (ROOT / 'module_files' / filename).read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'\(allow (\w+) (\w+) \((\w+) \(([\w ]+)\)\)\)', line)
        if not match:
            raise ValueError(f'Unsupported CIL syntax: {line}')
        domain, target, cls, perms = match.groups()
        grants.update((domain, target, cls, perm) for perm in perms.split())
    return grants


class DisplayPolicyTests(unittest.TestCase):
    def test_cil_matches_module_display_block(self):
        module = {rule for rule in module_grants() if rule[1] in TYPES}
        self.assertEqual(module, cil_grants())

    def test_exact_scope(self):
        expected = {(d, t, cls, perm) for d in DOMAINS for t in TYPES
                    for cls, perms in [('dir', ('getattr', 'open', 'read', 'search')),
                                       ('file', ('getattr', 'open', 'read', 'write'))]
                    for perm in perms}
        expected.update(('hal_fingerprint_oppo', 'sysfs_graphics_ffl', cls, perm)
                        for cls, perms in [('dir', ('getattr', 'open', 'read', 'search')),
                                           ('file', ('getattr', 'open', 'read', 'write'))]
                        for perm in perms)
        self.assertEqual(cil_grants(), expected)

    def test_complete_user_additions_match_module(self):
        extras = cil_grants('user_additions.cil')
        self.assertEqual(len(extras), 18)
        self.assertTrue(extras.issubset(module_grants()))
        self.assertFalse(any(rule[2] == 'property_service' for rule in extras))

    def test_no_generic_sysfs_write_or_permissive(self):
        self.assertNotIn(('init', 'sysfs', 'file', 'write'), module_grants())
        for filename, comment in [('sepolicy.rule', '#'), ('display_nodes.cil', ';')]:
            lines = [line.split(comment, 1)[0].strip() for line in
                     (ROOT / 'module_files' / filename).read_text().splitlines()]
            self.assertFalse(any('permissive' in line for line in lines))


def compile_captured_target(source_dir: Path):
    output = ROOT.parent / 'analysis' / 'hbm_fod_20261005' / 'policy_validation'
    output.mkdir(parents=True, exist_ok=True)
    rules = '\n'.join(f'(allow {domain} {target} ({cls} ({perm})))'
                      for domain, target, cls, perm in sorted(module_grants())) + '\n'
    report = {'live_policy_modified': False, 'generic_sysfs_write': False,
              'new_permissive': False, 'display_grants': len(cil_grants()), 'chains': []}
    with RomSource(source_dir) as source:
        cache = next(n for n in ('odm/etc/selinux/precompiled_sepolicy',
                                'vendor/etc/selinux/precompiled_sepolicy') if source.has(n))
        version = policy_version(source.read(cache))
        jobs = [(False, False), (True, False)]
        if source.has('system/etc/selinux/vivodebug_plat_sepolicy.cil'):
            jobs.append((True, True))
        for debug, vivo_debug in jobs:
            names = inputs(source, debug, vivo_debug)
            name = 'vivo-debug' if vivo_debug else 'debug' if debug else 'normal'
            # Append to a local compiler input only, never to the ROM itself.
            target = 'vendor/etc/selinux/vendor_sepolicy_debug.cil' if debug and source.has(
                'vendor/etc/selinux/vendor_sepolicy_debug.cil') else 'vendor/etc/selinux/vendor_sepolicy.cil'
            updates = {target: source.read(target) + b'\n' + rules.encode()}
            result = compile_chain(source, names, updates, version, output / f'{name}.log')
            (output / f'{name}.policy').write_bytes(result)
            report['chains'].append({'name': name, 'inputs': names, 'policy_version': version,
                                     'bytes': len(result), 'compiled': True,
                                     'neverallow_check': 'disabled like existing OEM fallback compiler'})
            print(f'PASS: full target CIL chain {name} ({len(result)} bytes)')
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DisplayPolicyTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)
    if len(sys.argv) == 2:
        compile_captured_target(Path(sys.argv[1]))
