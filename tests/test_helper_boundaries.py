"""MIT. New helper CLI boundaries, with fictional generated inputs and no user project."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

KIT = Path(__file__).parents[1]
HELPERS = KIT / 'Editing_OS/Tools/editing-workbench'


class HelperBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='helper-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'schema': 'editing-pack-config/v1', 'workspace_root': str(self.workspace)}))
        self.audio = self.workspace / 'silence.wav'
        with wave.open(str(self.audio), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0\0' * 800)
        self.env = os.environ.copy()
        for key in ['EDITING_PACK_ROOT', 'EDITING_PACK_WORKSPACE', 'EDITING_PACK_CONFIG']:
            self.env.pop(key, None)
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'

    def call(self, name, args, isolated=False):
        return subprocess.run([sys.executable, '-B', *(['-S'] if isolated else []), str(HELPERS / name),
            '--config', str(self.config), *map(str, args)], env=self.env, capture_output=True, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)

    def test_audio_output_outside_workspace_is_rejected_before_write(self):
        out = self.root / 'outside.json'
        r = self.call('audio_motion.py', [self.audio, '--out', out])
        self.assertEqual(r.returncode, 2)
        self.assertIn('within the selected external workspace', r.stderr)
        self.assertFalse(out.exists())

    def test_audio_existing_output_and_source_are_immutable(self):
        for out in [self.audio, self.workspace / 'exists.json']:
            if not out.exists(): out.write_text('existing fixture')
            before = out.read_bytes()
            r = self.call('audio_motion.py', [self.audio, '--out', out])
            self.assertEqual(r.returncode, 2)
            self.assertEqual(out.read_bytes(), before)

    def test_audio_rational_clock_cli_reports_bound_source(self):
        out = self.workspace / 'measured.json'
        r = self.call('audio_motion.py', [self.audio, '--out', out, '--fps', '30000/1001'])
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(out.read_text())
        self.assertEqual(data['fps'], '30000/1001')
        self.assertEqual(data['frame_count'], 3)
        self.assertEqual(len(data['source_sha256']), 64)

    def test_missing_optional_pillow_has_explicit_profile_diagnostic(self):
        out = self.workspace / 'unavailable.json'
        r = self.call('style_inspect.py', [self.workspace / 'generated.png', '--out', out], isolated=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Missing optional Pillow', r.stderr)
        self.assertFalse(out.exists())

    def test_demo_missing_draft_flag_and_unsafe_names_write_nothing(self):
        for args in [['audio', '--job-name', 'plain'], ['audio', '--job-name', '../escape', '--allow-unapproved-draft-treatment']]:
            r = self.call('capability_examples.py', args)
            self.assertEqual(r.returncode, 2)
        self.assertFalse((self.workspace / 'jobs').exists())

    def test_studio_missing_resources_fails_required_profile_before_job_creation(self):
        r = self.call('capability_examples.py', ['studio', '--job-name', 'missing', '--allow-unapproved-draft-treatment'])
        self.assertEqual(r.returncode, 2)
        self.assertIn('Missing three_module', r.stderr)
        self.assertFalse((self.workspace / 'jobs').exists())


if __name__ == '__main__':
    unittest.main()
