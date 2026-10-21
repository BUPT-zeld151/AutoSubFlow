from pathlib import Path
import importlib.util,json,os,sys,time,tempfile,unittest,ast,re
sys.dont_write_bytecode=True
base=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dsh_budget',base/'dsh/autosubflow/scripts/context_budget.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
ID='11111111-1111-1111-1111-111111111111'
ID2='22222222-2222-2222-2222-222222222222'
class ContextBudgetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.home=Path(self.tmp.name);self.ws=self.home/'project';self.ws.mkdir()
  self.cache=self.home/'storages/session_projcache/sessions';self.cache.mkdir(parents=True)
 def tearDown(self):self.tmp.cleanup()
 def record(self,used=224689,window=1000000,active=True):
  return {'identity':{'cwd':str(self.ws)},'rows':{'subagent':{'val':{'identity':{'mode':'one-shot'}}},'turnBoundary':{'val':{'openTurnStartSeq':3 if active else None}},'contextPressure':{'seq':10,'val':{'pressureTokens':used,'contextWindow':window}}}}
 def write(self,r,ident=ID):
  p=self.cache/(ident+'.json');p.write_text(json.dumps({'record':r}));return p
 def test_reported_premature_handoffs_rejected(self):
  for used in [224689,237458]:
   self.write(self.record(used));d=b.check(self.home,self.ws)
   self.assertEqual(d['decision'],'continue');self.assertFalse(d['handoff_allowed'])
 def test_actual_threshold_and_not_assumed_1m(self):
  for used,window,allow in [(899999,1000000,False),(900000,1000000,True),(1000000,1000000,True),(230000,250000,True)]:
   self.write(self.record(used,window));self.assertEqual(b.check(self.home,self.ws)['handoff_allowed'],allow)
 def test_projection_delta_and_large_cumulative_usage(self):
  r=self.record(800000);r['rows']['contextPressure']['val'].update(surfaceTokens=150000,sampledSurfaceTokens=20000)
  self.write(r);self.assertEqual(b.check(self.home,self.ws)['effective_tokens'],930000)
  r=self.record(224689);r['rows']['tokenUsage']={'val':{'totals':{'cacheReadTokens':20000000}}};self.write(r)
  self.assertFalse(b.check(self.home,self.ws)['handoff_allowed'])
 def test_missing_invalid_stale_records_not_evidence(self):
  for field,value in [('pressureTokens',None),('pressureTokens',-1),('contextWindow',0),('contextWindow',True)]:
   r=self.record();r['rows']['contextPressure']['val'][field]=value;self.write(r)
   self.assertEqual(b.check(self.home,self.ws)['decision'],'telemetry_unavailable')
  p=self.write(self.record(950000));os.utime(p,(time.time()-600,time.time()-600))
  self.assertFalse(b.check(self.home,self.ws,ID)['handoff_allowed'])
 def test_exact_child_identity_required(self):
  self.write(self.record(950000));self.write(self.record(950000),ID2)
  self.assertEqual(b.check(self.home,self.ws)['decision'],'telemetry_unavailable')
  self.assertTrue(b.check(self.home,self.ws,ID)['handoff_allowed'])
  self.assertFalse(b.check(self.home,self.home,ID)['handoff_allowed'])
  r=self.record(950000);r['rows']['subagent']['val']={};self.write(r)
  self.assertFalse(b.check(self.home,self.ws,ID)['handoff_allowed'])
 def test_finished_child_can_be_verified_by_parent(self):
  self.write(self.record(950000,active=False))
  self.assertFalse(b.check(self.home,self.ws)['handoff_allowed'])
  self.assertTrue(b.check(self.home,self.ws,ID)['handoff_allowed'])
 def test_no_writes_to_cache_or_project(self):
  p=self.write(self.record());data=p.read_bytes();stamp=p.stat().st_mtime_ns
  b.check(self.home,self.ws)
  self.assertEqual(p.read_bytes(),data);self.assertEqual(p.stat().st_mtime_ns,stamp)
  self.assertEqual(list(self.ws.iterdir()),[])
 def test_malformed_record_fails_closed(self):
  (self.cache/(ID+'.json')).write_text('{"record":[]}')
  self.assertFalse(b.check(self.home,self.ws,ID)['handoff_allowed'])
  self.assertFalse(b.check(self.home,self.ws,'../elsewhere')['handoff_allowed'])
if __name__=='__main__':unittest.main()
