"""MIT. Inspect public source files, syntax and local Markdown links without running them."""
from __future__ import annotations
import ast,json,os,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BLOCKED={".venv","venv","node_modules","projects","videos","jobs","inputs","outputs","exports","renders","workspace","workspaces","dependencies","cache",".cache","logs",".claude",".codex",".idea",".vscode",".hyperframes","__pycache__"}
MEDIA={".mp4",".mov",".mkv",".webm",".mp3",".wav",".m4a",".flac",".png",".jpg",".jpeg",".webp",".woff",".woff2",".ttf",".otf",".zip",".7z",".gz",".pyc",".pem",".key",".p12"}
def linked(p):
 return p.is_symlink() or bool(getattr(p.lstat(),"st_file_attributes",0)&0x400)
def public_paths(errors):
 for base,dirs,names in os.walk(ROOT,followlinks=False):
  base=Path(base)
  for name in list(dirs):
   p=base/name; rel=p.relative_to(ROOT)
   if base==ROOT and name==".git":dirs.remove(name);continue
   if linked(p) or name.casefold() in BLOCKED or name.casefold()==".git":
    errors.append(str(rel)+": excluded/link directory");dirs.remove(name)
  for name in names:yield base/name
def main():
 errors=[]; files=0; links=0
 for p in public_paths(errors):
  rel=p.relative_to(ROOT); parts=rel.parts
  if parts[0]=='.git':continue
  if linked(p):errors.append(str(rel)+': link/junction');continue
  if any(x.casefold() in BLOCKED or x.casefold()=='.git' for x in parts):errors.append(str(rel)+': excluded path');continue
  if not p.is_file():continue
  files+=1
  if p.suffix.casefold() in MEDIA or p.name.casefold().endswith('.local.json') or (p.name.startswith('.env') and p.name!='.env.example'):errors.append(str(rel)+': local/binary material');continue
  try:
   data=p.read_bytes()
   if len(data)>2_000_000 or b'\x00' in data:raise ValueError('binary or oversized file')
   text=data.decode('utf-8')
   if p.suffix=='.json':json.loads(text)
   if p.suffix=='.py':ast.parse(text)
   if p.suffix=='.md':
    for target in re.findall(r'\[[^\]]*\]\(([^\n]*?)\)',text):
     target=target.strip().strip('<>')
     if target.startswith(('https:','http:','mailto:','#')):continue
     if not (p.parent/target.split('#')[0]).exists():errors.append(str(rel)+': broken local link '+target)
     links+=1
  except (ValueError,SyntaxError,OSError) as exc:errors.append(str(rel)+': '+str(exc))
 print(json.dumps({'files':files,'local_links':links,'passed':not errors,'errors':errors},indent=2))
 return 1 if errors else 0
if __name__=='__main__':sys.exit(main())
