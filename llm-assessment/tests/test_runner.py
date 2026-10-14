import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import runner

@unittest.skipUnless(os.environ.get('ASSESSMENT_TEST_WSL')=='1','Set ASSESSMENT_TEST_WSL=1 for real WSL isolation checks')
class Isolation(unittest.TestCase):
    def run_code(self,code,cases,**options):
        return runner.run(code,{'function':'solve','public':cases,'hidden':[],**options})
    def test_correct_wrong_and_mutation(self):
        cases=[{'args':[[1,2]],'expected':3},{'args':[[]],'expected':0}]
        self.assertEqual(self.run_code('def solve(x): return sum(x)',cases)['passed'],2)
        self.assertEqual(self.run_code('def solve(x): return 99',cases)['passed'],0)
        self.assertEqual(self.run_code('def solve(x):\n x.append(4)\n return 3',cases,mutation_check=True)['passed'],0)
    def test_files_network_and_processes_denied(self):
        code='''def solve():
 import os,socket
 denied=[]
 for path in ['/mnt/c/Users','/home/joel','/etc/shadow']:
  try: open(path);denied.append(False)
  except OSError:denied.append(True)
 try:
  s=socket.socket();s.settimeout(.2);s.connect(('1.1.1.1',80));denied.append(False)
 except OSError:denied.append(True)
 try:os.fork();denied.append(False)
 except OSError:denied.append(True)
 return denied
'''
        result=self.run_code(code,[{'args':[],'expected':[True]*5}])
        self.assertEqual(result.get('passed'),1,result)
    def test_timeout_memory_and_direct_output(self):
        for code in ['def solve():\n while True: pass','def solve(): return bytearray(400000000)','def solve():\n import os\n os.write(1,b"x"*1000000)']:
            result=self.run_code(code,[{'args':[],'expected':0}])
            self.assertTrue(result['status'] in ('timeout','error') or result.get('passed')==0,result)
    def test_hidden_values_not_returned(self):
        tests={'function':'solve','public':[],'hidden':[{'args':['hidden-secret-123'],'expected':'hidden-secret-123'}]}
        result=runner.run('def solve(x):\n print(x)\n return x',tests,hidden=True)
        self.assertEqual(result.get('passed'),1,result)
        self.assertNotIn('hidden-secret',str(result));self.assertNotIn('stdout',result)

if __name__=='__main__':unittest.main(verbosity=2)
