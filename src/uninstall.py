"""Conservative uninstall; never delete source/user data/system packages."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def uninstall(root, candidates):
    root = root.resolve()
    descriptors=[]
    try:
        # Acquire all existing management and running locks before making changes.
        # Caller must stop new invocations; this is not an OS-wide lifecycle transaction.
        for folder in ('locks','running'):
            directory=root/folder
            if directory.is_symlink():raise ValueError('Refusing symlinked lock directory')
            if not directory.exists():continue
            for path in sorted(directory.glob('*.lock')):
                fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
                descriptors.append(fd)
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    print('[uninstall=failed code=SESSION_BUSY] Stop active tasks/management operations first.',file=sys.stderr)
                    return 3
        env=root/'.venv'
        if env.is_symlink():raise ValueError('Refusing symlinked .venv')
        if env.exists() and not env.is_dir():raise ValueError('.venv is not a directory')
        # Exact launcher bytes include its destination. A marker alone is NOT ownership proof.
        line=subprocess.check_output(['bash','-c','printf \'exec %q "$@"\\n\' "$1"','bash',str(root/'batchcode')])
        expected=b'#!/bin/bash\n# batchcode-managed-launcher-v1\n'+line
        owned=[]
        for path in dict.fromkeys(candidates):
            if path.is_symlink() or not path.is_file():continue
            if path.stat().st_size>16384:continue
            if path.read_bytes()==expected:owned.append(path)
        for path in owned:
            if not os.access(path.parent,os.W_OK):raise PermissionError('No permission to remove launcher')
        for path in owned:
            path.unlink()
            print(f'[uninstall] removed launcher: {path}')
        if env.exists():
            shutil.rmtree(env)
            print('[uninstall] removed private .venv')
        print('[uninstall=done] Source, config, API keys, sessions, logs and artifacts retained.')
        print('Run bash install.sh to reinstall. Shells caching the old command may need hash -r.')
        return 0
    except (OSError,ValueError,subprocess.SubprocessError):
        print('[uninstall=failed] Could not complete removal. Check permissions and directory structure; partial removal is possible.',file=sys.stderr)
        return 2
    finally:
        for fd in descriptors:os.close(fd)

if __name__=='__main__':
    candidates=[Path('/usr/local/bin/batchcode'),Path.home()/'.local/bin/batchcode']
    candidates += [Path(p)/'batchcode' for p in os.environ.get('PATH','').split(os.pathsep) if p and Path(p).is_absolute()]
    sys.exit(uninstall(ROOT,candidates))
