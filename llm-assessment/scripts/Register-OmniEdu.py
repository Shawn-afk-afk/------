"""Verify and register an existing local OmniEdu package without modifying it."""
import argparse,hashlib,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,model_library,model_slots

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()

def verify(package):
    config=json.loads((package/'adapter/adapter_config.json').read_text('utf-8-sig'))
    if config.get('base_model_name_or_path')!='google/gemma-4-E4B-it' or config.get('peft_type')!='LORA':raise ValueError('不是指定的 Gemma 4 E4B-it LoRA')
    manifest=json.loads((package/'evidence/base_model_manifest.json').read_text('utf-8-sig'))
    if manifest['revision']!=config.get('revision'):raise ValueError('底模與 adapter revision 不一致')
    for entry in manifest['files']:
        path=(package/'base_model'/entry['path']).resolve()
        if not path.is_relative_to((package/'base_model').resolve()) or not path.is_file():raise ValueError('模型來源路徑不合法或缺檔')
        if path.stat().st_size!=entry['size'] or digest(path)!=entry['sha256']:raise ValueError('底模雜湊不符：'+path.name)
    adapter=package/'adapter/adapter_model.safetensors'
    adapter_hash=digest(adapter)
    if adapter_hash!='ec4f6736e96d8f293558355a0ca56047571ea59b6ef5fb7fd652d6c0b1480b0c':raise ValueError('OmniEdu adapter 雜湊不符')
    return config,adapter_hash

def register(package,endpoint):
    config,adapter_hash=verify(package);storage.initialize()
    with storage.db() as c:
        admin=c.execute("SELECT id FROM users WHERE role='admin' AND disabled=0 ORDER BY rowid LIMIT 1").fetchone()
        if not admin:raise ValueError('先在網站建立管理者帳戶')
        owner=admin['id']
    # Small adapter/config are archived as SQLite chunks; the 16 GB immutable base
    # remains at its existing path. Never copy weights into a Git repository.
    for name in ('adapter_model.safetensors','adapter_config.json'):
        file=package/'adapter'/name;iid='omniedu-'+name;h=digest(file)
        with file.open('rb') as stream:prefix=stream.read(model_library.CHUNK)
        model_library.validate_weight(name,file.stat().st_size,prefix)
        with storage.db() as c:
            existing=c.execute('SELECT sha256 FROM model_uploads WHERE id=?',(iid,)).fetchone()
            if existing:
                if existing['sha256']!=h:raise ValueError('已有同名 OmniEdu 權重，但雜湊不同')
                continue
            c.execute('INSERT INTO model_uploads VALUES(?,?,?,?,?,?,?,?)',(iid,owner,name,file.stat().st_size,file.stat().st_size,'stored',h,time.time()))
            offset=0
            with file.open('rb') as stream:
                for block in iter(lambda:stream.read(model_library.CHUNK),b''):
                    c.execute('INSERT INTO model_upload_chunks VALUES(?,?,?)',(iid,offset,block));offset+=len(block)
    profile={'provider':'omni_local','endpoint':model_slots.endpoint(endpoint),'model':'omniedu-gemma4-e4b-it-lora','vision':True,'source_kind':'lora','base_model':'google/gemma-4-E4B-it','adapter_note':'OmniEdu final 20261007 · rank8 · '+config['revision']+' · adapter SHA256 '+adapter_hash,'reasoning':'medium','package_path':str(package)}
    with storage.db() as c:
        old=c.execute("SELECT config_json FROM model_profiles WHERE id='omniedu-final-20261007'").fetchone()
        if old and storage.decode(old['config_json'])!=profile:raise ValueError('既有 OmniEdu 來源設定不同，請在後台新增新版本')
        c.execute('INSERT OR IGNORE INTO model_profiles VALUES(?,?,?,?)',('omniedu-final-20261007','OmniEdu · Gemma 4 E4B-it · LoRA rank8',storage.encode(profile),time.time()))
        storage.audit(c,owner,'omniedu_registered','omniedu-final-20261007',{'adapter_sha256':adapter_hash,'base_revision':config['revision']})
    print('OmniEdu hashes verified; adapter archived; source registered. Existing model roles preserved.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--endpoint',default='http://127.0.0.1:8767/v1');parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    package=Path(args.package).resolve()
    if args.verify_only:verify(package);print('OmniEdu base and adapter hashes verified')
    else:register(package,args.endpoint)
