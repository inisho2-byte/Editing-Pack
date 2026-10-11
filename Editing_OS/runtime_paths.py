"""MIT. Standalone filesystem configuration and explicit external job boundaries."""
from __future__ import annotations
import json,os,re,shutil,subprocess,sys
from pathlib import Path

class ConfigurationError(ValueError): pass
TOOL_NAMES={'ffmpeg','ffprobe','node','hyperframes_cli','browser','gsap_runtime','inter_regular_font','inter_bold_font'}
FILE_TOOLS={'hyperframes_cli','gsap_runtime','inter_regular_font','inter_bold_font'}
HYPERFRAMES_VERSION='0.8.146'

def contains(root,path):return path==root or root in path.parents
def resolved(value,base=None):
 p=Path(value).expanduser()
 return (p if p.is_absolute() else (base or Path.cwd())/p).resolve()
def root(explicit=None):
 value=explicit or os.environ.get('EDITING_PACK_ROOT')
 candidates=[resolved(value)] if value else list(Path(__file__).resolve().parents)
 for p in candidates:
  marker=p/'toolkit.json'
  if not marker.is_file():continue
  try:m=json.loads(marker.read_text(encoding='utf-8'))
  except (OSError,ValueError) as exc:raise ConfigurationError('Invalid toolkit.json marker') from exc
  if m.get('schema')!='editing-pack-toolkit/v1' or m.get('layout_version')!=1:raise ConfigurationError('Unsupported toolkit layout')
  if not (p/'Editing_OS/Video Editing/Contracts/schemas').is_dir() or not (p/'Editing_OS/Skills/MASTER_PROMPT.md').is_file():raise ConfigurationError('Incomplete toolkit root')
  return p
 raise ConfigurationError('Set --toolkit-root/EDITING_PACK_ROOT to a standalone toolkit with toolkit.json')
def configure(*,toolkit_root=None,config=None,workspace=None):
 """Make CLI overrides visible to existing sibling modules in this process."""
 if toolkit_root is not None:os.environ['EDITING_PACK_ROOT']=str(root(toolkit_root))
 if config is not None:os.environ['EDITING_PACK_CONFIG']=str(resolved(config))
 if workspace is not None:os.environ['EDITING_PACK_WORKSPACE']=str(resolved(workspace))
 settings()  # validate even for read-only commands
 if workspace is not None:workspace_root()
def settings():
 value=os.environ.get('EDITING_PACK_CONFIG');p=resolved(value) if value else root()/'config/toolkit.local.json'
 if not p.exists():
  if value:raise ConfigurationError('Explicit configuration file is missing')
  return {},p.parent
 try:data=json.loads(p.read_text(encoding='utf-8-sig'))
 except (OSError,ValueError) as exc:raise ConfigurationError('Configuration must be readable UTF-8 JSON') from exc
 if not isinstance(data,dict) or data.get('schema')!='editing-pack-config/v1':raise ConfigurationError('Unsupported config schema')
 allowed={'schema','workspace_root','external_tools_root','tools','providers','native_apps','note'}
 if set(data)-allowed:raise ConfigurationError('Unknown top-level configuration field')
 for field in ('workspace_root','external_tools_root'):
  if data.get(field) is not None and not isinstance(data[field],str):raise ConfigurationError(field+' must be a path string or null')
 tools=data.get('tools',{})
 if not isinstance(tools,dict) or set(tools)-TOOL_NAMES:raise ConfigurationError('Unknown tools configuration field')
 if any(v is not None and not isinstance(v,str) for v in tools.values()):raise ConfigurationError('Tool paths must be strings or null')
 providers=data.get('providers',{})
 if not isinstance(providers,dict) or set(providers)-{'ideogram'}:raise ConfigurationError('Unknown provider')
 ideogram=providers.get('ideogram',{})
 if not isinstance(ideogram,dict) or set(ideogram)-{'api_key_env','execute_by_default'}:raise ConfigurationError('Provider values must be environment references, never keys')
 if ideogram.get('api_key_env','IDEOGRAM_API_KEY')!='IDEOGRAM_API_KEY' or ideogram.get('execute_by_default',False) is not False:raise ConfigurationError('Ideogram requires IDEOGRAM_API_KEY and explicit cost-gated execution')
 native=data.get('native_apps',{})
 if not isinstance(native,dict) or set(native)-{'resolve'}:raise ConfigurationError('Unknown native application')
 resolve=native.get('resolve',{})
 if not isinstance(resolve,dict) or set(resolve)-{'enabled','expected_project_id','expected_project_name','mailbox_dir'}:raise ConfigurationError('Unknown Resolve configuration field')
 if 'enabled' in resolve and not isinstance(resolve['enabled'],bool):raise ConfigurationError('Resolve enabled must be boolean')
 if any(v is not None and not isinstance(v,str) for k,v in resolve.items() if k!='enabled'):raise ConfigurationError('Resolve identity/mailbox values must be strings or null')
 return data,p.parent
def workspace_root(explicit=None,required=True):
 data,base=settings();value=explicit or os.environ.get('EDITING_PACK_WORKSPACE') or data.get('workspace_root')
 if not value:
  if required:raise ConfigurationError('Select an external workspace with --workspace, EDITING_PACK_WORKSPACE or workspace_root in config')
  return None
 w=resolved(value,base if not explicit and not os.environ.get('EDITING_PACK_WORKSPACE') else None);r=root()
 if contains(r,w) or contains(w,r):raise ConfigurationError('Workspace and toolkit must not overlap (including link targets)')
 if w==Path(w.anchor) or w==Path.home().resolve() or (os.name=='nt' and w.name.casefold() in {'windows','program files','program files (x86)','users'}):raise ConfigurationError('Choose a dedicated workspace, not a home/system root')
 return w
def output(path,*,require_workspace=False):
 p=resolved(path);r=root()
 if contains(r,p):raise ConfigurationError('Job output must remain outside the toolkit')
 w=workspace_root(required=require_workspace)
 if w is not None and not contains(w,p):raise ConfigurationError('Output must remain within the selected external workspace')
 if p==Path(p.anchor):raise ConfigurationError('Invalid output root')
 return p
def tool(name,explicit=None,required=True):
 if name not in TOOL_NAMES:
  found=shutil.which(name)
  if not found and required:raise ConfigurationError('Missing optional executable: '+name)
  return found
 data,base=settings();env=os.environ.get('EDITING_PACK_'+name.upper());configured=data.get('tools',{}).get(name)
 value=explicit or env or configured
 if value:
  p=resolved(value,base if not explicit and not env else None)
  if not p.is_file():raise ConfigurationError('Configured '+name+' file is missing; fix the explicit path')
  return str(p)
 found=None if name in FILE_TOOLS or name=='browser' else shutil.which(name)
 if not found and required:raise ConfigurationError('Missing '+name+': configure EDITING_PACK_'+name.upper()+' or tools.'+name+'; no automatic installation')
 return found
def command(args):
 args=list(map(str,args))
 if args and args[0] in {'ffmpeg','ffprobe','node'}:args[0]=tool(args[0])
 return args
def child_kwargs():return {'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)} if os.name=='nt' else {}
def child_env():
 env=os.environ.copy();folders=[]
 for name in ('ffmpeg','ffprobe','node'):
  value=tool(name,required=False)
  if value:folders.append(str(Path(value).parent))
 env['PATH']=os.pathsep.join([*dict.fromkeys(folders),env.get('PATH','')]);env['PYTHONDONTWRITEBYTECODE']='1';env['HYPERFRAMES_SKIP_SKILLS']='1'
 browser=tool('browser',required=False)
 if browser:env['PRODUCER_HEADLESS_SHELL_PATH']=browser
 return env
def hyperframes_command(args):
 cli=Path(tool('hyperframes_cli'));package=cli.parent.parent/'package.json'
 try:version=json.loads(package.read_text(encoding='utf-8'))['version']
 except (OSError,ValueError,KeyError) as exc:raise ConfigurationError('HyperFrames CLI must be its installed bin/hyperframes.mjs entry point') from exc
 if version!=HYPERFRAMES_VERSION:raise ConfigurationError('Required HyperFrames version is '+HYPERFRAMES_VERSION+'; configured package is '+str(version))
 return [tool('node'),str(cli),*map(str,args)]
def fonts_filter():
 """An installed system font provider is sufficient; never hardcode Windows fonts."""
 return ''
def native_mailbox():
 data,base=settings();configured=data.get('native_apps',{}).get('resolve',{}).get('mailbox_dir');env=os.environ.get('EDITING_PACK_RESOLVE_MAILBOX')
 if not (env or configured):raise ConfigurationError('Configure an external Resolve mailbox before starting the prototype')
 return output(resolved(env or configured,None if env else base),require_workspace=True)
def common_args(parser):
 parser.add_argument('--toolkit-root',type=Path);parser.add_argument('--config',type=Path);parser.add_argument('--workspace',type=Path)
def configure_args(args):configure(toolkit_root=getattr(args,'toolkit_root',None),config=getattr(args,'config',None),workspace=getattr(args,'workspace',None))
def guard_args(args,names):
 for name in names:
  value=getattr(args,name,None)
  if value is not None:output(value,require_workspace=True)
def model_environment():
 w=workspace_root();cache=output(w/'dependencies/model-cache',require_workspace=True);cache.mkdir(parents=True,exist_ok=True)
 for name,part in [('HF_HOME','huggingface'),('TORCH_HOME','torch')]:os.environ[name]=str(cache/part)
 return cache
