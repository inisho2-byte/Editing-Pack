"""MIT. Export privacy gates using isolated fictional repositories, never user projects."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release_export', Path(__file__).parents[1] / 'scripts/export_release.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='export-gate-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / 'payload'
        self.dst = self.root / 'checkout'
        self.protected = self.root / 'protected'
        for p in (self.payload, self.dst, self.protected):
            p.mkdir()
        self.env = os.environ.copy()
        self.env.update(GIT_CONFIG_GLOBAL='NUL' if os.name == 'nt' else '/dev/null', GIT_CONFIG_NOSYSTEM='1')
        self.git('-c', 'init.defaultBranch=main', 'init')
        (self.dst / 'README.md').write_text('# Fixture baseline\n', encoding='utf-8')
        self.git('add', 'README.md')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fictional baseline')
        self.origin = 'https://github.com/inisho2-byte/Editing-Pack.git'
        self.git('remote', 'add', 'origin', self.origin)
        self.git('remote', 'set-url', '--push', 'origin', 'disabled://test-only')
        self.manifest = self.root / 'manifest.json'
        self.report = self.root / 'report.json'
        self.data = {'schema': 'editing-pack-export/v1', 'payload_root': str(self.payload),
            'protected_roots': [str(self.protected)], 'expected_origin': self.origin,
            'baseline_commit': self.git('rev-parse', 'HEAD').strip(),
            'baseline_files': {'README.md': exporter.digest(self.dst / 'README.md')}, 'files': []}
        self.add('README.md', '# Fixture update\n')

    def git(self, *args):
        r = subprocess.run(['git', '-C', str(self.dst), *args], env=self.env, capture_output=True,
            text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def add(self, name, text):
        p = self.payload / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8', newline='\n')
        self.data['files'].append({'source': name, 'destination': name,
            'sha256': exporter.digest(p), 'bytes': p.stat().st_size})

    def run_export(self, apply=False):
        self.manifest.write_text(json.dumps(self.data), encoding='utf-8')
        return exporter.run(self.manifest, self.dst, self.report, apply)

    def refusal(self):
        before = (self.dst / 'README.md').read_bytes()
        with self.assertRaises(exporter.ExportError):
            self.run_export(True)
        self.assertEqual((self.dst / 'README.md').read_bytes(), before)

    def test_explicit_web_source_dry_run_apply_and_resume(self):
        for name, text in [('starter/scene.js', 'export const state = 1;\n'),
                ('starter/index.html', '<!doctype html><div>Draft fixture</div>\n'),
                ('starter/stage.css', '.draft {color: black}\n')]:
            self.add(name, text)
        self.assertEqual(self.run_export()['mode'], 'dry-run')
        self.assertFalse((self.dst / 'starter/scene.js').exists())
        for _ in range(2):
            self.assertEqual(self.run_export(True)['files'], 4)
        self.assertFalse(json.loads(self.report.read_text())['publication_approved'])

    def test_relative_traversal_absolute_reserved_and_local_names(self):
        for value in ['../out.js', '/out.html', 'a/../out.css', 'a\\out.js', 'CON.js', 'a/toolkit.local.json']:
            with self.subTest(value=value), self.assertRaises(exporter.ExportError):
                exporter.relative(value)

    def test_unknown_source_and_destination_files_refuse_before_writes(self):
        (self.payload / 'extra.js').write_text('unknown')
        self.refusal()
        (self.payload / 'extra.js').unlink()
        (self.dst / 'extra.html').write_text('unknown')
        self.refusal()

    def test_binary_media_private_categories_and_oversize_refused(self):
        for value in ['jobs/draft.html', 'projects/scene.js', 'dependencies/library.js', 'clip.mp4', 'archive.zip']:
            with self.subTest(value=value), self.assertRaises(exporter.ExportError):
                exporter.relative(value)
        for data in [b'\x00', b'PK\x03\x04payload', b'x' * 2_000_001]:
            p = self.payload / 'README.md'
            p.write_bytes(data)
            self.data['files'][0].update(sha256=exporter.digest(p), bytes=len(data))
            self.refusal()

    def test_embedded_machine_paths_refused_in_web_types(self):
        for name in ['scene.js', 'index.html', 'stage.css']:
            for value in ['C:' + '/Users/Fixture/private', 'file:' + '//private/fixture']:
                with self.subTest(name=name, value=value):
                    self.add(name, value)
                    self.refusal()
                    self.data['files'].pop()
                    (self.payload / name).unlink()

    def test_stale_source_hash_and_baseline_refused(self):
        original = dict(self.data['files'][0])
        self.data['files'][0]['sha256'] = '0' * 64
        self.refusal()
        self.data['files'][0] = original
        self.data['baseline_commit'] = '0' * 40
        self.refusal()

    def test_wrong_origin_and_enabled_push_refused(self):
        self.git('remote', 'set-url', 'origin', 'https://example.com/wrong.git')
        self.refusal()
        self.git('remote', 'set-url', 'origin', self.origin)
        self.git('remote', 'set-url', '--push', 'origin', self.origin)
        self.refusal()

    def test_protected_overlap_and_internal_manifest_refused(self):
        self.data['protected_roots'] = [str(self.dst)]
        self.refusal()
        self.data['protected_roots'] = [str(self.protected)]
        self.manifest = self.payload / 'manifest.json'
        self.refusal()

    def test_windows_junction_or_posix_link_rejected_without_reading_target(self):
        target = self.root / 'private fixture'
        target.mkdir()
        link = self.payload / 'linked'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
        self.addCleanup(lambda: link.rmdir() if os.name == 'nt' else link.unlink())
        self.refusal()

    def test_partial_interruption_only_identical_manifested_writes_resume(self):
        self.add('starter/scene.js', 'export const fixture = true;\n')
        (self.dst / 'README.md').write_bytes((self.payload / 'README.md').read_bytes())
        self.assertEqual(self.run_export(True)['files'], 2)
        (self.dst / 'starter/scene.js').write_text('unexpected partial write')
        self.refusal()


if __name__ == '__main__':
    unittest.main()
