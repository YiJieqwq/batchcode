"""Installation maintenance, not a runtime GC command. No history or artifacts removed."""
import contextlib
import os
import sys
import common as c
import storage


def run():
    c.init()
    # Installer's system-Python supervisor already holds the exclusive lifecycle FD
    # across this child. Direct execution must acquire it itself, never race a run.
    guarded=os.environ.get('BATCHCODE_INSTALL_LOCKED')=='1'
    with (contextlib.nullcontext() if guarded else c.lock(c.ROOT/'locks/lifecycle.lock')):
        count,skipped=storage.cleanup_orphan_locks()
    if count:print(f'[install] removed {count} orphan session lock files; artifacts retained')
    if skipped:
        print(f'[install] skipped {len(skipped)} busy or unexpected orphan lock pairs; not removed',file=sys.stderr)
    return count,skipped


if __name__=='__main__':
    try:run()
    except c.Failure as ex:
        print('[install=failed] Lock cleanup: '+ex.text,file=sys.stderr);sys.exit(ex.exit_code)
    except OSError:
        print('[install=failed] Lock cleanup filesystem error; fix permissions/storage and retry. Partial cleanup may have occurred; no artifact directories were deleted.',file=sys.stderr)
        sys.exit(2)
