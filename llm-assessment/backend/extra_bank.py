"""Additive, original chapter 1–2 choice and interactive exercises; draft only."""
from explanations import SECTIONS,REPO
from storage import encode,db,initialize
import random

# Option explanations stay in the private answer, never the learner payload.
CHOICES=[
('1.1','未見 bigram 的處理',False,'訓練語料未出現 (A,B)，但測試句包含此配對。哪個處理最合理？',[
('A','直接宣告這個句子不可能','未觀察到不代表語言上不可能。'),('B','採明確的平滑或 backoff，並在 held-out 資料比較','處理未見事件，同時用獨立資料驗證估計偏差與效益。'),('C','把測試句加進訓練計數後再評測','這會污染評測，無法檢驗泛化。'),('D','把所有未見配對機率設為 1','破壞正規化與合理機率分配。')],['B']),
('1.2','生成階段的前一個 token',False,'自回歸生成時，模型尚未看到下一個真實 token。下一步通常使用哪個輸入？',[
('A','資料集的真實下一個 token','這是偷看未來；生成時通常不可取得。'),('B','模型已生成的前一個 token','生成逐步使用已生成的前綴。'),('C','整份測試集的答案','這會產生答案洩漏。'),('D','每一步都重新使用同一個 BOS，丟掉前綴','這無法正常條件化於生成歷史。')],['B']),
('1.3','注意力分數縮放',False,'scaled dot-product attention 為何將 QKᵀ 除以 √d_k？',[
('A','保證任何 Q、K 都得到均勻注意力','縮放不會讓任意分數變成相同。'),('B','抑制維度增大時分數尺度，避免 softmax 過度飽和','在常見分量尺度假設下，點積變異隨維度增大，縮放有助穩定。'),('C','讓模型不再需要 V','V 仍提供被加權的內容。'),('D','直接消除所有浮點誤差','縮放不能保證消除數值誤差。')],['B']),
('1.4','greedy 的序列取捨',False,'有兩條完整序列，其機率分別為 .03 與 .10；greedy 得到 .03。這最直接顯示什麼？',[
('A','逐步局部最佳不保證完整序列最佳','局部選擇無法保證全局最大序列機率。'),('B','.03 一定比 .10 更有創意','序列機率不足以判定創意。'),('C','beam search 必定找到所有長度下的全局最優','有限 beam 仍可能刪掉之後較好的候選。'),('D','應將 .10 解讀為 10% 的事實正確率','模型序列機率不是事實準確率。')],['A']),
('1.5','PPL 改善能推出什麼',False,'在相同 held-out tokens 與計算方式下，模型 PPL 下降。哪個結論最有依據？',[
('A','所有下游任務一定改善','下游指標與 PPL 不相同。'),('B','此評測文字的平均負對數似然降低','在相同定義下，PPL 是平均 NLL 的指數。'),('C','可以跳過事實正確性評測','事實可靠性仍需直接評測。'),('D','模型的推論速度一定提高','PPL 不直接量測速度。')],['B']),
('2.3','MLM 能否直接當生成迴圈',False,'要把 BERT 的 MLM 訓練直接改成由左到右的 next-token 生成。哪個判斷合理？',[
('A','只把函式名稱改成 generate 就完全相同','介面名稱不能改變訓練目標與可見範圍。'),('B','需檢查訓練目標、遮罩與生成程序，不能視為等價','MLM 的雙向條件與自回歸前綴條件不同。'),('C','MLM 訓練從不使用 token 標籤','被遮罩位置的原 token 可作監督標籤。'),('D','任何 encoder-only 都無法用在任何下游任務','encoder 表示可支援分類等任務。')],['B']),
('1.4','top-p 的邊界條件',True,'機率已正規化且為 A=.50、B=.25、C=.15、D=.10；top-p 門檻 .80，按機率由大到小取最小達標前綴。選出所有正確敘述。',[
('A','候選集合為 A、B、C','A+B=.75 不足 .80；加 C 得 .90。'),('B','A、B 已達到門檻','累積只有 .75。'),('C','抽樣前需在保留集合內重新正規化','候選總和 .90，應將各機率除以 .90。'),('D','門檻 .80 表示一定恰好保留 80% 的 token 種類','門檻針對機率質量，與種類比例不同。')],['A','C']),
('1.5','建立可信評測集',True,'要比較兩個語言模型的 PPL。哪些做法能提高比較的可解讀性？',[
('A','固定相同資料切分並檢查訓練與評測重疊','能減少資料條件與污染混淆。'),('B','不同 tokenizer 的 raw token PPL 可不加說明直接比較','token 定義不同會影響可比性。'),('C','說明 tokenizer、截斷及 NLL 聚合方式','需要知道指標所依賴的計算條件。'),('D','只公布最好的一個 seed，略過其他結果','挑選最好結果會扭曲穩定性。')],['A','C']),
('2.1','固定算力的改善方案',True,'模型參數已很大而訓練 tokens 明顯不足。哪些下一步比較合理？',[
('A','比較較小模型搭配更多 tokens 的配置','固定算力下重新分配模型與資料預算。'),('B','所有任務都直接固定 20 tokens／參數，不需驗證','經驗比例不是跨條件的保證。'),('C','追蹤 held-out loss、實際算力與資料品質','同時檢查效果、預算及資料条件。'),('D','同時增加參數與資料，忽略原算力限制','不再是固定算力的比較。')],['A','C']),
('2.4','去噪實驗的控制變因',True,'比較兩種 T5／BART 延伸去噪策略。哪些設計較能支持「策略造成差異」？',[
('A','固定資料、模型規模與訓練預算','減少其他因素造成的差異。'),('B','新策略使用更多資料與更大模型，卻只歸因去噪','同時改變多項因素，歸因不成立。'),('C','同時觀察重建指標與目標下游任務指標','重建改善未必等於實際任務改善。'),('D','只看一段生成範例，不設基準','無法支持系統性比較。')],['A','C']),
('2.5','next-token 資料準備',True,'輸入 token 序列為 [BOS,A,B,EOS]。哪些處理正確？',[
('A','輸入 [BOS,A,B] 配標籤 [A,B,EOS]','輸入與標籤相差一個位置。'),('B','訓練時允許當前位置看見未來標籤 token','違反自回歸可見範圍，造成洩漏。'),('C','在同一個序列內處理相邻 token，並明確定義邊界','需要知道 EOS、句界與資料打包策略。'),('D','任何情況都把原輸入本身當作同位置標籤','未位移的同位置複製不是指定的 next-token 任務。')],['A','C']),
('2.6','公平比較 Mamba 與 Transformer',True,'要在有限主機上比較兩種架構的長序列表現。哪些紀錄不可省略？',[
('A','硬體、dtype、batch、輸入長度及量測階段','效能依賴硬體與工作負載，訓練與推論也不同。'),('B','只報理論複雜度就宣告所有任務勝出','理論階數不足以判定實際效能及品質。'),('C','任務品質、延遲／吞吐、記憶體與重複量測','需要同時衡量效益、成本與穩定性。'),('D','不同任務與不同品質要求下只比單一速度數字','不同條件下速度不能直接代表架構優劣。')],['A','C']),
]

INTERACTIONS=[
('1.1','ordering','bigram baseline 的實驗順序','依以下固定的 baseline 流程排序，再解釋為何不能把 held-out 文字放回計數。',
 ['切分訓練與 held-out 句子','只在訓練集統計句內 bigram','建立含明確平滑的條件機率','在 held-out 計算 NLL／PPL','比較基準並記錄限制'],
 '先固定資料切分，後續計數與機率估計只用訓練資料；平滑處理未見事件，最後在保留集量測。若先混入 held-out，指標便無法代表未知資料的表現。'),
('1.3','ordering','注意力輸出的資料流程','本題從已給定 Q、K、V 開始，依 scaled dot-product attention 的指定流程排序；遮罩加在縮放後、softmax 前。說明 V 在哪一步使用。',
 ['計算 QKᵀ 分數','除以 √d_k','套用可見範圍遮罩','逐列套用 softmax','以注意力權重乘 V'],
 '先取得 query 與 key 的相似度，再控制分數尺度與不可見位置。softmax 將每列轉成权重，最後加權 V 形成輸出。遮罩前後的代數等價變體不在本題指定流程內；V 是內容，不是用來產生相似度的 K。'),
('1.5','ordering','從 token 機率算 PPL','所有 token 機率都在 (0,1]，採自然對數。排序計算流程，並說明為何不能直接平均機率後取倒數。',
 ['取得每個正確 token 的條件機率','對各機率取負自然對數','將 NLL 加總並除以 token 數','對平均 NLL 取 exp'],
 'PPL=exp(−Σlog p_t／T)，使用的是負對數似然的平均。它等價於 token 機率幾何平均的倒數，不是算術平均的倒數；低機率事件在 NLL 中會形成較大的懲罰。'),
('2.2','matching','架構與注意力配置配對','配對三種典型架構與本題指定的注意力配置，再指出一個適合的任務。',
 {'encoder-only':'輸入內雙向 self-attention','decoder-only':'前綴內因果 self-attention','encoder-decoder':'encoder 表示加 decoder cross-attention'},
 'encoder-only 可利用完整輸入做表示與分類；decoder-only 依前綴生成；encoder-decoder 在生成端透過 cross-attention 讀取輸入表示，適合條件生成如翻譯。這是架構配置比較，不是宣告任務只能由一種架構完成。'),
('2.4','matching','cross-attention 張量來源配對','在典型 encoder-decoder 的 cross-attention 中，配對 Q／K／V 的來源，說明這如何連結輸入與生成。',
 {'Query Q':'decoder 當前隱藏表示的投影','Key K':'encoder 輸出用於匹配的投影','Value V':'encoder 輸出用於內容的投影'},
 '生成端用自己的隱藏表示形成 Q，對輸入端的 K 計算關聯，再加權輸入端的 V。K 與 V 都可來自 encoder 輸出，但投影矩陣与功能不同；不能因來源相同就假定 K=V。'),
('2.4','matching','去噪策略與恢复任務配對','依本題簡化策略描述，配對損壞方式與恢復任務，再說明其中一種適用的資料情境。',
 {'以 sentinel 取代連續 span':'生成被移除 span 並用 sentinel 分隔','打亂句子順序':'恢復原本句子的順序與內容','刪除部分 token':'由受損上下文重建原文'},
 'span corruption 常以特殊標記界定被移除片段，目標是恢復片段；句子打亂需要恢復文檔次序；刪除 token 需推斷缺失內容與位置。這些是教材去噪概念的簡化示例，實際 T5／BART 設定仍需核對各自完整輸入與目標格式。'),
('2.6','matching','狀態、選擇與測試時學習配對','配對三個概念與其功能，並解釋為何不能只憑名詞宣布效能優劣。',
 {'SSM 的狀態':'用遞迴更新攜帶歷史資訊','Mamba 的選擇':'讓部分狀態更新依賴當前輸入','TTT 的測試時學習':'用學習程序更新內部記憶'},
 'SSM 以狀態更新傳遞歷史，Mamba 引入輸入相依選擇，TTT 用測試時學習更新內部記憶。三者機制名稱不能直接推出任務品質或效能優劣，仍需固定工作負載並量測品質、延遲和資源。'),
('2.3','grid','BERT 的雙向可見範圍','三個非 padding 輸入 token 使用標準 BERT 雙向 self-attention。點選 3×3 Query／Key 矩陣：可看為 1，不可看為 0。說明它與 decoder 因果遮罩的差別。',
 [[1,1,1],[1,1,1],[1,1,1]],
 '三個位置都可看所有非 padding 輸入位置，所以矩陣全部為 1，包含自己。這描述 encoder 的輸入可見範圍，不代表 MLM 已遮罩 token 的原值直接作輸入；decoder 因果遮罩則禁止讀取後續位置。若有 padding，仍需另行遮掉。'),
]

def seed(connection,refresh=False):
    inserted=0
    records=[]
    for choice_index,(section,title,multiple,prompt,options,correct) in enumerate(CHOICES):
        options=list(options);random.Random(20261012+choice_index).shuffle(options)
        remap={old:'ABCD'[i] for i,(old,_,_) in enumerate(options)}
        correct=sorted(remap[key] for key in correct)
        options=[(remap[key],label,reason) for key,label,reason in options]
        payload={'options':[{'id':key,'label':label} for key,label,_ in options],'multiple':multiple}
        objective={'type':'choices' if multiple else 'choice','expected':correct if multiple else correct[0]}
        solution=f'正確答案：{"、".join(correct)}。\n'+ '\n'.join(f'{key}：{reason}' for key,_,reason in options)
        records.append((section,'selection',title,prompt+('（複選：選項全對才得操作分。）' if multiple else '（單選。）')+'請另外用自己的話說明理由。',payload,objective,solution))
    for section,kind,title,prompt,expected,solution in INTERACTIONS:
        payload={'cards':expected} if kind=='ordering' else {'left':list(expected),'right':list(expected.values())[::-1]} if kind=='matching' else {'rows':3,'columns':3}
        records.append((section,kind,title,prompt,payload,{'type':{'ordering':'order','matching':'mapping','grid':'grid'}[kind],'expected':expected},solution))
    for index,(section,kind,title,prompt,payload,objective,solution) in enumerate(records,1):
        if kind!='selection':solution='核准操作結果：'+encode(objective['expected'])+'\n'+solution
        qid=f'ZJU-EX-{index:03d}';vid=qid+'-v1'
        exists=connection.execute('SELECT 1 FROM questions WHERE id=?',(qid,)).fetchone()
        if exists:
            if not refresh:continue
            status=connection.execute('SELECT review_status FROM question_versions WHERE id=?',(vid,)).fetchone()
            if not status or status[0]!='draft' or connection.execute('SELECT 1 FROM assignment_items WHERE question_version_id=?',(vid,)).fetchone() or connection.execute('SELECT COUNT(*) FROM question_versions WHERE question_id=?',(qid,)).fetchone()[0]!=1:continue
        source=connection.execute('SELECT v.source_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE q.skill_id=? AND v.scope=? LIMIT 1',(section,'chapter_core')).fetchone()[0]
        sections,keywords,pages=SECTIONS[section]
        guide={'origin':'教材概念互動延伸','reference_answer':solution,'steps':['先辨認題目指定條件與可用資料。','完成選項／操作，核對每一項關係。','解釋機制、常見混淆，以及實際使用時的條件。'],'common_errors':['只背關鍵詞，沒有核對題目條件。','把某一指標或單一案例延伸成所有情境的保證。'],'practical_transfer':'可先以小型資料或矩陣實作驗證本題機制，再記錄基準、控制條件與限制。','reference_code':None,'reading':{'chapter':int(section[0]),'sections':sections,'keywords':keywords,'english_printed_pages':pages,'page_note':'書內頁碼；PDF 檔頁數可能含封面而不同。','repo_url':REPO},'authorship':'本系統原創教學題與詳解，概念依據第一／二章；仍待人工覆核。'}
        rubric={'version':1,'total_points':12,'requires_human_review':True,'criteria':[
            {'id':'operation','name':'選項／互動結果','points':6,'max_level':3,'levels':{'0':'未作答或結果不符合指定答案','1':'保留人工部分給分空間','2':'保留人工部分給分空間','3':'完整符合核准的選項／操作答案'}},
            {'id':'reasoning','name':'理解與理由','points':6,'max_level':3,'levels':{'0':'未說明或關鍵概念相矛盾','1':'只有名詞或存在關鍵錯誤','2':'核心機制正確但有小幅遺漏','3':'連結指定條件、核心機制與適用限制'}}]}
        answer={'expected_elements':[solution],'allow_equivalent_answers':True,'objective':objective,'teaching_guide':guide}
        metadata={'target_skill':section,'required_evidence':['核准的操作結果','有依據的概念說明'],'not_allowed_inference':['motivation','personality'],'status_note':'原創教學草稿，待人工覆核'}
        if not exists:connection.execute('INSERT INTO questions VALUES(?,?)',(qid,section))
        values=(vid,qid,1,title,kind,prompt,source,f'chapter {section[0]}, section {sections}; original exercise','chapter_core','standard',encode(payload),encode(answer),encode(rubric),encode(metadata),encode({'gpu_required':False,'practice':'browser_interaction','official_grading':'backend_rules_and_ai'}),'{}','draft',None,None)
        if exists:connection.execute('UPDATE question_versions SET payload_json=?,answer_json=?,rubric_json=? WHERE id=?',(encode(payload),encode(answer),encode(rubric),vid))
        else:connection.execute('INSERT INTO question_versions VALUES('+','.join('?' for _ in values)+')',values)
        inserted+=1
    return inserted

if __name__=='__main__':
    initialize()
    with db() as connection:print({'inserted_drafts':seed(connection)})
