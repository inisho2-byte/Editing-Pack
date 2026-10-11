"""Local HyperFrames project launcher. Project files remain the source of truth."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import urllib.request
import webbrowser
from datetime import datetime, timezone


import sys as _runtime_sys
for _parent in Path(__file__).resolve().parents:
    if (_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_parent)); break
import runtime_paths as runtime

VIDEOS = STATE = None
ICON = Path(__file__).with_name('hyperframes.ico')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
OWNED = []
OWNED_LOCK = threading.Lock()
CLOSING = False


def stop_owned():
    global CLOSING
    with OWNED_LOCK:
        CLOSING = True
        children = list(OWNED)
        OWNED.clear()
    for child, log in children:
        if child.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **runtime.child_kwargs())
            else:
                os.killpg(child.pid, __import__('signal').SIGTERM)
            child.wait(timeout=15)
        log.close()


def projects() -> list[dict]:
    """Discover saved projects without traversing media, dependencies or drafts."""
    found = []
    excluded = {'node_modules', '.git', '.hyperframes', '.media', 'assets',
                'public', 'public-overlay', 'check', 'proto', 'piptest',
                'renders', 'evidence', 'graphics'}
    for current, dirs, files in os.walk(VIDEOS):
        dirs[:] = [d for d in dirs if d not in excluded and not d.startswith('.') and not (Path(current)/d).is_symlink() and not getattr(Path(current)/d, 'is_junction', lambda: False)() and runtime.contains(VIDEOS.resolve(), (Path(current)/d).resolve())]
        folder = Path(current)
        if 'index.html' not in files:
            continue
        if not ({'hyperframes.json', 'package.json'} & set(files)):
            continue
        source = (folder / 'index.html').read_text(encoding='utf-8-sig')
        if 'data-composition-id=' not in source:
            continue
        relative = folder.relative_to(VIDEOS).as_posix()
        label = folder.relative_to(VIDEOS).parts[0]
        found.append({'id': relative, 'name': label, 'path': str(folder)})
    return sorted(found, key=lambda item: item['name'].casefold())


def read_state() -> dict:
    try:
        value = json.loads(STATE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(value: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(STATE)


def command_for(project: dict) -> list[str]:
    path = runtime.output(project['path'], require_workspace=True)
    return runtime.hyperframes_command(['preview', str(path), '--foreground', '--no-open', '--port', '3100'])


def launch(project: dict, browser: bool = True, remember: bool = True) -> dict:
    import socket
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', 3100))
        except OSError: raise RuntimeError('Port 3100 is occupied. Close its owning session before opening this preview.')
    cache = runtime.output(runtime.workspace_root() / 'cache', require_workspace=True)
    cache.mkdir(parents=True, exist_ok=True)
    log = (cache / ('preview-' + str(os.getpid()) + '.log')).open('a', encoding='utf-8')
    with OWNED_LOCK:
        if CLOSING:
            log.close()
            raise RuntimeError('Launcher session is closing')
        child = subprocess.Popen(command_for(project), cwd=project['path'], env=runtime.child_env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != 'nt', **runtime.child_kwargs())
        OWNED.append((child, log))
    session = {'pid': child.pid, 'owner_pid': os.getpid(), 'project': project['path'], 'started_at': datetime.now(timezone.utc).isoformat(), 'studioUrl': 'http://127.0.0.1:3100', 'session_owned': True}
    (cache / 'preview-owner.json').write_text(json.dumps(session, indent=2), encoding='utf-8')
    if remember:
        state = read_state(); state.update(last_project=project['id'], last_opened=session['started_at']); save_state(state)
    # A browser tab is optional; the preview process is always owned by this launcher.
    if browser: webbrowser.open(session['studioUrl'])
    return session



class Library:
    def __init__(self, root, auto_resume: bool = True):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.items = root, projects()
        root.title('HyperFrames')
        root.geometry('600x390')
        root.minsize(500, 350)
        if ICON.exists():
            root.iconbitmap(str(ICON))
        style = ttk.Style(root)
        style.theme_use('vista' if 'vista' in style.theme_names() else 'clam')
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='HyperFrames', font=('Segoe UI', 23, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Your saved video projects', font=('Segoe UI', 11)).pack(anchor='w', pady=(4, 18))
        self.listbox = tk.Listbox(frame, font=('Segoe UI', 11), height=5, activestyle='none',
                                 selectbackground='#1864ab', borderwidth=1, exportselection=False)
        self.listbox.pack(fill='both', expand=True)
        for project in self.items:
            self.listbox.insert('end', project['name'])
        state = read_state()
        selected = next((i for i, p in enumerate(self.items) if p['id'] == state.get('last_project')), 0)
        if self.items:
            self.listbox.selection_set(selected)
        self.status = tk.StringVar(value='Choose a project to open its timeline in Studio.')
        ttk.Label(frame, textvariable=self.status, wraplength=535).pack(anchor='w', pady=(12, 6))
        self.resume = tk.BooleanVar(value=state.get('auto_resume', True))
        ttk.Checkbutton(frame, text='Reopen my last project when I launch', variable=self.resume,
                        command=self.preference).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(16, 0))
        self.button = ttk.Button(buttons, text='Open Studio', command=self.open)
        self.button.pack(side='right')
        ttk.Button(buttons, text='Open videos folder', command=lambda: os.startfile(VIDEOS)).pack(side='left')
        self.listbox.bind('<Double-Button-1>', lambda event: self.open())
        root.bind('<Return>', lambda event: self.open())
        if not self.items:
            self.status.set('No saved HyperFrames projects found in your videos folder.')
            self.button.state(['disabled'])
        elif auto_resume and self.resume.get() and any(p['id'] == state.get('last_project') for p in self.items):
            root.after(200, self.open)

    def preference(self):
        state = read_state()
        state['auto_resume'] = self.resume.get()
        save_state(state)

    def open(self):
        if 'disabled' in self.button.state():
            return
        selected = self.listbox.curselection()
        if not selected:
            return
        project = self.items[selected[0]]
        self.button.state(['disabled'])
        self.status.set('Opening ' + project['name'] + '...')
        threading.Thread(target=self.worker, args=(project,), daemon=True).start()

    def worker(self, project):
        try:
            launch(project)
            self.root.after(0, lambda: self.finish(None))
        except Exception as error:
            message = str(error)
            self.root.after(0, lambda: self.finish(message))

    def finish(self, error):
        from tkinter import messagebox
        self.button.state(['!disabled'])
        if error:
            self.status.set('Studio could not open. Your project files are unchanged.')
            messagebox.showerror('HyperFrames', error, parent=self.root)
        else:
            self.status.set('Studio is open. Choose another project here whenever you need it.')
            self.root.iconify()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--open', dest='project_id')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-remember', action='store_true')
    parser.add_argument('--ui-check', action='store_true')
    parser.add_argument('--preview-check', action='store_true', help='Bounded startup/shutdown smoke check; use --open')
    runtime.common_args(parser)
    args = parser.parse_args()
    runtime.configure_args(args)
    global VIDEOS, STATE
    workspace = runtime.workspace_root()
    VIDEOS = workspace / 'jobs'
    STATE = workspace / 'cache/hyperframes-launcher-state.json'
    if args.list:
        print(json.dumps(projects(), indent=2))
    elif args.project_id:
        project = next((p for p in projects() if p['id'] == args.project_id), None)
        if not project:
            parser.error('Project not found. Use --list to see saved project IDs.')
        print(json.dumps(launch(project, not args.no_browser, not args.no_remember), indent=2), flush=True)
        if args.preview_check:
            import time
            deadline = time.monotonic() + 45
            while True:
                if OWNED[-1][0].poll() is not None: raise RuntimeError('Preview exited; inspect workspace/cache log')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:3100', timeout=2) as response:
                        if response.status == 200: break
                except OSError:
                    if time.monotonic() >= deadline: raise RuntimeError('Preview readiness timed out; inspect workspace/cache log')
                    time.sleep(.2)
            print(json.dumps({'preview_ready': True, 'publication_approval': False}), flush=True)
        else:
            OWNED[-1][0].wait()
    else:
        import tkinter as tk
        root = tk.Tk()
        if args.ui_check:
            root.withdraw()
        library = Library(root, auto_resume=not args.ui_check)
        if args.ui_check:
            root.update()
            assert library.listbox.size() == len(projects())
            print(json.dumps({'ui_ok': True, 'projects': library.listbox.size()}))
            root.destroy()
        else:
            root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        stop_owned()
