#!/usr/bin/env python3
"""Install Vault into Codex and/or Claude Code user skill directories."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--target', choices=('codex', 'claude', 'both'), default='both')
    p.add_argument('--sync', action='store_true', help='Update files in an existing skill directory without removing private data')
    a = p.parse_args()
    home = Path.home()
    targets = []
    if a.target in ('codex', 'both'):
        targets.append(home / '.codex' / 'skills' / 'vault')
    if a.target in ('claude', 'both'):
        targets.append(home / '.claude' / 'skills' / 'vault')
    for dst in targets:
        if dst.exists() and not a.sync:
            raise SystemExit(f'Refusing to overwrite existing installation: {dst}')
    for dst in targets:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            for item in SOURCE.iterdir():
                if item.name in ('.venv','__pycache__') or item.name.endswith('.pyc'): continue
                target=dst/item.name
                if item.is_dir(): shutil.copytree(item,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.venv'))
                else: shutil.copy2(item,target)
        else:
            shutil.copytree(SOURCE, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.venv'))
        pyvenv = dst / '.venv'
        subprocess.run([sys.executable, '-m', 'venv', str(pyvenv)], check=True)
        exe = pyvenv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run([str(exe), '-m', 'pip', 'install', '-r', str(dst / 'requirements.txt')], check=True)
        print(f'Installed: {dst}')
    data = Path(os.environ.get('VAULT_DATA_HOME', home / '.local' / 'share' / 'vault'))
    data.mkdir(parents=True, exist_ok=True)
    for name in ('knowledge', 'cache', 'corrections'):
        (data / name).mkdir(exist_ok=True)
    print(f'Private data: {data.resolve()}')

if __name__ == '__main__':
    main()
