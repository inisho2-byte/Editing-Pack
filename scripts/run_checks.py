"""MIT. Run owned checks with external scratch and explicitly configured tools."""
from __future__ import annotations
import argparse,json,os,re,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Editing_OS'))
import runtime_paths as runtime
GROUPS=[('contracts','Editing_OS/Video Editing/Contracts',23),('adapter','Editing_OS/Video Editing/Engines/Orchestration_adapter',8),('captions','Editing_OS/Video Editing/Engines/Captions_engine',39),('editorial','Editing_OS/Video Editing/Engines/Video editing engine',37),('quality','Editing_OS/Video Editing/Engines/Quality_engine',29),('photo','Editing_OS/Photo editing/Engines/Ideogram4_engine',12),('workbench','Editing_OS/Tools/editing-workbench',17)]
def main():
 p=argparse.ArgumentParser(description=__doc__);runtime.common_args(p);p.add_argument('--graphics',action='store_true');p.add_argument('--style-analysis',action='store_true');p.add_argument('--3d-browser',dest='studio',action='store_true');a=p.parse_args()
 runtime.configure_args(a);root=runtime.root();w=runtime.workspace_root();runtime.tool('ffmpeg');runtime.tool('ffprobe')
 if a.graphics:runtime.hyperframes_command([]);[runtime.tool(x) for x in ('gsap_runtime','inter_regular_font','inter_bold_font')]
 if a.studio:runtime.studio_resources()
 scratch=runtime.output(w/'cache/checks',require_workspace=True);scratch.mkdir(parents=True,exist_ok=True)
 env=runtime.child_env();env.update(TEMP=str(scratch),TMP=str(scratch),TMPDIR=str(scratch));results=[]
 groups=[*GROUPS[:-1],('workbench','Editing_OS/Tools/editing-workbench',14),('inventory','Editing_OS/Tools/editing-workbench',3),('runtime','tests',19),('exporter','tests',10),('helper-boundaries','tests',6),('audio','Editing_OS/Tools/editing-workbench',9)]+([('style','Editing_OS/Tools/editing-workbench',12)] if a.style_analysis else [])+([('graphics','Editing_OS/Video Editing/Engines/Graphics_engine',29)] if a.graphics else [])+([('3d-browser','Editing_OS/Tools/editing-workbench',1)] if a.studio else [])
 patterns={'workbench':'test_workbench.py','inventory':'test_inventory.py','runtime':'test_runtime_paths.py','exporter':'test_exporter.py','helper-boundaries':'test_helper_boundaries.py','audio':'test_audio_motion.py','style':'test_style_inspect.py','3d-browser':'test_studio3d.py'}
 for name,folder,expected in groups:
  cmd=[sys.executable,'-B','test_engine.py'] if name=='captions' else [sys.executable,'-B','-m','unittest','discover','-s','tests' if name=='contracts' else '.', '-p',patterns.get(name,'test*.py'),'-v']
  r=subprocess.run(cmd,cwd=root/folder,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,**runtime.child_kwargs())
  output=r.stdout+r.stderr;(scratch/(name+'.log')).write_text(output,encoding='utf-8');m=re.search(r'Ran (\d+) tests?',output) if name!='captions' else re.search(r'(\d+)/39 passed',output)
  count=int(m.group(1)) if m else 0;skipped='skipped=' in output or '... skipped' in output
  passed=r.returncode==0 and count>0 and (count==expected if expected else True) and not skipped
  results.append({'group':name,'tests':count,'exit_code':r.returncode,'skipped':skipped,'passed':passed});print(json.dumps(results[-1]),flush=True)
 report={'schema':'editing-pack-checks/v1','passed':all(x['passed'] for x in results),'groups':results,'publication_approval':False,'profiles':{'core':True,'style-analysis':a.style_analysis,'graphics':a.graphics,'3d-browser':a.studio},'total_tests':sum(x['tests'] for x in results)};(scratch/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return 0 if report['passed'] else 1
if __name__=='__main__':
 try:raise SystemExit(main())
 except (ValueError,OSError,subprocess.TimeoutExpired) as exc:print('Setup/check failure: '+str(exc),file=sys.stderr);raise SystemExit(2)
