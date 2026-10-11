"""MIT. Export only explicitly manifested, reviewed UTF-8 release payload files.

The manifest and detailed reports contain local information and belong outside
the source and destination repositories. Dry-run is the default. No Git writes,
staging, commits, network access, or publication are performed by this tool.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,stat,subprocess
from pathlib import Path,PurePosixPath

class ExportError(ValueError): pass
ALLOWED={'.md','.py','.json','.txt','.lua','.toml','.yml','.yaml','.ps1','.sh'}
SPECIAL={'LICENSE','LICENSE-DOCS','.gitignore','.gitattributes','.env.example'}
BLOCKED={'.git','.venv','venv','node_modules','__pycache__','videos','projects','assets','archive','audits','case studies','working_mem','.claude','.codex','personal projects','client projects',
         'jobs','inputs','outputs','exports','renders','work','workspace','workspaces','cache','.cache','logs','dependencies','.idea','.vscode','.hyperframes'}
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inside(p,r): return p==r or r in p.parents
def no_links(p):
 for x in [p,*p.parents]:
  if x.exists() and (x.is_symlink() or getattr(x.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024)):
   raise ExportError('Link/junction path is not allowed')
def relative(s):
 if not isinstance(s,str) or '\\' in s or ':' in s or '\0' in s: raise ExportError('Invalid relative path')
 p=PurePosixPath(s)
 if p.is_absolute() or not p.parts or any(x in ('','..','.') for x in s.split('/')):raise ExportError('Escaping or noncanonical relative path')
 if any(x.casefold() in BLOCKED for x in p.parts):raise ExportError('Protected path category')
 if p.name.casefold().endswith('.local.json'):raise ExportError('Local configuration is not release content')
 if any(x.endswith((' ','.')) or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',x) for x in p.parts):raise ExportError('Unsafe Windows path')
 if p.suffix.lower() not in ALLOWED and str(p) not in SPECIAL:raise ExportError('Unapproved file type')
 return p
def run(manifest_path,destination,report_path,apply=False):
 no_links(manifest_path);no_links(destination);no_links(report_path)
 manifest_path=manifest_path.resolve(strict=True);dst=destination.resolve(strict=True);report=report_path.resolve()
 m=json.loads(manifest_path.read_text(encoding='utf-8'));src=Path(m['payload_root']).resolve(strict=True);no_links(src)
 if m.get('schema')!='editing-pack-export/v1' or not m.get('files'):raise ExportError('Unsupported/empty manifest')
 if inside(dst,src) or inside(src,dst):raise ExportError('Source/destination overlap')
 if inside(report,dst) or inside(report,src) or inside(manifest_path,dst) or inside(manifest_path,src):raise ExportError('Manifest/report must remain outside payload and checkout')
 protected=[Path(x).resolve(strict=True) for x in m['protected_roots']]
 if not protected:raise ExportError('Source protection roots required')
 for p in protected:
  if inside(dst,p) or inside(p,dst):raise ExportError('Destination overlaps protected working source')
 if not (dst/'.git').is_dir() or (dst/'.git').is_symlink():raise ExportError('Destination must be an existing standalone checkout')
 def git(*args):return subprocess.check_output(['git','-C',str(dst),*args],stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0).decode().strip()
 if Path(git('rev-parse','--show-toplevel')).resolve()!=dst:raise ExportError('Destination is not exact repository root')
 if git('remote','get-url','origin')!=m['expected_origin']:raise ExportError('Unexpected destination origin')
 if not git('remote','get-url','--push','origin').startswith('disabled://'):raise ExportError('Destination pushing must remain disabled')
 if git('rev-parse','HEAD')!=m['baseline_commit']:raise ExportError('Destination baseline changed')
 # Existing contents must be exactly baseline or a complete prior identical export.
 expected_existing=m['baseline_files']; planned={};items=[]
 for name,h in expected_existing.items():
  relative(name)
  if not isinstance(h,str) or not re.fullmatch('[a-f0-9]{64}',h):raise ExportError('Invalid baseline hash')
 for entry in m['files']:
  q=relative(entry['destination']); key=str(q).casefold()
  if key in planned:raise ExportError('Duplicate destination')
  planned[key]=entry
  if entry['source']!=entry['destination']:raise ExportError('Payload must mirror exact destination paths')
  source=src/str(q); target=dst/str(q);no_links(source);no_links(target)
  if not source.is_file() or not inside(source.resolve(),src):raise ExportError('Source outside payload')
  b=source.read_bytes()
  if len(b)>2_000_000 or b'\0' in b or b.startswith((b'PK\x03\x04',b'\x1f\x8b')):raise ExportError('Binary/archive/oversize content')
  try:b.decode('utf-8')
  except UnicodeError as e:raise ExportError('Non-UTF8 content') from e
  if digest(source)!=entry['sha256']:raise ExportError('Payload hash mismatch')
  if target.exists() and (not target.is_file() or digest(target) not in {entry['sha256'],expected_existing.get(str(q))}):raise ExportError('Unexpected destination file content')
  items.append((source,target,entry,b))
 actual=[]
 for cur,dirs,files in os.walk(src,followlinks=False):
  for name in dirs: no_links(Path(cur)/name)
  for name in files: no_links(Path(cur)/name);actual.append((Path(cur)/name).relative_to(src).as_posix())
 if set(actual)!={x['destination'] for x in m['files']}:raise ExportError('Unknown or missing payload files')
 for cur,dirs,files in os.walk(dst,followlinks=False):
  dirs[:]=[x for x in dirs if not (Path(cur)==dst and x=='.git')]
  for name in dirs:no_links(Path(cur)/name)
  for name in files:
   p=Path(cur)/name;no_links(p);rel=p.relative_to(dst).as_posix()
   if rel not in expected_existing and rel.casefold() not in planned:raise ExportError('Unknown destination content')
 identity=hashlib.sha256(json.dumps(sorted((e['destination'],e['sha256']) for e in m['files']),separators=(',',':')).encode()).hexdigest()
 result={'schema':'editing-pack-export-report/v1','mode':'apply' if apply else 'dry-run','files':len(items),'inventory_sha256':identity,'inventory':[{k:e[k] for k in ('destination','sha256','bytes')} for _,_,e,_ in items],'publication_approved':False}
 # All validation finishes before destination writes. Interrupted writes can be
 # resumed only if files still equal baseline or manifested hashes.
 if apply:
  for source,target,entry,b in items:
   if digest(source)!=entry['sha256']:raise ExportError('Source changed after preflight')
   no_links(target);target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists() and digest(target)==entry['sha256']:continue
   if target.exists() and digest(target)!=expected_existing.get(entry['destination']):raise ExportError('Destination changed after preflight')
   with target.open('wb') as f:f.write(b)
  if any(digest(t)!=e['sha256'] for _,t,e,_ in items):raise ExportError('Export verification mismatch')
 report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 return {k:v for k,v in result.items() if k!='inventory'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True,type=Path);p.add_argument('--destination',required=True,type=Path);p.add_argument('--report',required=True,type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
 try: print(json.dumps(run(a.manifest,a.destination,a.report,a.apply)))
 except (ExportError,OSError,KeyError,json.JSONDecodeError,subprocess.CalledProcessError) as e:p.exit(2,'Export refused: '+str(e)+'\n')
if __name__=='__main__':main()
