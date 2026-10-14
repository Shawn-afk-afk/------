"""Real local model smoke check; no stored scores or live learner data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,analysis
config=analysis.settings()
if config['model']!='gpt-oss:20b':raise SystemExit('測試要求使用 gpt-oss:20b。')
def question(title):
    with storage.db() as c:
        return storage.question(c.execute('SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE v.title=? ORDER BY v.version DESC LIMIT 1',(title,)).fetchone(),True)
def check(q,response):
    result=analysis.grade(q,response,config)
    print(storage.encode({'title':q['title'],'model':config['model'],'reasoning':config['reasoning'],'complete':result['complete'],'raw_points':result['raw_points'],'criteria':result['criteria'],'error':result['error']}),flush=True)
    if not result['complete']:raise SystemExit(1)
    return result
check(question('條件機率拼圖'),{'interaction':{'order':['C(A,B)','/','C(A)'],'result':'0.25'},'text':'P(B|A)=C(A,B)/C(A)=2/8=0.25。分母 C(A)=8，表示已知 A 出現時的機會總數，而其中 2 次接 B。因此是條件 A 的次數，不是 C(B)；條件方向不可倒置。'})
case=question('BERT Table 5：不是所有改動都改善')
fields=('observation','problem_and_alternatives','improvement_and_mechanism','validation_baseline_controls_metrics','constraints_and_failure')
strong=check(case,{'proposal':dict(zip(fields,case['answer']['teaching_guide']['steps']))})
weak=check(case,{'proposal':{field:'' for field in fields}})
if strong['raw_points']<=weak['raw_points'] or weak['raw_points']!=0:
    raise SystemExit('案例批改校準未通過：完整與空白作答的分數未合理區分。')
print('實際模型驗證通過：觀念題、五分項案例、真實證據及空白作答。',flush=True)
