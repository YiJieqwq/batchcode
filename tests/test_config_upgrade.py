"""Retired configuration cleanup is install-only and cannot alter raw history."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import common as c
import configuration as conf
import config_upgrade as upgrade
import storage as st

class ConfigUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(c,'ROOT',Path(self.tmp.name));self.patch.start();c.init()
        self.profile=c.ROOT/'model'/'sample.txt'
        self.cfg={**copy.deepcopy(conf.DEFAULTS),'api_key':'private-fixture','summary_chars':200}
        self.profile.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2)+'\n')
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_backup_exact_and_preserve_other_fields(self):
        raw=self.profile.read_bytes()
        count,backup=upgrade.cleanup();self.assertEqual(count,1)
        self.assertEqual((backup/'model/sample.txt').read_bytes(),raw)
        expected=dict(self.cfg);expected.pop('summary_chars')
        self.assertEqual(c.load(self.profile),expected)
        self.assertEqual(self.profile.stat().st_mode&0o777,0o600)
    def test_idempotent_and_does_not_reformat_new_configs(self):
        upgrade.cleanup();raw=self.profile.read_bytes()
        count,backup=upgrade.cleanup();self.assertEqual((count,backup),(0,None))
        self.assertEqual(raw,self.profile.read_bytes())
    def test_context_info_unchanged(self):
        sid=st.add('one',{'summary_chars':15,'temperature':.4})
        folder=st.spath(sid)
        context=b'{"historic":"summary_chars and target_chars stay raw"}\n'
        (folder/'ctx.json').write_bytes(context);info=(folder/'info.json').read_bytes()
        count,backup=upgrade.cleanup();self.assertEqual(count,2)
        self.assertEqual(c.load(folder/'config.json'),{'temperature':.4})
        self.assertEqual((folder/'ctx.json').read_bytes(),context)
        self.assertEqual((folder/'info.json').read_bytes(),info)
    def test_pending_transaction_cannot_restore_removed_setting(self):
        sid=st.add('one',{'summary_chars':15})
        session=st.Session(sid)
        tx={'config.json':{'summary_chars':9,'temperature':.7},'ctx.json':session.ctx,'info.json':session.info}
        c.atomic(session.path/'.transaction.json',tx)
        count,_=upgrade.cleanup();self.assertEqual(count,3)
        recovered=st.Session(sid)
        self.assertEqual(recovered.conf,{'temperature':.7});self.assertEqual(recovered.ctx,tx['ctx.json'])
    def test_invalid_json_fails_before_any_config_rewrite(self):
        before=self.profile.read_bytes();(c.ROOT/'model'/'broken.txt').write_text('{bad')
        with self.assertRaises(c.Failure):upgrade.cleanup()
        self.assertEqual(before,self.profile.read_bytes());self.assertEqual(list((c.ROOT/'state').iterdir()),[])
    def test_symlink_not_followed(self):
        link=c.ROOT/'model'/'linked.txt';link.symlink_to(self.profile)
        before=self.profile.read_bytes()
        with self.assertRaises(c.Failure):upgrade.cleanup()
        self.assertEqual(before,self.profile.read_bytes())
    def test_runtime_schema_does_not_accept_removed_parameter(self):
        self.assertNotIn('summary_chars',conf.DEFAULTS)
        for session in (False,True):
            with self.assertRaises(c.Failure):conf.validate({'summary_chars':200},session)
    def test_only_top_level_config_key_removed(self):
        # Text merely mentioning the old term is untouched; do not recurse into arbitrary content.
        sid=st.add('one',{'extra_body':{'note':'summary_chars is historical text'},'summary_chars':None})
        upgrade.cleanup()
        self.assertEqual(c.load(st.spath(sid)/'config.json'),{'extra_body':{'note':'summary_chars is historical text'}})
