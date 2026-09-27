import contextlib
import fcntl
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uninstall import uninstall

class UninstallTests(unittest.TestCase):
    def setup_tree(self,tmp):
        root=Path(tmp)/'app space';root.mkdir()
        (root/'.venv').mkdir();(root/'.venv/file').write_text('test')
        (root/'config.json').write_text('KEEP')
        (root/'locks').mkdir();(root/'running').mkdir()
        own=Path(tmp)/'batchcode'
        line=subprocess.check_output(['bash','-c','printf \'exec %q "$@"\\n\' "$1"','bash',str(root/'batchcode')])
        own.write_bytes(b'#!/bin/bash\n# batchcode-managed-launcher-v1\n'+line)
        return root,own
    def test_remove_and_repeat_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            r,p=self.setup_tree(tmp)
            self.assertEqual(uninstall(r,[p]),0)
            self.assertFalse(p.exists());self.assertFalse((r/'.venv').exists())
            self.assertEqual((r/'config.json').read_text(),'KEEP')
            self.assertEqual(uninstall(r,[p]),0)
    def test_foreign_and_symlink_preserved(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            r,p=self.setup_tree(tmp);p.write_text('#!/bin/bash\n# batchcode-managed-launcher-v1\nexec /another/install/batchcode "$@"\n')
            link=Path(tmp)/'link';link.symlink_to(p)
            self.assertEqual(uninstall(r,[p,link]),0)
            self.assertTrue(p.exists());self.assertTrue(link.is_symlink())
    def test_busy_does_not_remove(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()):
            r,p=self.setup_tree(tmp)
            with open(r/'locks/01.lock','w') as f:
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertEqual(uninstall(r,[p]),3)
            self.assertTrue(p.exists());self.assertTrue((r/'.venv').exists())
    def test_venv_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()):
            r,p=self.setup_tree(tmp)
            import shutil
            shutil.rmtree(r/'.venv');outside=Path(tmp)/'outside';outside.mkdir();(r/'.venv').symlink_to(outside)
            self.assertEqual(uninstall(r,[p]),2);self.assertTrue(p.exists());self.assertTrue(outside.exists())
