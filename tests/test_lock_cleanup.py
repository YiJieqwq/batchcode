"""Safe retirement of per-session lock inodes, including delayed openers and redo."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import common as c
import storage as st
import lock_cleanup

SRC=Path(__file__).resolve().parents[1]/'src'

class LockCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bc-lock-test-')
        self.root=Path(self.tmp.name)/'app';self.root.mkdir()
        self.patch=patch.object(c,'ROOT',self.root);self.patch.start();c.init()
        self.sid=st.add('one',{})
        self.procs=[]
    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:p.kill()
            p.communicate(timeout=5)
        self.patch.stop();self.tmp.cleanup()
    def files(self,sid=None):
        return [self.root/d/((sid or self.sid)+'.lock') for d in ('locks','running')]
    def prime(self,sid=None):
        sid=sid or self.sid
        with st.session_locked(sid),st.running_locked(sid):pass
        for path in self.files(sid):self.assertTrue(path.exists())
    def orphan(self,hexchar='a'):
        sid='s_'+hexchar*32
        self.assertNotEqual(sid,self.sid)
        for path in self.files(sid):path.touch(mode=0o600)
        return sid
    def cleanup(self):
        with c.lock(self.root/'locks/lifecycle.lock'):
            return st.cleanup_orphan_locks()
    def child(self,body,pass_fds=()):
        prefix=f"import sys,json\nfrom pathlib import Path\nsys.path.insert(0,{str(SRC)!r})\nimport common as c, storage as st\nc.ROOT=Path({str(self.root)!r})\nsid={self.sid!r}\n"
        p=subprocess.Popen([sys.executable,'-c',prefix+body],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,pass_fds=pass_fds)
        self.procs.append(p)
        ready,_,_=select.select([p.stdout],[],[],10)
        self.assertTrue(ready,'child never reached rendezvous')
        self.assertEqual(p.stdout.readline().strip(),'READY')
        return p
    def release(self,p):
        out,err=p.communicate('go\n',timeout=10)
        self.assertEqual(p.returncode,0,err)
        return out.strip()

    def test_01_unused_delete_never_creates_per_session_locks(self):
        self.assertEqual(st.delete_all(self.sid),'one')
        self.assertTrue(all(not p.exists() for p in self.files()))
        self.assertFalse(st.spath(self.sid).exists())

    def test_02_delete_retires_pair_keeps_artifacts_and_globals(self):
        self.prime()
        artifact=self.root/'sub_workspace'/self.sid/'report.md';artifact.parent.mkdir();artifact.write_text('KEEP')
        for name in ('profiles.lock','lifecycle.lock'):
            with c.lock(self.root/'locks'/name):pass
        global_inodes={p:p.stat().st_ino for p in (self.root/'locks').glob('*.lock') if not p.name.startswith('s_')}
        self.assertEqual(st.delete_all(self.sid),'one')
        self.assertEqual(artifact.read_text(),'KEEP')
        self.assertTrue(all(not p.exists() for p in self.files()))
        for path,ino in global_inodes.items():self.assertEqual(path.stat().st_ino,ino)

    def test_03_busy_management_is_nondestructive(self):
        self.prime();index=(self.root/'session_index.json').read_bytes()
        with st.session_locked(self.sid):
            with self.assertRaises(c.Failure) as ex:st.delete_all(self.sid)
            self.assertEqual(ex.exception.exit_code,3)
        self.assertEqual(index,(self.root/'session_index.json').read_bytes())
        self.assertTrue(all(p.exists() for p in self.files()))
        self.assertFalse((self.root/'state/index-transaction.json').exists())

    def test_04_busy_running_alone_also_blocks_delete(self):
        self.prime()
        with st.running_locked(self.sid):
            with self.assertRaises(c.Failure) as ex:st.delete_all(self.sid)
            self.assertEqual(ex.exception.exit_code,3)
        self.assertTrue(st.spath(self.sid).exists())
        self.assertTrue(all(p.exists() for p in self.files()))
        self.assertFalse((self.root/'state/index-transaction.json').exists())

    def test_05_stale_session_opener_never_recreates_deleted_lock(self):
        self.prime()
        p=self.child("st.resolve('one')\nprint('READY',flush=True)\nsys.stdin.readline()\ntry:\n with st.session_locked(sid):print('UNEXPECTED')\nexcept c.Failure as e:print(e.code)\n")
        st.delete_all(self.sid)
        self.assertEqual(self.release(p),'NOT_FOUND')
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_06_stale_running_opener_never_recreates_deleted_lock(self):
        p=self.child("st.resolve('one')\nprint('READY',flush=True)\nsys.stdin.readline()\ntry:\n with st.running_locked(sid):print('UNEXPECTED')\nexcept c.Failure as e:print(e.code)\n")
        st.delete_all(self.sid)
        self.assertEqual(self.release(p),'NOT_FOUND')
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_07_list_and_probe_do_not_create_locks(self):
        for _ in range(3):
            self.assertEqual(st.list_sessions(),[('one',self.sid,False)])
            self.assertFalse(st.active(self.sid))
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_08_running_probe_and_stale_snapshot(self):
        with st.running_locked(self.sid):
            self.assertTrue(st.active(self.sid))
            self.assertEqual(st.list_sessions(),[('one',self.sid,True)])
        sid,name=st.resolve('one')
        st.delete_all(sid)
        self.assertFalse(st.active(sid))
        self.assertEqual(st.list_sessions(),[])
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_09_recreated_name_does_not_revive_old_id(self):
        self.prime();st.delete_all(self.sid)
        new=st.add('one',{});self.assertNotEqual(new,self.sid)
        with self.assertRaises(c.Failure):
            with st.session_locked(self.sid):pass
        with st.session_locked(new):pass
        self.assertTrue(all(not f.exists() for f in self.files()))
        self.assertEqual(st.resolve('one')[0],new)

    def test_10_delete_is_idempotent_even_after_locks_removed(self):
        self.prime();st.delete_all(self.sid)
        self.assertIsNone(st.delete_all(self.sid))
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_11_delete_failure_cleanup_is_redoable(self):
        self.prime();real=st._unlink_locked;count=0
        def fail_second(path,fd):
            nonlocal count
            count+=1
            if count==2:raise PermissionError('simulated cleanup interruption')
            return real(path,fd)
        with patch.object(st,'_unlink_locked',side_effect=fail_second):
            with self.assertRaises(PermissionError):st.delete_all(self.sid)
        self.assertFalse(st.spath(self.sid).exists())
        self.assertFalse(self.files()[0].exists());self.assertTrue(self.files()[1].exists())
        self.assertTrue((self.root/'state/index-transaction.json').exists())
        self.assertEqual(st.list_sessions(),[])
        self.assertTrue(all(not f.exists() for f in self.files()))
        self.assertFalse((self.root/'state/index-transaction.json').exists())

    def test_12_journal_recovery_at_each_deletion_stage(self):
        for stage in range(4):
            with self.subTest(stage=stage):
                sid=st.add('stage'+str(stage),{});self.prime(sid)
                with st.index_locked() as idx:
                    after=copy.deepcopy(idx);after['names'].pop('stage'+str(stage))
                    c.atomic(self.root/'state/index-transaction.json',{'op':'delete','id':sid,'index':after})
                    if stage>=1:shutil.rmtree(st.spath(sid))
                    if stage>=2:c.atomic(self.root/'session_index.json',after)
                    if stage>=3:self.files(sid)[0].unlink()
                with self.assertRaises(c.Failure):st.resolve(sid)
                self.assertFalse(st.spath(sid).exists())
                self.assertTrue(all(not f.exists() for f in self.files(sid)))
                self.assertFalse((self.root/'state/index-transaction.json').exists())

    def test_13_recovery_does_not_delete_busy_inode(self):
        self.prime()
        with st.index_locked() as idx:
            idx['names'].pop('one')
            c.atomic(self.root/'state/index-transaction.json',{'op':'delete','id':self.sid,'index':idx})
        with c.lock(self.files()[0]):
            with self.assertRaises(c.Failure) as ex:st.list_sessions()
            self.assertEqual(ex.exception.exit_code,3)
            self.assertTrue(st.spath(self.sid).exists())
        self.assertEqual(st.list_sessions(),[])
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_14_other_session_operation_continues_during_delete(self):
        other=st.add('other',{})
        with st.session_locked(other),st.running_locked(other):
            self.prime();self.assertEqual(st.delete_all(self.sid),'one')
            self.assertTrue(st.active(other))
        self.assertEqual(st.resolve('other')[0],other)

    def test_15_installer_only_orphans_and_no_artifact_deletion(self):
        self.prime();orphan=self.orphan()
        artifact=self.root/'sub_workspace'/orphan/'report';artifact.parent.mkdir();artifact.write_text('KEEP')
        count,skipped=self.cleanup()
        self.assertEqual((count,skipped),(2,[]));self.assertEqual(artifact.read_text(),'KEEP')
        self.assertTrue(all(f.exists() for f in self.files()))
        self.assertTrue(all(not f.exists() for f in self.files(orphan)))
        self.assertEqual(self.cleanup(),(0,[]))

    def test_16_unindexed_session_directory_is_not_orphan_evidence(self):
        sid=self.orphan();(self.root/'session'/sid).mkdir()
        self.assertEqual(self.cleanup(),(0,[]))
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_17_orphan_cleanup_skips_busy_pair(self):
        sid=self.orphan()
        with c.lock(self.files(sid)[1]):
            count,skipped=self.cleanup()
        self.assertEqual(count,0);self.assertEqual(skipped,[{'sessionid':sid,'reason':'BUSY'}])
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_18_symlink_and_nonempty_locks_preserved(self):
        for marker in ('symlink','nonempty','directory','fifo','hardlink'):
            with self.subTest(marker=marker):
                sid='s_'+('abcdef1234'[len(marker)%10])*32
                a,b=self.files(sid)
                for f in (a,b):
                    if f.is_dir():shutil.rmtree(f)
                    elif os.path.lexists(f):f.unlink()
                b.touch()
                outside=self.root/(marker+'.txt');outside.write_text('KEEP' if marker!='hardlink' else '')
                if marker=='symlink':a.symlink_to(outside)
                elif marker=='nonempty':a.write_text('KEEP')
                elif marker=='directory':a.mkdir()
                elif marker=='fifo':os.mkfifo(a)
                else:a.hardlink_to(outside)
                count,skipped=self.cleanup()
                self.assertEqual(count,0);self.assertTrue(any(x['sessionid']==sid and x['reason']=='UNSAFE_LOCK' for x in skipped))
                self.assertTrue(os.path.lexists(a));self.assertTrue(b.exists())
                self.assertEqual(outside.read_text(),'KEEP' if marker!='hardlink' else '')
                if a.is_dir():a.rmdir()
                else:a.unlink()
                b.unlink()

    def test_19_non_id_and_global_lock_files_are_untouched(self):
        paths=[self.root/'locks'/name for name in ('index.lock','lifecycle.lock','profiles.lock','notes.lock','01.lock','s_wrong.lock')]
        for p in paths:
            if not p.exists():p.touch()
        with c.lock(self.root/'locks/lifecycle.lock'):
            inodes={p:p.stat().st_ino for p in paths}
            count,skipped=st.cleanup_orphan_locks()
        self.assertEqual((count,skipped),(0,[]))
        self.assertEqual({p:p.stat().st_ino for p in paths},inodes)

    def test_20_corrupt_index_does_not_trigger_orphan_purge(self):
        sid=self.orphan();(self.root/'session_index.json').write_text('{bad')
        with self.assertRaises(c.Failure):self.cleanup()
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_21_direct_maintenance_refuses_active_lifecycle(self):
        sid=self.orphan()
        with patch.dict(os.environ,{},clear=True),c.lock(self.root/'locks/lifecycle.lock',shared=True):
            with self.assertRaises(c.Failure) as ex:lock_cleanup.run()
            self.assertEqual(ex.exception.exit_code,3)
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_22_unlink_verifies_inode(self):
        p=self.files()[0];p.touch()
        with c.lock(p) as fd:
            p.unlink();p.write_text('replacement')
            with self.assertRaises(c.Failure) as ex:st._unlink_locked(p,fd)
            self.assertEqual(ex.exception.code,'UNSAFE_LOCK')
        self.assertEqual(p.read_text(),'replacement')

    def test_23_nonregular_lock_is_not_taken(self):
        p=self.root/'locks/fifo.lock';os.mkfifo(p)
        with self.assertRaises(c.Failure) as ex:
            with c.lock(p):pass
        self.assertEqual(ex.exception.code,'UNSAFE_LOCK')

    def test_24_inherited_management_fd_blocks_delete_until_child_exits(self):
        with st.session_locked(self.sid) as (s,name,fd):
            p=self.child("print('READY',flush=True)\nsys.stdin.readline()\n",pass_fds=(fd,))
        # Parent closed its descriptor, child still owns the same lock open-file description.
        with self.assertRaises(c.Failure) as ex:st.delete_all(self.sid)
        self.assertEqual(ex.exception.exit_code,3)
        self.release(p)
        self.assertEqual(st.delete_all(self.sid),'one')
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_25_stale_list_process_never_recreates_running_file(self):
        p=self.child("old=st.list_sessions()\nprint('READY',flush=True)\nsys.stdin.readline()\nprint(st.active(old[0][1]))\n")
        st.delete_all(self.sid)
        self.assertEqual(self.release(p),'False')
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_26_existing_busy_worker_rejects_delete_in_another_process(self):
        p=self.child("with st.session_locked(sid),st.running_locked(sid):\n print('READY',flush=True)\n sys.stdin.readline()\n")
        with self.assertRaises(c.Failure) as ex:st.delete_all(self.sid)
        self.assertEqual(ex.exception.exit_code,3);self.assertTrue(st.spath(self.sid).exists())
        self.release(p);st.delete_all(self.sid)
        self.assertTrue(all(not f.exists() for f in self.files()))

    def test_27_orphan_cleanup_preserves_session_symlink(self):
        sid=self.orphan();(self.root/'session'/sid).symlink_to(self.root/'absent')
        self.assertEqual(self.cleanup(),(0,[]))
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_28_unsafe_target_lock_refuses_whole_delete_before_journal(self):
        self.prime();self.files()[1].write_text('not a program lock')
        with self.assertRaises(c.Failure) as ex:st.delete_all(self.sid)
        self.assertEqual(ex.exception.code,'UNSAFE_LOCK')
        self.assertTrue(st.spath(self.sid).exists());self.assertEqual(st.resolve('one')[0],self.sid)
        self.assertFalse((self.root/'state/index-transaction.json').exists())
        self.assertTrue(all(f.exists() for f in self.files()))

    def test_29_permission_error_is_not_absence_for_cleanup(self):
        sid=self.orphan();path=self.root/'session'/sid;real=Path.lstat
        def denied(p,*args,**kwargs):
            if p==path:raise PermissionError('cannot determine session entry presence')
            return real(p,*args,**kwargs)
        with patch.object(Path,'lstat',denied):
            with self.assertRaises(PermissionError):self.cleanup()
        self.assertTrue(all(f.exists() for f in self.files(sid)))

    def test_30_permission_error_cannot_report_successful_delete(self):
        self.prime();path=st.spath(self.sid);real=Path.lstat
        before=(self.root/'session_index.json').read_bytes()
        def denied(p,*args,**kwargs):
            if p==path:raise PermissionError('cannot inspect session directory')
            return real(p,*args,**kwargs)
        with patch.object(Path,'lstat',denied):
            with self.assertRaises(PermissionError):st.delete_all(self.sid)
        self.assertEqual((self.root/'session_index.json').read_bytes(),before)
        self.assertTrue(path.exists());self.assertTrue(all(f.exists() for f in self.files()))
