"""MIT. Generated-input demonstrations; never production or human-approval evidence."""
from __future__ import annotations
import argparse
from array import array
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import runtime_paths as runtime


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write('\n')


def stage_studio(job, example):
    resources = runtime.studio_resources()
    root = runtime.root() / 'Editing_OS/Skills/studio-3d-objects/starter'
    copies = {'assets/three/three.module.js': resources['three_module'],
        'assets/three/three.core.js': resources['three_core'],
        'assets/three/addons/environments/RoomEnvironment.js': resources['room_environment'],
        'assets/js/gsap.min.js': resources['gsap_runtime'], 'assets/js/studio3d.js': root / 'studio3d.js',
        'assets/css/stage.css': root / 'stage.css',
        'assets/fonts/inter-regular.woff2': resources['inter_regular_font'],
        'assets/fonts/inter-bold.woff2': resources['inter_bold_font'],
        'compositions/scene.html': root / 'examples' / (example + '.html')}
    inventory = []
    for name, source in copies.items():
        dest = runtime.output(job / name, require_workspace=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        inventory.append({'file': name, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
    for label, package in [('three', resources['three_module'].parent.parent),
            ('gsap', resources['gsap_runtime'].parent.parent), ('inter', resources['inter_regular_font'].parent.parent)]:
        licenses = sorted(package.glob('LICENSE*'))
        if not licenses and label == 'gsap':
            notice = job / 'notices/GSAP.txt'
            notice.parent.mkdir(parents=True, exist_ok=True)
            notice.write_text('GSAP retains its embedded GreenSock copyright and custom Standard License. Terms: https://gsap.com/standard-license/. Not toolkit MIT.\n', encoding='utf-8')
            inventory.append({'file': 'notices/GSAP.txt', 'sha256': hashlib.sha256(notice.read_bytes()).hexdigest()})
        elif not licenses:
            raise ValueError('Missing required installed resource license: ' + label)
        for source in licenses:
            dest = job / 'notices' / (label + '-' + source.name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            inventory.append({'file': dest.relative_to(job).as_posix(), 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
    scene_id = 'draft-' + example
    html = '<!doctype html><html><head><meta charset="utf-8"><title>Synthetic 3D draft</title><script src="assets/js/gsap.min.js"></script>'
    html += '<script type="importmap">' + json.dumps({'imports': {'three': './assets/three/three.module.js',
        'three/addons/': './assets/three/addons/', 'studio3d': './assets/js/studio3d.js'}}) + '</script></head>'
    html += '<body style="margin:0"><div data-composition-id="synthetic-studio" data-width="1080" data-height="1920" data-duration="3" style="width:100%;height:100%;position:relative">'
    html += '<div id="' + scene_id + '" data-composition-id="' + scene_id + '" data-composition-src="compositions/scene.html" data-start="0" data-duration="3" data-track-index="1"></div></div>'
    html += '<script>window.__timelines=window.__timelines||{};window.__timelines["synthetic-studio"]=gsap.timeline({paused:true}).to({t:0},{t:3,duration:3,ease:"none"});</script></body></html>'
    (job / 'index.html').write_text(html, encoding='utf-8', newline='\n')
    write(job / 'runtime-assets.json', {'synthetic': True, 'production_authority': False, 'resources': inventory})


def run_command(args, cwd, log, timeout=600):
    process = subprocess.Popen(args, cwd=cwd, env=runtime.child_env(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', **runtime.child_kwargs())
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, **runtime.child_kwargs())
            else:
                process.kill()
        stdout, stderr = process.communicate()
        log.write_text(stdout + stderr, encoding='utf-8')
        raise ValueError('Owned demo process timed out; diagnostics retained')
    log.write_text(stdout + stderr, encoding='utf-8')
    if process.returncode:
        raise ValueError('Demo command failed; inspect ' + log.name)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    runtime.common_args(p)
    p.add_argument('kind', choices=['audio', 'style', 'studio'])
    p.add_argument('--job-name', required=True)
    p.add_argument('--allow-unapproved-draft-treatment', action='store_true')
    p.add_argument('--example', choices=['folder-cards-rise', 'cards-scatter-file-in', 'mat-loupe-stamp', 'monitor-timeline', 'tablet-over-footage'], default='folder-cards-rise')
    p.add_argument('--render', action='store_true')
    p.add_argument('--capture', choices=['software', 'hardware'], default='software')
    args = p.parse_args(argv)
    try:
        runtime.configure_args(args)
        if args.render and args.kind != 'studio':
            raise ValueError('--render is supported only for studio; audio/style produce analysis fixtures')
        if not args.allow_unapproved_draft_treatment:
            raise ValueError('Synthetic demonstrations require explicit --allow-unapproved-draft-treatment; this never grants publication authority')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', args.job_name) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])', args.job_name):
            raise ValueError('Use a safe ASCII job name')
        job = runtime.output(runtime.workspace_root() / 'jobs' / args.job_name, require_workspace=True)
        if job.exists():
            raise ValueError('Job exists; use a new name, no overwrite')
        if args.kind == 'style':
            inspector = load('example_style', Path(__file__).with_name('style_inspect.py'))
            if inspector.Image is None:
                raise ValueError('Install optional requirements-style.lock.txt first')
        if args.kind == 'studio':
            runtime.studio_resources()
        job.mkdir(parents=True)
        (job / 'evidence').mkdir()
        (job / 'cache').mkdir()
        write(job / 'fixture-status.json', {'synthetic': True, 'production_authority': False,
            'selected_by_human': False, 'publication_approved': False, 'kind': args.kind})
        if args.kind == 'audio':
            path = job / 'generated-pcm.wav'
            rate = 16000
            samples = array('h', (int(9000 * math.sin(2 * math.pi * (440 if i < rate else 880) * i / rate)) for i in range(rate * 2)))
            if sys.byteorder != 'little':
                samples.byteswap()
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(samples.tobytes())
            motion = load('example_audio', Path(__file__).with_name('audio_motion.py'))
            data = motion.analyze(path, fps='30000/1001')
            write(job / 'evidence/audio-motion.json', data)
        elif args.kind == 'style':
            image = inspector.Image.new('RGBA', (160, 100), '#101820')
            image.paste('#3DD6D0', (20, 20, 70, 80)); image.paste('#F7BA1E', (80, 20, 140, 80))
            path = job / 'generated-palette.png'; image.save(path)
            data = inspector.inspect_image(path, roi=[20, 20, 120, 60], subject=[20, 20, 50, 60])
            write(job / 'evidence/style-observations.json', {'synthetic': True, 'production_authority': False, 'images': [data]})
        else:
            stage_studio(job, args.example)
            if args.render:
                run_command(runtime.hyperframes_command(['check', '--json', '--at', '0.2,1.3,2.7']), job, job / 'cache/check.log')
                (job / 'exports').mkdir()
                output = job / 'exports/synthetic-3d-DRAFT.mp4'
                mode = '--no-browser-gpu' if args.capture == 'software' else '--browser-gpu'
                run_command(runtime.hyperframes_command(['render', '--quality', 'draft', mode, '--workers', '1', '--output', str(output)]), job, job / 'cache/render.log')
                quality = load('example_quality', runtime.root() / 'Editing_OS/Video Editing/Engines/Quality_engine/qa.py')
                report = quality.run_quality_audit(output, scan_scenes=False)
                write(job / 'evidence/quality-report.json', report)
                if not report['decode_integrity']['passed'] or report['ready']:
                    raise ValueError('Draft decode failed or missing publication authority unexpectedly passed')
        print(json.dumps({'job': str(job), 'synthetic': True, 'ready': False, 'publication_approved': False}))
        return 0
    except (OSError, ValueError) as exc:
        print('Draft demonstration failed: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
