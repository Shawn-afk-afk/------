"""WSL2 runner: trusted controller, isolated student processes, no host fallback."""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

DISTRO=os.environ.get('ASSESSMENT_WSL_DISTRO','Ubuntu')
GATE=threading.BoundedSemaphore(2)
_cached=(0,None)

def availability():
    global _cached
    if time.monotonic()-_cached[0]<30 and _cached[1] is not None:return dict(_cached[1])
    if not shutil.which('wsl'):return {'available':False,'reason':'需要 WSL2 Ubuntu 與 bubblewrap；瀏覽器練習仍可使用。'}
    try:
        from wsl_controller import command
        p=subprocess.run(['wsl','-d',DISTRO,'--exec']+command()+['-c','print("sandbox-ready")'],capture_output=True,timeout=12)
        result={'available':True,'image':'WSL2 '+DISTRO+' / bubblewrap / Python3','backend':'wsl2'} if p.returncode==0 and b'sandbox-ready' in p.stdout else {'available':False,'reason':'WSL2 隔離 runner 未就緒，執行 scripts/Prepare-Runner.ps1。','detail':p.stderr.decode('utf-8','replace')[:300]}
    except (OSError,subprocess.TimeoutExpired):result={'available':False,'reason':'WSL2 啟動或沙箱驗證失敗。'}
    _cached=(time.monotonic(),result)
    return dict(result)

def run(code,tests,hidden=False):
    if not isinstance(code,str) or len(code)>50000:return {'status':'error','error':'程式長度不合法'}
    if not availability()['available']:return {'status':'unavailable','error':'WSL2 隔離 runner 未就緒，保留作答供 AI／人工覆核。'}
    cases=tests.get('public',[])+(tests.get('hidden',[]) if hidden else [])
    package={'code':code,'tests':tests,'cases':cases}
    script='PACKAGE = '+repr(package)+'\n'+Path(__file__).with_name('wsl_controller.py').read_text(encoding='utf-8')
    with GATE:
        try:
            p=subprocess.run(['wsl','-d',DISTRO,'--exec','/usr/bin/python3','-I','-B','-'],input=script.encode(),capture_output=True,timeout=20)
            if p.returncode:return {'status':'error','error':'WSL2 控制器執行失敗','detail':p.stderr.decode('utf-8','replace')[:300]}
            result=json.loads(p.stdout)
            result['runtime']='WSL2 '+DISTRO+' / bubblewrap / Python3'
            if hidden:
                result['tests']=[{'passed':x['passed']} for x in result.get('tests',[])]
                result.pop('stdout',None)
            return result
        except subprocess.TimeoutExpired:return {'status':'timeout','error':'執行時間超過限制'}
        except (OSError,ValueError):return {'status':'error','error':'runner 回傳無法解析，請管理者檢查 WSL2'}
