import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import doctor
import engine as e
import subprocess

class DoctorTests(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(doctor.summarize([{'status':'ok','elapsed':.3}]*3)['status'],'ok')
        self.assertEqual(doctor.summarize([{'status':'ok','elapsed':5}]*3)['status'],'warning')
        self.assertEqual(doctor.summarize([{'status':'timeout','elapsed':10}])['status'],'failed')
    def test_timeout(self):
        with patch('doctor.subprocess.run',side_effect=subprocess.TimeoutExpired('x',1)):
            self.assertEqual(doctor.probe('example.com',1)['status'],'timeout')
    def test_only_configured_hosts_no_key_required(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'ROOT',Path(tmp)):
            root=Path(tmp);(root/'model').mkdir();(root/'websearch').mkdir()
            (root/'model/ds.txt').write_text(json.dumps({'url':'https://api.example.com/v1/chat','api_key':''}))
            a=SimpleNamespace(model='ds',websearch=None)
            self.assertEqual(doctor.hosts_for(a,{'websearch':None,'allow_http_endpoints':False}),['api.example.com'])
    def test_parameter_mapping(self):
        m={'extra_body':{'thinking':{'type':'disabled'},'reasoning_effort':'high'},'thinking':'enabled','reasoning_effort':'auto','temperature':1,'top_p':1}
        b=e.model_body(m)
        self.assertNotIn('reasoning_effort',b);self.assertEqual(b['thinking'],{'type':'enabled'})
        b=e.model_body(m,{'thinking':'auto','temperature':.4,'top_p':None})
        self.assertNotIn('thinking',b);self.assertNotIn('top_p',b);self.assertEqual(b['temperature'],.4)
    def test_invalid_parameters(self):
        for d in [{'temperature':True},{'temperature':float('nan')},{'top_p':2},{'thinking':'yes'}]:
            with self.assertRaises(e.Failure):e.validate_parameters(d)
