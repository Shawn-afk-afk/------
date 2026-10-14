"""This script is passed through stdin to a disposable restricted Linux container.
No student code is executed by the website process.
"""
import contextlib
import copy
import io
import json
import math

class LimitedOutput(io.StringIO):
    def write(self, s):
        if self.tell()+len(s)>16000: raise RuntimeError('輸出超過限制')
        return super().write(s)

def normalize(value,encoding=None):
    if encoding=='tuple_key_pairs':
        if not isinstance(value,dict): return value
        return sorted([[list(k),v] for k,v in value.items()],key=lambda x:repr(x[0]))
    if isinstance(value,(tuple,list)): return [normalize(x) for x in value]
    if isinstance(value,dict): return {str(k):normalize(v) for k,v in value.items()}
    return value

def equal(a,b,tol):
    if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)):
        return math.isclose(a,b,rel_tol=tol,abs_tol=tol)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(equal(x,y,tol) for x,y in zip(a,b))
    return a==b

def evaluate(package):
    out=LimitedOutput()
    ns={'__name__':'__student__'}
    result=[]
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
        try:
            exec(compile(package['code'],'submission.py','exec'),ns)
            fn=ns.get(package['tests']['function'])
            if not callable(fn): raise ValueError('找不到題目指定的函式')
            for case in package['cases']:
                args=copy.deepcopy(case['args'])
                original=copy.deepcopy(args)
                try:
                    actual=fn(*args)
                    passed=('raises' not in case and equal(normalize(actual,case.get('encoding')),case['expected'],package['tests'].get('abs_tol',1e-8)))
                    if package['tests'].get('mutation_check') and args!=original: passed=False
                    result.append({'passed':passed,'actual':normalize(actual,case.get('encoding'))})
                except Exception as exc:
                    result.append({'passed':type(exc).__name__==case.get('raises'),'exception':type(exc).__name__})
        except Exception as exc:
            return {'status':'error','error':str(exc)[:500],'stdout':out.getvalue()[:16000]}
    return {'status':'completed','tests':result,'passed':sum(x['passed'] for x in result),'total':len(result),'stdout':out.getvalue()[:16000]}

if __name__=='__main__':
    import sys
    # Configuration is injected as a literal by runner.py, stdin carries script only.
    print(json.dumps(evaluate(PACKAGE),ensure_ascii=False))
