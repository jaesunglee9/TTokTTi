"""Actual Django views/models on disposable SQLite; external LLM is stubbed.
Run: python tests/report_pipeline/run.py
Does not load production settings or contact MySQL, Azure, Redis, or OpenAI.
"""
import ast
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from django.conf import settings
settings.configure(
 SECRET_KEY='isolated-report-test-only',DEBUG=False,USE_TZ=True,TIME_ZONE='UTC',
 DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}},
 INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','apps.user','apps.worksession','apps.check','apps.detect','apps.risk','apps.report'],
 AUTH_USER_MODEL='user.User',ROOT_URLCONF=__name__,MIDDLEWARE=[],
 REST_FRAMEWORK={'DEFAULT_AUTHENTICATION_CLASSES':['rest_framework_simplejwt.authentication.JWTAuthentication']},
 MIGRATION_MODULES={name:None for name in ['user','worksession','check','detect','risk','report']},
 ALLOWED_HOSTS=['testserver'],
)
import django
django.setup()
from django.urls import path,include
urlpatterns=[path('api/detect/',include('apps.detect.urls')),path('api/report/',include('apps.report.urls'))]
from django.test import TestCase
from django.test.utils import setup_databases,teardown_databases
from django.utils import timezone
from rest_framework.test import APIClient
from apps.user.models import User
from apps.worksession.models import Worksite,WorkSession
from apps.detect.models import RiskType,VideoLog
from apps.check.models import Compliance,Photo
from apps.report.models import PostWorkReport
from apps.report.services import build_input_package

class ReportPipelineTests(TestCase):
 def setUp(self):
  self.user=User.objects.create_user('fixture-worker',name='테스트 근로자',sex='M')
  site=Worksite.objects.create(name='격리 테스트 현장',address='synthetic test location')
  self.session=WorkSession.objects.create(worksite=site,name='테스트 작업',starts_at=timezone.now(),status='DONE',bodycam_video='fixture://bodycam.mp4')
  self.risk=RiskType.objects.create(code='TEST_BODY_RISK',name='테스트 위험',camera_type='BODY')
  self.client=APIClient();self.client.force_authenticate(self.user)
 def payload(self):
  return {'worksession_id':self.session.id,'risk_type_id':self.risk.id,'video_path':'fixture://evidence.mp4'}
 def test_risk_logs_report_snapshot_versions_and_latest(self):
  for _ in range(3):
   response=self.client.post('/api/detect/bodycam/',self.payload(),format='json')
   self.assertEqual(response.status_code,200)
  self.assertEqual(VideoLog.objects.filter(source='AUTO').count(),3)
  self.assertEqual(PostWorkReport.objects.count(),0,'Risk events alone do not generate a report')
  Compliance.objects.create(employee=self.user,worksession=self.session,category='HELMET',is_complied=False)
  Photo.objects.create(employee=self.user,worksession=self.session,status='BEFORE',image_path='fixture://before.jpg')
  package=build_input_package(self.session.id)
  self.assertEqual(package['risk_logs']['stats']['total'],3)
  self.assertEqual(len(package['risk_logs']['highlights']),1)
  self.assertEqual(package['risk_logs']['highlights'][0]['count'],3)
  def generated(_):
   return {'report_title':'격리 테스트 보고서 (LLM stub)','risk_statistics':{'total':999},
     'risk_highlights':[{'invented':True}],'before_after_summary':{'before_photos':['fake']},
     'compliance_summary':{},'action_items':{'immediate':['테스트 조치'],'preventive':[],'follow_up':[]}}
  with patch('apps.report.views.generate_report_json',side_effect=generated) as llm:
   first=self.client.post('/api/report/generate',{'worksession_id':self.session.id},format='json')
   second=self.client.post('/api/report/generate',{'worksession_id':self.session.id},format='json')
  self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,200)
  self.assertEqual(llm.call_count,2)
  self.assertEqual([first.data['report_version'],second.data['report_version']],[1,2])
  self.assertEqual(first.data['report']['risk_statistics']['total'],3)
  self.assertEqual(first.data['report']['before_after_summary']['before_photos'],['fixture://before.jpg'])
  self.assertEqual(first.data['report']['compliance_summary']['helmet']['not_complied'],1)
  self.assertEqual(first.data['report']['risk_highlights'][0]['count'],3)
  saved=PostWorkReport.objects.get(pk=first.data['report_id'])
  self.assertEqual(saved.input_snapshot['risk_logs']['stats']['total'],3)
  self.assertEqual(saved.report_snapshot,first.data['report'])
  latest=self.client.get(f'/api/report/{self.session.id}/latest')
  versions=self.client.get(f'/api/report/{self.session.id}/versions')
  self.assertEqual(latest.data['report_version'],2)
  self.assertEqual([v['report_version'] for v in versions.data['versions']],[2,1])
  artifact={'kind':'synthetic_sqlite_contract_test_not_real_detection_or_llm_report',
    'generated_by':'tests/report_pipeline/run.py','llm_stubbed':True,'external_services_used':False,
    'request':self.payload(),'response':first.data}
  (ROOT/'performance-results/report-pipeline-fixture.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2))
 def test_bodycam_validation_and_internal_header_is_not_jwt(self):
  unauth=APIClient()
  response=unauth.post('/api/detect/bodycam/',self.payload(),format='json',HTTP_X_INTERNAL_KEY='fixture-key')
  self.assertEqual(response.status_code,401)
  bad=self.payload();bad.pop('risk_type_id')
  self.assertEqual(self.client.post('/api/detect/bodycam/',bad,format='json').status_code,400)
  self.risk.camera_type='FULL';self.risk.save()
  self.assertEqual(self.client.post('/api/detect/bodycam/',self.payload(),format='json').status_code,400)
  self.assertEqual(VideoLog.objects.count(),0)
 def test_generation_failure_does_not_save_report(self):
  with patch('apps.report.views.generate_report_json',side_effect=RuntimeError('controlled LLM failure')):
   with self.assertRaisesRegex(RuntimeError,'controlled LLM failure'):
    self.client.post('/api/report/generate',{'worksession_id':self.session.id},format='json')
  self.assertEqual(PostWorkReport.objects.count(),0)
 def test_empty_session_and_missing_report(self):
  package=build_input_package(self.session.id)
  self.assertEqual(package['risk_logs']['stats']['total'],0)
  self.assertEqual(package['risk_logs']['highlights'],[])
  self.assertEqual(self.client.get(f'/api/report/{self.session.id}/latest').status_code,404)
  self.assertEqual(self.client.post('/api/report/generate',{},format='json').status_code,400)
 def test_default_worker_endpoint_absent_from_root_routes(self):
  # Check real application route declarations, rather than our reduced test URLconf.
  tree=ast.parse((ROOT/'backend/apps/urls.py').read_text())
  routes=[node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call)
    and isinstance(node.func,ast.Name) and node.func.id=='path' and node.args and isinstance(node.args[0],ast.Constant)]
  self.assertNotIn('incidents/',routes)
  self.assertIn('incident/',routes);self.assertIn('detect/',routes);self.assertIn('report/',routes)
  worker=ast.parse((ROOT/'vision_bodycam/worker.py').read_text())
  assignment=next(n for n in worker.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DJANGO_API_URL' for t in n.targets))
  self.assertEqual(assignment.value.args[1].value,'http://localhost:8000/api/incidents/')

if __name__=='__main__':
 old=setup_databases(verbosity=0,interactive=False)
 try:
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReportPipelineTests))
 finally:teardown_databases(old,verbosity=0)
 sys.exit(0 if result.wasSuccessful() else 1)
