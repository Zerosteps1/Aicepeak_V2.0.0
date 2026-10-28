"""Diagnose identity and avoid claiming remote readiness from local presence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(os.environ.get('FACTORY_CANDIDATE',Path(__file__).resolve().parents[3]))
sys.path.insert(0,str(ROOT/'tools/factory'))
import doctor


class DoctorBoundaries(unittest.TestCase):
    def test_actual_git_identity_rejects_wrong_origin_and_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            def git(*args):subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True)
            git('init','-q');git('remote','add','origin','git@github.com:Zerosteps1/Aicepeak_V2.0.0.git')
            self.assertTrue(doctor.repository_identity(root))
            nested=root/'nested';nested.mkdir()
            self.assertFalse(doctor.repository_identity(nested))
            git('remote','set-url','origin','https://credential-sentinel@example.invalid/other.git')
            self.assertFalse(doctor.repository_identity(root))

    def test_no_credentials_leak_and_local_presence_never_claims_live_acceptance(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'SENSITIVE_DO_NOT_PRINT','CONTEXT7_API_KEY':'SENSITIVE_DO_NOT_PRINT'}), \
             patch.object(doctor,'probe',return_value=True),patch.object(doctor.shutil,'which',return_value='/fixture/tool'), \
             patch.object(doctor,'repository_identity',return_value=True):
            result=doctor.inspect(ROOT,'codex')
        self.assertNotIn('SENSITIVE_DO_NOT_PRINT',json.dumps(result))
        self.assertEqual(result['factory']['live_status'],'unverified')
        self.assertEqual(result['product']['status'],'blocked')


    def test_reviewer_host_reports_presence_without_values_or_api_key_paths(self):
        secrets={'CODEX_ACCESS_TOKEN':'SENSITIVE_DO_NOT_PRINT','FACTORY_PUBLISHER_APP_PRIVATE_KEY':'SENSITIVE_DO_NOT_PRINT','CONTEXT7_API_KEY':'SENSITIVE_DO_NOT_PRINT','ANTHROPIC_API_KEY':'SENSITIVE_DO_NOT_PRINT'}
        with patch.dict(os.environ,secrets,clear=True), patch.object(doctor,'probe',return_value=False), \
             patch.object(doctor.shutil,'which',return_value='/fixture/tool'), patch.object(doctor,'repository_identity',return_value=True), \
             patch.object(doctor,'codex_version',return_value='codex-cli 0.164.0'):
            result=doctor.inspect(ROOT,'claude')
        checks={c['check']:c['status'] for c in result['factory']['local_prerequisites']}
        for name in ('reviewer_codex','reviewer_access_token','reviewer_publisher_key'):
            self.assertEqual(checks[name],'passed',name)
        self.assertNotIn('environment_OPENAI_API_KEY',checks)
        text=json.dumps(result)
        self.assertNotIn('SENSITIVE_DO_NOT_PRINT',text)
        self.assertNotIn('model-smoke',text)
        self.assertIn('local_review.py --smoke',text)

if __name__=='__main__':unittest.main()
