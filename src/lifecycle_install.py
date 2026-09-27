"""Hold lifecycle lock while bash creates/rebuilds the local runtime."""
import os,subprocess,sys
import common as c
if __name__=='__main__':
    try:
        c.init()
        with c.lock(c.ROOT/'locks/lifecycle.lock') as fd:
            env=dict(os.environ,BATCHCODE_INSTALL_LOCKED='1',BATCHCODE_INSTALL_SELF_CHECK='1')
            sys.exit(subprocess.call(['bash',str(c.ROOT/'install.sh'),*sys.argv[1:]],env=env,pass_fds=(fd,)))
    except c.Failure as ex:
        print('[install=failed] '+ex.text,file=sys.stderr);sys.exit(ex.exit_code)
