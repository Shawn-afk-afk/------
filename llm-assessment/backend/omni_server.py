"""Loopback-only OpenAI-compatible bridge for the user's native OmniEdu LoRA.

No model download, hosted inference or remote Python code. Optional dependencies
are installed in an isolated environment; all weights are read from --package.
"""
import argparse,base64,gc,io,json,os,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
MODEL_ID='omniedu-gemma4-e4b-it-lora'
GATE=threading.Lock()

class Engine:
    def __init__(self,package):self.package=Path(package).resolve();self.model=None;self.processor=None
    def load(self):
        if self.model is not None:return
        import torch
        from peft import PeftModel
        from transformers import AutoProcessor,AutoModelForCausalLM,BitsAndBytesConfig
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():raise RuntimeError('OmniEdu 原生來源需要支援 BF16 的 NVIDIA CUDA GPU；此載入器不支援 M5／CPU')
        base=self.package/'base_model';adapter=self.package/'adapter'
        config=json.loads((adapter/'adapter_config.json').read_text('utf-8-sig'))
        if config.get('base_model_name_or_path')!='google/gemma-4-E4B-it':raise ValueError('OmniEdu adapter 的基底不是 google/gemma-4-E4B-it')
        self.processor=AutoProcessor.from_pretrained(str(base),local_files_only=True,trust_remote_code=False)
        self.processor.tokenizer.chat_template=(base/'chat_template.jinja').read_text('utf-8')
        model=AutoModelForCausalLM.from_pretrained(str(base),local_files_only=True,trust_remote_code=False,use_safetensors=True,dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa',low_cpu_mem_usage=True,quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16))
        for name,param in model.named_parameters():
            param.requires_grad=False
            if 'norm' in name.lower() and param.dtype in (torch.float16,torch.bfloat16) and param.__class__.__name__!='Params4bit':param.data=param.data.to(torch.float32)
        self.model=PeftModel.from_pretrained(model,str(adapter),is_trainable=False,autocast_adapter_dtype=False,local_files_only=True).eval()
    def unload(self):
        self.model=None;self.processor=None;gc.collect()
        try:
            import torch
            if torch.cuda.is_available():torch.cuda.empty_cache()
        except ImportError:pass
    def generate(self,body):
        from PIL import Image
        import torch
        messages=body.get('messages');images=[];converted=[]
        if not isinstance(messages,list) or not 1<=len(messages)<=40:raise ValueError('messages 必須是 1–40 則訊息')
        try:
            for item in messages:
                if not isinstance(item,dict) or item.get('role') not in ('system','user','assistant'):raise ValueError('不支援的訊息角色')
                raw=item.get('content');content=[]
                if isinstance(raw,str):content=[{'type':'text','text':raw}]
                elif isinstance(raw,list):
                    for part in raw:
                        if part.get('type')=='text' and isinstance(part.get('text'),str):content.append({'type':'text','text':part['text']})
                        elif part.get('type')=='image_url':
                            url=part.get('image_url',{}).get('url','')
                            if not isinstance(url,str) or not url.startswith('data:image/png;base64,') or len(images)>=2:raise ValueError('只支援最多兩張內嵌 PNG 圖片')
                            data=base64.b64decode(url.split(',',1)[1],validate=True)
                            if len(data)>8*1024**2:raise ValueError('圖片超過 8 MiB')
                            with Image.open(io.BytesIO(data)) as picture:
                                if picture.width*picture.height>12_000_000:raise ValueError('圖片解析度過高')
                                images.append(picture.convert('RGB'))
                            content.append({'type':'image'})
                        else:raise ValueError('不支援的訊息內容')
                else:raise ValueError('訊息內容需為文字或圖文陣列')
                converted.append({'role':item['role'],'content':content})
            if body.get('response_format',{}).get('type')=='json_object':
                instruction={'type':'text','text':'Return only a valid JSON object that follows the requested schema. No Markdown fences.'}
                if converted and converted[0]['role']=='system':converted[0]['content'].insert(0,instruction)
                else:converted.insert(0,{'role':'system','content':[instruction]})
            budget=body.get('max_tokens',512)
            if type(budget) is not int or budget<1:raise ValueError('max_tokens 需為正整數')
            budget=min(budget,2048);self.load()
            prompt=self.processor.apply_chat_template(converted,tokenize=False,add_generation_prompt=True)
            inputs=self.processor(text=[prompt],return_tensors='pt',padding=True,add_special_tokens=False,**({'images':[images]} if images else {})).to('cuda')
            length=inputs['input_ids'].shape[-1]
            if length+budget>8192:raise ValueError('輸入與生成預算超過 8192 tokens，沒有自動截斷')
            start=time.perf_counter()
            with torch.inference_mode():output=self.model.generate(**inputs,max_new_tokens=budget,do_sample=False,use_cache=True)
            generated=output[0,length:];text=self.processor.tokenizer.decode(generated,skip_special_tokens=True);count=generated.numel()
            return {'id':'omni-'+str(time.time_ns()),'object':'chat.completion','model':MODEL_ID,'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'length' if count==budget else 'stop'}],'usage':{'prompt_tokens':length,'completion_tokens':count,'total_tokens':length+count},'generation_seconds':round(time.perf_counter()-start,3)}
        finally:
            for image in images:image.close()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,value,status=200):
        data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/v1/models':return self.send({'object':'list','data':[{'id':MODEL_ID,'object':'model','owned_by':'local','capabilities':['text','vision'],'loaded':self.server.engine.model is not None}]})
        self.send({'error':'not found'},404)
    def do_POST(self):
        if self.headers.get('Origin'):return self.send({'error':'只接受本機後端呼叫'},403)
        if self.path not in ('/v1/chat/completions','/v1/unload'):return self.send({'error':'not found'},404)
        if not GATE.acquire(blocking=False):return self.send({'error':'本機模型忙碌，請稍後重試'},503)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=12*1024**2:raise ValueError('請求大小不合法')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('只接受 JSON')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError('JSON 必須是 object')
            if self.path=='/v1/unload':self.server.engine.unload();return self.send({'ok':True})
            if body.get('model')!=MODEL_ID or body.get('stream'):raise ValueError('請使用 OmniEdu 模型 ID，stream=false')
            self.send(self.server.engine.generate(body))
        except (ValueError,KeyError,TypeError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:print('OmniEdu inference failed:',type(exc).__name__,str(exc)[:400],flush=True);self.server.engine.unload();self.send({'error':'原生模型載入或推論失敗，請查看主機紀錄與套件／GPU 相容性'},503)
        finally:GATE.release()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--port',type=int,default=8767);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.engine=Engine(args.package)
    print(f'OmniEdu local API: http://127.0.0.1:{args.port}/v1',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.engine.unload();server.server_close()

if __name__=='__main__':main()
