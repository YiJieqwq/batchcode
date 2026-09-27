"""Install-only cleanup of a retired answer-length setting; never rewrite stored transcripts.

No runtime/CLI compatibility alias is registered. Run under the exclusive lifecycle lock.
Every touched file is backed up verbatim before the first replacement. Partial installation
failure is safe to retry: removal is idempotent and all other values are preserved.
"""
import copy
from pathlib import Path
import uuid
import common as c
from storage import ID_RE

# This literal exists only for upgrade cleanup, not as a supported config field.
RETIRED = 'summary_chars'


def cleanup():
    candidates=[]
    for folder in ('model','session','state'):
        if (c.ROOT/folder).is_symlink():
            raise c.Failure('UNSAFE_PATH','Refusing symlinked configuration/state directory',2)
    for p in sorted((c.ROOT/'model').glob('*.txt')):
        candidates.append((p,False))
    for folder in sorted((c.ROOT/'session').iterdir()):
        if not ID_RE.fullmatch(folder.name):continue
        if folder.is_symlink():
            raise c.Failure('UNSAFE_PATH','Refusing symlinked session directory during config cleanup',2)
        if not folder.is_dir():continue
        for name,journal in (('config.json',False),('.transaction.json',True)):
            if (folder/name).exists() or (folder/name).is_symlink():
                candidates.append((folder/name,journal))
    changes=[]
    for path,journal in candidates:
        if path.is_symlink():
            raise c.Failure('UNSAFE_PATH','Refusing symlinked configuration file',2)
        try:
            raw=path.read_bytes().decode('utf-8');obj=c.decode(raw)
        except (OSError,UnicodeError,ValueError):
            raise c.Failure('CONFIG_UPGRADE_FAILED','Cannot read configuration safely; no cleanup performed',2)
        if not isinstance(obj,dict):
            raise c.Failure('CONFIG_UPGRADE_FAILED','Expected an object in configuration file; no cleanup performed',2)
        content=obj.get('config.json') if journal else obj
        if journal and 'config.json' in obj and not isinstance(content,dict):
            raise c.Failure('CONFIG_UPGRADE_FAILED','Invalid pending configuration transaction',2)
        if not isinstance(content,dict) or RETIRED not in content:continue
        updated=copy.deepcopy(obj)
        (updated['config.json'] if journal else updated).pop(RETIRED)
        changes.append((path,raw,updated))
    if not changes:return 0,None
    backup=c.ROOT/'state'/('config-backup-'+uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    # Backups include credentials where present: state is private, tool-inaccessible,
    # excluded from packaging, and never printed or sent to providers.
    for path,raw,updated in changes:
        dest=backup/path.relative_to(c.ROOT);dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        c.atomic_text(dest,raw)
    for path,raw,updated in changes:c.atomic(path,updated)
    return len(changes),backup


if __name__=='__main__':
    try:
        count,backup=cleanup()
        if count:print(f'[install] cleaned retired answer-length settings in {count} config files; private originals: {backup}')
    except c.Failure as exc:
        import sys
        print('[install=failed] '+exc.text,file=sys.stderr);sys.exit(exc.exit_code)
    except OSError:
        import sys
        print('[install=failed] Config cleanup filesystem error; originals backed up before modification. Partial cleanup may have occurred; fix permissions/storage and rerun install.',file=sys.stderr)
        sys.exit(2)
