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


if __name__=='__main__':unittest.main()
