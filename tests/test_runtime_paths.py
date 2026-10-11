"""MIT. Standalone configuration and boundary regressions."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Editing_OS'))
import runtime_paths as runtime
class RuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.cfg=self.base/'config.json'
  self.environment=mock.patch.dict(os.environ,{},clear=False);self.environment.start();self.addCleanup(self.environment.stop)
  for k in list(os.environ):
   if k.startswith('EDITING_PACK_'):os.environ.pop(k)
  self.data={'schema':'editing-pack-config/v1','workspace_root':str(self.base/'workspace'),'tools':{}}
  self.save();os.environ['EDITING_PACK_CONFIG']=str(self.cfg)
 def save(self):self.cfg.write_text(json.dumps(self.data),encoding='utf-8')
 def test_root_is_module_derived(self):self.assertEqual(runtime.root(),Path(__file__).resolve().parents[1])
 def test_explicit_invalid_root_does_not_fall_back(self):
  with self.assertRaises(runtime.ConfigurationError):runtime.root(self.base)
 def test_explicit_missing_config_does_not_fall_back(self):
  os.environ['EDITING_PACK_CONFIG']=str(self.base/'missing.json')
  with self.assertRaises(runtime.ConfigurationError):runtime.settings()
 def test_config_relative_workspace_is_relative_to_config(self):
  self.data['workspace_root']='jobs';self.save();self.assertEqual(runtime.workspace_root(),self.base/'jobs')
 def test_environment_workspace_overrides_config(self):
  os.environ['EDITING_PACK_WORKSPACE']=str(self.base/'override');self.assertEqual(runtime.workspace_root(),self.base/'override')
 def test_workspace_cannot_be_in_toolkit(self):
  self.data['workspace_root']=str(runtime.root()/'jobs');self.save()
  with self.assertRaises(runtime.ConfigurationError):runtime.workspace_root()
 def test_workspace_cannot_contain_toolkit(self):
  self.data['workspace_root']=str(runtime.root().parent);self.save()
  with self.assertRaises(runtime.ConfigurationError):runtime.workspace_root()
 def test_output_inside_toolkit_is_refused(self):
  with self.assertRaises(runtime.ConfigurationError):runtime.output(runtime.root()/'leak.json')
 def test_output_outside_configured_workspace_is_refused(self):
  with self.assertRaises(runtime.ConfigurationError):runtime.output(self.base/'elsewhere.json')
 def test_output_inside_workspace_is_accepted(self):
  self.assertEqual(runtime.output(self.base/'workspace/job/out.json'),self.base/'workspace/job/out.json')
 def test_invalid_configured_tool_does_not_fall_back_to_path(self):
  self.data['tools']['ffmpeg']='missing.exe';self.save()
  with mock.patch('shutil.which',return_value='available.exe'),self.assertRaises(runtime.ConfigurationError):runtime.tool('ffmpeg')
 def test_file_resource_has_no_path_fallback(self):
  with mock.patch('shutil.which',return_value='available.js'),self.assertRaises(runtime.ConfigurationError):runtime.tool('gsap_runtime')
 def test_configured_paths_with_spaces_are_preserved(self):
  file=self.base/'tools with spaces/tool.exe';file.parent.mkdir();file.write_text('fixture');self.data['tools']['ffmpeg']=str(file);self.save();self.assertEqual(runtime.command(['ffmpeg','-version']),[str(file),'-version'])
 def test_hyperframes_requires_exact_package_version(self):
  package=self.base/'hyperframes';(package/'bin').mkdir(parents=True);cli=package/'bin/hyperframes.mjs';cli.write_text('// fixture');(package/'package.json').write_text('{"version":"9.0.0"}');self.data['tools']['hyperframes_cli']=str(cli);self.save()
  with self.assertRaises(runtime.ConfigurationError):runtime.hyperframes_command(['lint'])
 def test_unknown_config_and_raw_provider_key_are_refused(self):
  self.data['providers']={'ideogram':{'api_key':'fixture'}};self.save()
  with self.assertRaises(runtime.ConfigurationError):runtime.settings()
 def test_missing_native_mailbox_is_actionable_not_import_error(self):
  with self.assertRaises(runtime.ConfigurationError):runtime.native_mailbox()
 def test_native_mailbox_must_be_inside_workspace(self):
  self.data['native_apps']={'resolve':{'mailbox_dir':str(runtime.root()/'mailbox')}};self.save()
  with self.assertRaises(runtime.ConfigurationError):runtime.native_mailbox()
 def test_child_processes_are_hidden_on_windows(self):
  if os.name=='nt':self.assertTrue(runtime.child_kwargs()['creationflags'])
 def test_model_cache_is_external_even_with_old_environment(self):
  os.environ['HF_HOME']='old-location';cache=runtime.model_environment();self.assertTrue(runtime.contains(runtime.workspace_root(),cache));self.assertEqual(os.environ['HF_HOME'],str(cache/'huggingface'))
if __name__=='__main__':unittest.main()
