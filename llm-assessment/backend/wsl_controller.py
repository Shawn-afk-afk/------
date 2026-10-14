"""Trusted WSL controller. Expected answers never enter the student namespace."""
import json
import math
import subprocess
import tempfile
import time

def command():
    return ['/usr/bin/bwrap','--unshare-all','--unshare-user','--uid','65534','--gid','65534','--disable-userns','--assert-userns-disabled','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv','--setenv','PATH','/usr/bin','--setenv','LANG','C.UTF-8','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev','--size','16777216','--tmpfs','/tmp','--chdir','/tmp','--','/usr/bin/prlimit','--as=268435456:268435456','--cpu=3:3','--nproc=0:0','--fsize=65536:65536','--nofile=32:32','--core=0:0','--','/usr/bin/python3','-I','-B']

CHILD=r'''
import contextlib,copy,io,json
class Output(io.StringIO):
    def write(self,s):
        if self.tell()+len(s)>16000:raise RuntimeError('輸出超過限制')
        return super().write(s)
def norm(v,encoding=None):
    if encoding=='tuple_key_pairs' and isinstance(v,dict):return sorted([[list(k),x] for k,x in v.items()],key=lambda x:repr(x[0]))
    if isinstance(v,(tuple,list)):return [norm(x) for x in v]
    if isinstance(v,dict):return {str(k):norm(x) for k,x in v.items()}
    return v
out=Output();ns={'__name__':'__student__'};args=DATA['args'];original=copy.deepcopy(args)
try:
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
        exec(compile(DATA['code'],'submission.py','exec'),ns)
        fn=ns.get(DATA['function'])
        if not callable(fn):raise ValueError('找不到指定函式')
        value=fn(*args)
    result={'actual':norm(value,DATA.get('encoding')),'mutated':args!=original,'stdout':out.getvalue()}
except Exception as exc:result={'exception':type(exc).__name__,'error':str(exc)[:300],'stdout':out.getvalue()}
print(json.dumps(result,ensure_ascii=False,allow_nan=False))
'''

def equal(a,b,tol):
    if type(a) in (int,float) and type(b) in (int,float):return math.isfinite(a) and math.isclose(a,b,rel_tol=tol,abs_tol=tol)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y,tol) for x,y in zip(a,b))
    return a==b

def evaluate(package):
    deadline=time.monotonic()+12;results=[];logs=[]
    for case in package['cases']:
        remaining=deadline-time.monotonic()
        if remaining<=0:return {'status':'timeout','error':'整份程式試跑超過 12 秒'}
        data={'code':package['code'],'function':package['tests']['function'],'args':case['args'],'encoding':case.get('encoding')}
        script='DATA='+repr(data)+'\n'+CHILD
        with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
            try:p=subprocess.run(command()+['-'],input=script.encode(),stdout=stdout,stderr=stderr,timeout=min(5,remaining))
            except subprocess.TimeoutExpired:return {'status':'timeout','error':'單一測試超過時間限制'}
            if p.returncode:return {'status':'error','error':'程式超過資源限制或隔離執行失敗'}
            stdout.seek(0)
            try:actual=json.loads(stdout.read(65536))
            except (ValueError,UnicodeError):return {'status':'error','error':'程式輸出不合法或超過限制'}
        if 'exception' in actual:passed=actual['exception']==case.get('raises')
        else:passed='raises' not in case and equal(actual.get('actual'),case.get('expected'),package['tests'].get('abs_tol',1e-8)) and not (package['tests'].get('mutation_check') and actual.get('mutated'))
        results.append({'passed':passed,**{k:v for k,v in actual.items() if k!='stdout'}})
        logs.append(actual.get('stdout','')[:16000])
    return {'status':'completed','tests':results,'passed':sum(x['passed'] for x in results),'total':len(results),'stdout':'\n'.join(logs)[:16000]}

if __name__=='__main__':print(json.dumps(evaluate(PACKAGE),ensure_ascii=False,allow_nan=False))
