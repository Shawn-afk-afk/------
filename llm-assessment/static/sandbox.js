'use strict';
// This document has an opaque origin (sandbox=allow-scripts, never allow-same-origin).
// It receives code and PUBLIC tests only, never credentials or hidden tests.
const source=`
importScripts('https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.js');
let runtime;
self.onmessage=async(event)=>{
 const {id,code,tests}=event.data;
 try {
  runtime=await loadPyodide({indexURL:'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/'});
  let stdout='';runtime.setStdout({batched:s=>{stdout+=(s+'\\n');if(stdout.length>16000)throw Error('輸出過多');}});
  runtime.globals.set('__package_json',JSON.stringify({code,tests,cases:tests.public}));
  const raw=await runtime.runPythonAsync(
   'import json, math, copy\\n'+
   '__pkg=json.loads(__package_json)\\n'+
   '__ns={"__name__":"__student__"}\\n'+
   'exec(compile(__pkg["code"],"practice.py","exec"),__ns)\\n'+
   '__fn=__ns[__pkg["tests"]["function"]]\\n'+
   'def __norm(v,encoding=None):\\n'+
   '    if encoding=="tuple_key_pairs" and isinstance(v,dict): return sorted([[list(k),x] for k,x in v.items()],key=lambda x:repr(x[0]))\\n'+
   '    if isinstance(v,(list,tuple)): return [__norm(x) for x in v]\\n'+
   '    return v\\n'+
   'def __eq(a,b,tol):\\n'+
   '    if isinstance(a,(float,int)) and isinstance(b,(float,int)): return math.isclose(a,b,rel_tol=tol,abs_tol=tol)\\n'+
   '    if isinstance(a,list) and isinstance(b,list): return len(a)==len(b) and all(__eq(x,y,tol) for x,y in zip(a,b))\\n'+
   '    return a==b\\n'+
   '__results=[]\\n'+
   'for __case in __pkg["cases"]:\\n'+
   '    __args=copy.deepcopy(__case["args"])\\n'+
   '    __before=copy.deepcopy(__args)\\n'+
   '    try:\\n'+
   '        __actual=__norm(__fn(*__args),__case.get("encoding"))\\n'+
   '        __pass="raises" not in __case and __eq(__actual,__case.get("expected"),__pkg["tests"].get("abs_tol",1e-8))\\n'+
   '        if __pkg["tests"].get("mutation_check") and __args!=__before: __pass=False\\n'+
   '        __results.append({"passed":__pass,"actual":__actual})\\n'+
   '    except Exception as __exc:\\n'+
   '        __results.append({"passed":type(__exc).__name__==__case.get("raises"),"exception":type(__exc).__name__})\\n'+
   'json.dumps({"status":"completed","tests":__results,"passed":sum(x["passed"] for x in __results),"total":len(__results)})');
  const result=JSON.parse(raw);result.stdout=stdout.slice(0,16000);self.postMessage({id,result});
 }catch(e){self.postMessage({id,error:String(e.message).slice(0,2000)});}
};`;
window.addEventListener('message',event=>{
 if(event.source!==parent||typeof event.data?.code!=='string'||!event.data.id)return;
 const {id,code,tests}=event.data;
 if(code.length>50000||!tests||!Array.isArray(tests.public)){parent.postMessage({id,error:'程式或測試格式不合法'},'*');return;}
 const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));
 const worker=new Worker(url);
 const timer=setTimeout(()=>{worker.terminate();URL.revokeObjectURL(url);parent.postMessage({id,error:'練習執行逾時，已停止'},'*');},55000);
 worker.onmessage=e=>{clearTimeout(timer);worker.terminate();URL.revokeObjectURL(url);parent.postMessage(e.data,'*');};
 worker.onerror=e=>{clearTimeout(timer);worker.terminate();URL.revokeObjectURL(url);parent.postMessage({id,error:e.message||'Python 環境載入失敗，請檢查網路'},'*');};
 worker.postMessage({id,code,tests:{...tests,hidden:undefined}});
});
