import importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('opencode_budget',root/'opencode/skills/autosubflow/scripts/context_budget.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class BudgetTests(unittest.TestCase):
 def msg(self,used=225000):return {'type':'assistant','id':'msg_1','model':{'id':'model-a','providerID':'provider-a'},'tokens':{'input':5000,'output':0,'reasoning':0,'cache':{'read':used-5000,'write':0}}}
 def models(self,capacity=1000000):return [{'id':'model-a','providerID':'provider-a','limit':{'context':capacity}}]
 def test_previous_low_usage_continues(self):
  for used in [224689,237458]:self.assertFalse(b.evaluate([self.msg(used)],self.models(),'ses_test')['handoff_allowed'])
 def test_threshold(self):
  self.assertFalse(b.evaluate([self.msg(899999)],self.models(),'ses_test')['handoff_allowed'])
  self.assertTrue(b.evaluate([self.msg(900000)],self.models(),'ses_test')['handoff_allowed'])
 def test_uses_latest_request_not_accumulated(self):
  d=b.evaluate([self.msg(950000),self.msg(225000)],self.models(),'ses_test')
  self.assertEqual(d['effective_tokens'],225000)
 def test_exact_model_capacity(self):
  self.assertTrue(b.evaluate([self.msg(225000)],self.models(250000),'ses_test')['handoff_allowed'])
  self.assertFalse(b.evaluate([self.msg()],[], 'ses_test')['handoff_allowed'])
 def test_unknown_not_exhaustion(self):
  for msgs in [[],[{'type':'assistant'}],[{'type':'user'}]]:self.assertEqual(b.evaluate(msgs,self.models(),'ses_test')['decision'],'telemetry_unavailable')
 def test_parent_rejected_and_no_mutating_api(self):
  seen=[]
  def api(cli,path,server):seen.append(path);return {'id':'ses_test','location':{'directory':str(root)}}
  with patch.object(b,'api',api):d=b.check('cli',root,'ses_test')
  self.assertFalse(d['handoff_allowed']);self.assertEqual(seen,['/api/session/ses_test'])
 def test_exact_child_and_auto_selection(self):
  seen=[]
  def api(cli,path,server):
   seen.append(path)
   return {'/api/session/active':{'ses_test':{'type':'running'}},'/api/session/ses_test':{'id':'ses_test','parentID':'ses_parent','location':{'directory':str(root)}},'/api/session/ses_test/context':[self.msg()],'/api/model':self.models()}[path]
  with patch.object(b,'api',api):d=b.check('cli',root)
  self.assertEqual(d['session_id'],'ses_test');self.assertEqual(d['decision'],'continue')
  self.assertTrue(all(p.startswith('/api/') for p in seen))
 def test_ambiguous_active_child_not_guessed(self):
  def api(cli,path,server):
   return {'ses_a':{},'ses_b':{}} if path.endswith('active') else {'id':path.rsplit('/',1)[-1],'parentID':'ses_parent','location':{'directory':str(root)}}
  with patch.object(b,'api',api):self.assertFalse(b.check('cli',root)['handoff_allowed'])
if __name__=='__main__':unittest.main()
