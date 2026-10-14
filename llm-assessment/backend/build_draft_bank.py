"""Build an additive draft-only SQLite bank. Never approves or allocates questions."""
from pathlib import Path
import os
import hashlib
import json
import sqlite3
from explanations import guide

ROOT = Path(__file__).resolve().parents[2]
DB = Path(__file__).with_name('assessment.sqlite3')
def js(value):
    return json.dumps(value, ensure_ascii=False)

# section, kind, title, prompt, expected criteria. Original instructional questions.
ITEMS = [
('1.1','short_answer','n-gram 的取捨','比較 bigram 與 trigram 使用的上下文長度。為何較大的 n 可能增加零機率？提出一項改善及其取捨。',['bigram 看前一個 token，trigram 看前兩個','更長組合更稀疏，不代表真實語言不可能','平滑／回退可緩解零機率，但改變機率估計']),
('1.1','formula_puzzle','條件機率拼圖','已知 C(A)=8，C(A,B)=2。用卡片 C(A)、C(A,B)、除號拼出 P(B|A)，填入結果，解釋分母。',['C(A,B)/C(A)','結果 0.25','分母為條件 A 的次數']),
('1.1','python','bigram 計數實作','實作 bigram_counts(sentences)，sentences 為 token 串列的串列，回傳 tuple(token1,token2) 到次數的 dict。不得跨句配對。空資料回傳 {}。解釋如何驗證未跨句。',['只在各句相鄰 token 配對','重複配對累加，單 token／空句不產生配對','提出能抓出跨句錯誤的測試']),
('1.2','short_answer','RNN 如何保留上下文','說明 h_t=f(x_t,h_(t-1)) 中各項意義，及為何 RNN 的序列計算較難像 Transformer 訓練一樣平行。',['h_t 是當前隱藏狀態','當前輸入與前一狀態共同決定 h_t','時間步相依形成序列計算']),
('1.2','ordering','RNN 的一步計算','排序：取得 x_t；結合 h_(t-1) 計算 h_t；以 h_t 計算輸出分布；保存 h_t 供下一步。說明保存狀態的用途。',['取得輸入→更新狀態→輸出分布→保存狀態','下一步需要 h_t；接受保存與輸出在更新後的等價安排']),
('1.2','matching','teacher forcing 與生成','配對：訓練 teacher forcing／自由生成；候選輸入：前一步真實 token／前一步模型產生 token。指出兩者差異可能造成什麼問題。',['teacher forcing 使用真實前序 token','生成使用已產生 token','訓練與生成輸入差异可能使錯誤累積']),
('1.3','short_answer','訓練平行與生成循序','有人說 Transformer 可以平行，所以一次就能無條件產生所有未來 token。指出此說法的問題，區分訓練與一般自回歸生成。',['訓練已知序列可做位置平行計算','因果遮罩避免未來資訊洩漏','一般自回歸生成依賴前一步輸出']),
('1.3','ordering','注意力運算拼圖','對單頭 scaled dot-product attention 排序：QK^T；除以 sqrt(d_k)；套遮罩；沿 key 維做 softmax；乘 V。說明遮罩為何必須在 softmax 前影響 logits。',['QK^T→縮放→遮罩→softmax→乘V','遮罩位置不能取得注意力機率；遮罩／縮放可接受一致定義的等價安排']),
('1.3','python','注意力加權結果','實作 weighted_value(weights,values)，weights 是長度 n 的非負且和為 1 的串列；values 是 n×d 矩陣。回傳長度 d 加權向量；shape 不符或空輸入拋 ValueError。說明結果 shape。',['逐列以權重乘 value 再加總','回傳 d 維且檢查 shape','說明注意力權重與 value 的角色']),
('1.4','calculation','greedy 不一定最好','第一步 A=0.6、B=0.4；第二步 A→X=0.5、A→Y=0.5、B→X=0.9、B→Y=0.1。生成兩步。比較 greedy 與保留 A、B 兩條前綴的 beam size=2；第二步以聯合機率挑最高，平手依字母。',['greedy 選 AX，聯合機率 .30','BX 聯合機率 .36，比 AX 大','局部機率最大不保證序列最大']),
('1.4','selection','top-k／top-p 候選集合','候選 A=.50、B=.25、C=.15、D=.10。列出 top-k(k=2) 與 top-p(p=.80) 的最小累積候選集合；另解釋 temperature 上升通常如何改變分布。',['top-k 為 A,B','top-p 為 A,B,C，累積 .90','正溫度上升使 softmax 分布較平坦，不保證單次输出品質']),
('1.4','python','top-p 實作','實作 nucleus_indices(probs,p)。非空 probs 非負且和為 1；0<p<=1。依機率降序，同值按原索引，取累積機率首次 >=p 的最小前綴，回傳原索引。非法輸入拋 ValueError。',['穩定排序並保留原索引','包含跨過閾值的最後元素','驗證輸入及 p=1 邊界；不自行採樣']),
('1.5','calculation','困惑度計算','兩個正確目標 token 的預測機率為 .5 和 .25；用自然對數計算平均 NLL 與 perplexity，結果保留四位小數。說明機率降低時 PPL 如何改變。',['NLL=-(ln(.5)+ln(.25))/2≈1.0397','PPL=exp(NLL)≈2.8284','目標機率降低會提高 NLL/PPL']),
('1.5','short_answer','評測結論的界線','模型 A 的 PPL=10，B 的 PPL=12，但 tokenizer 不同。能否直接說 A 較好？若要評聊天品質，提出另兩項指標或評測方法。',['tokenization／資料／正規化条件需對齊','PPL 不能單獨代表聊天品質','可提出任務正确性、人工規準、幻覺／安全評量並說明用途']),
('1.5','python','PPL 小函式','實作 perplexity(probs)，非空且每項 0<p<=1，回傳 exp(-mean(log(p)))；非法輸入拋 ValueError。使用 math，避免直接連乘造成下溢。',['使用 log 平均再 exp','空輸入與零／負／超過1等值檢查','均勻機率 .5 的 PPL 為2']),
('2.1','short_answer','固定算力如何分配','在固定訓練算力下，為何不應只擴大參數量而完全忽略資料 token 數？用教材的規模法則討論，並說明其結論適用條件。',['參數與資料共同影響 loss','只加參數可能造成訓練資料不足','經驗規模法則依研究條件，不是所有任務通用保證']),
('2.1','calculation','Chinchilla 的訓練資料','教材 2.1.1 記載 Chinchilla 70B 參數、1.4T 訓練 tokens。計算 tokens/parameter。說明這個值是否為測試集大小，以及能否無條件套用到所有模型。',['1.4T/70B=20','是訓練 tokens 與參數比例，非測試集數量','屬特定 compute-optimal 研究條件，不是通用硬規則']),
('2.1','short_answer','能力提升如何驗證','某報告說模型規模加大後推理能力突然提升。提出至少兩項需要核對的條件及一個下一步實驗，避免只憑一條圖就下結論。',['核對資料、prompt、評測指標、測試集／污染等至少兩项','用固定條件的規模比較或更细粒度指標','說明觀察結果和因果推論差別']),
('2.2','matching','三種架構分類','將 BERT、T5、GPT 配對到 encoder-only、encoder-decoder、decoder-only。每種寫一個典型訓練目標。',['BERT encoder-only／MLM','T5 encoder-decoder／span corruption text-to-text','GPT decoder-only／next-token prediction']),
('2.2','short_answer','任務選型與限制','要做句子分類與自由文字續寫，分別提出一個典型架構選擇並解釋。說明為何這不代表其他架構絕對做不到。',['encoder-only 適合分類表示；decoder-only 適合自回歸續寫','任務目標／注意力形式說明合理','架構只是典型適配，訓練與介面也影响能力']),
('2.2','matching','注意力可見範圍','配對：BERT encoder self-attention／自回歸 decoder self-attention／encoder-decoder cross-attention；候選：輸入雙向／生成前綴含當前位置／decoder query 看 encoder 表示。',['BERT 輸入雙向','自回歸 decoder 因果前綴','cross-attention query 來自 decoder，key/value 來自 encoder']),
('2.3','short_answer','MLM 的監督訊號','輸入「我 喜歡 [MASK]」，遮罩位置原詞為「閱讀」。MLM 的預測目標是什麼？為何不能把它等同一般 GPT next-token 目標？',['恢復遮罩位置原 token','MLM 利用雙向可見上下文','next-token 依前綴預測下一位置，目標／可見範圍不同']),
('2.3','selection','BERT 概念辨錯','判斷並說明：「BERT 使用雙向上下文，所以推論時必須預先知道題目的正確標籤。」',['說法錯誤','雙向指輸入 token 的上下文可見範圍','下游標籤不是輸入上下文的必要部分']),
('2.3','short_answer','分類模型的驗證','以 BERT 做情感分類，訓練準確率高、測試低。提出兩種可能原因與一個優先驗證步驟，不能直接宣布一定是過擬合。',['可討論過擬合／資料分布／切分／標註／洩漏等至少两项','驗證步驟針對所提原因','区分假設與已證明原因']),
('2.4','matching','cross-attention 的來源','Encoder-decoder 的 cross-attention 中，將 Q、K、V 配對至 decoder 中間表示或 encoder 輸出，並說明作用。',['Q 來自 decoder','K、V 來自 encoder','輸出生成時取用輸入表示']),
('2.4','short_answer','T5 與 BART 的去噪','以教材為範圍，比較 T5 的 span corruption 與 BART 的去噪重建。描述輸入損壞與恢復目標，指出兩者共有的架構。',['T5 可用 sentinel 替換 spans 並生成缺失片段','BART 以損壞文本重建原始文本','兩者為 encoder-decoder；不需背所有損壞策略']),
('2.4','ordering','翻譯資料流','排列：來源句子 token→encoder 表示→decoder 使用目標前綴與 cross-attention→下一個目標 token。說明哪個部分不得看未來目標答案。',['資料流符合 encoder-decoder','decoder 自注意力須阻擋未來目標 token','來源句子可完整提供']),
('2.5','short_answer','decoder-only 的訓練目標','序列 [BOS,A,B,EOS] 以 next-token prediction 訓練，列出輸入及目標配對；說明 padding 通常如何處理。',['輸入 [BOS,A,B]，目標 [A,B,EOS]','預測下一位置而非重建當前位置','padding 應排除或 mask 掉對應 loss']),
('2.5','grid','因果遮罩矩陣','序列長度3，列為 query、欄為 key，1=可看。填入含對角線的標準 causal mask，解釋 (第1列,第3欄) 值。',['矩陣 [[1,0,0],[1,1,0],[1,1,1]]','第一位置不可看第三位置，避免未來資訊']),
('2.5','python','next-token 配對實作','實作 next_token_pairs(tokens)，長度>=2 回傳 (tokens[:-1],tokens[1:])，較短回傳 ([],[])。不修改原串列。說明這個函式尚未處理哪項訓練细節。',['正確位移與邊界','不改動輸入','尚未處理 padding／loss mask／batch 等合理細節']),
('2.6','short_answer','SSM 的狀態','用直觀方式說明 SSM 以狀態摘要處理序列，與直接建立全序列 token-pair attention 的差異。提出一項應實測的取捨。',['前序資訊由狀態更新攜帶','不等同每一步顯式計算所有 token 對','可比較長序列效率與品質，不能僅由複雜度判斷勝負']),
('2.6','calculation','簡化狀態更新','教學用標量模型 h_t=.5*h_(t-1)+x_t，y_t=h_t，h_0=0，x=[2,0,2]。列出 h_1..h_3；解釋此小模型為何不等於完整 Mamba。',['h=[2,1,2.5]','狀態保留衰減的先前輸入','未含 Mamba 的輸入相依選擇等完整機制']),
('2.6','matching','Mamba 與 TTT','配對：Mamba 的選擇機制／TTT 的 test-time 更新；候選：使狀態更新依賴輸入／以測試時學習更新隱藏記憶。說明不能只靠兩個名詞判斷哪個更好。',['Mamba 為輸入相依選擇','TTT 在測試時以學習更新內部記憶','需相同任務、條件、品質與資源評測']),
]

# Reading and improvement tasks are deliberately multi-solution, never labelled own experiments.
CASES = [
('2.1','case_proposal','Chinchilla 案例：讀懂比例後規劃','使用教材 2.1.1 的 70B 參數／1.4T tokens 案例。先算比值；再針對一個資料 token 明顯不足、但算力固定的模型提出下一步改善實驗。請寫觀察、原因假設、方案、固定條件、比較基準、成功與失敗判準。',['比值20且正确辨識訓練資料','方案優先回應資料／參數配置问题且不把20當必然最优','在固定算力下比较合理配置并追蹤 held-out loss 與成本']),
('1.4','case_proposal','教材搜尋樹：改善生成策略','引用 ch1 1.4 的搜尋樹例：greedy 路徑機率 .03，另一候選 .10。先算倍數並解釋局部／序列機率；接著為開放故事生成提出改善方案。請說明為何最高機率未必是最佳故事，以及要如何驗證方案。',['.10/.03≈3.33；識別局部最佳问题','可選 beam／top-p／temperature 等並說明目的與代價','固定模型、prompt、長度及多個 seed；衡量重複、多樣性與内容品質']),
('1.5','case_proposal','PPL 與任務品質：下一步評測','教材 1.5 區分內部與外部評測。假設案例模型的 PPL 改善，但使用者仍反映答案不可靠；此情境為教學假設，非論文實測。提出下一步排查／改善方案與驗證方式，至少列出兩個競爭假設。',['PPL 与任務可靠性不是同一衡量','提出至少两個可区分假設及針對性方案','固定測試集与基準，用事實正確性等直接指标并定義失败']),
('2.3','case_proposal','BERT 案例的對照實驗設計','依 ch2 的 BERT 與衍生模型案例，自行提出一個你要核對的訓練設定差異，例如預訓練資料、訓練步數或目標。先定位教材段落；再設計受文書機／有限主機算力限制的縮小實驗。不要捏造原論文數字。',['定位来源并区分已知與待查','一次聚焦有機制理由的因素，控制其他差異','縮小实验、資源估计、baseline 与指标明确；不將小规模结果当原论文本体']),
('2.4','case_proposal','T5／BART：去噪方案改進','閱讀教材 2.4 的去噪案例。選一種損壞策略，指出適合或不適合的資料情境；提出改變策略的下一步實驗，寫出你的預期、可能副作用與驗證指標。',['准确说明选定策略与恢复目标','改善基于数据情境并讨论代价／替代解释','对照策略固定数据／预算，使用重建及下游指标；说明预期未出现如何处理']),
('2.6','case_proposal','Mamba／Transformer：公平比較','閱讀教材 2.6 的 SSM／Mamba 案例。有人僅以長序列複雜度較低就宣布全面勝過 Transformer。提出一個公平且能在本機有限資源下進行的比較方案，列出預期與可能失敗條件。',['识别理论复杂度与实际性能差别','固定任务／输入长度／dtype／硬件／batch，区分训练与推论','比较质量、吞吐、延迟、内存，重复测量并处理负面结果']),
]

CASES += [
('2.3','case_proposal','BERT Table 5：不是所有改動都改善','原論文 Table 5 的 SQuAD dev F1：BERT_BASE=88.5；No NSP=87.9；LTR & No NSP=77.8；在 LTR & No NSP 上加 BiLSTM=84.9。先計算 BiLSTM 改善幅度及與 BERT_BASE 的差距；再解釋哪些對比改變了不只一項因素。提出下一步對照實驗、機制假設、成本及失敗判準。',['84.9-77.8=7.1 F1 點；仍比88.5低3.6點，不是相對百分比','辨識 BERT_BASE 與 LTR & No NSP 同時改變目標／方向及 NSP，不把下降全歸於 NSP','採受控對照，固定資料／預算／微調設定並重複seed，記錄 QA 與其他任務效果']),
('2.1','case_proposal','Chinchilla 原論文：改善結論的限制','依原論文 §4.2.1，WikiText-103 PPL：Gopher 7.75、Chinchilla 7.16；作者指出 Chinchilla 訓練資料量較大，train/test leakage 可能影響語言模型評測。計算相對下降；說明能否把改善全部歸因於模型／資料比例。提出下一步驗證，處理污染及其他訓練設定差異。',['PPL 相對下降=(7.75-7.16)/7.75≈7.61%，不等同任務準確率提升','相同算力仍有資料量、優化器／tokenizer等差異，區分觀察與原因','去污染held-out／匹配訓練設定／多任務對照，定義指標、預算及否定假設條件']),
]
REMOTE_CASE_SOURCES = {
 'BERT Table 5：不是所有改動都改善': {'id':'bert-table5','url':'https://aclanthology.org/N19-1423.pdf','locator':'Table 5; section 5.1; PDF page 8','data':{'task':'SQuAD dev','metric':'F1','BERT_BASE':88.5,'No NSP':87.9,'LTR & No NSP':77.8,'LTR & No NSP + BiLSTM':84.9}},
 'Chinchilla 原論文：改善結論的限制': {'id':'chinchilla-ppl','url':'https://arxiv.org/html/2203.15556v1','locator':'section 4.2.1; section 4.1','data':{'task':'WikiText-103','metric':'perplexity','Gopher':7.75,'Chinchilla':7.16,'limitation':'Authors discuss train/test leakage; section 4.1 lists optimizer and tokenizer differences'}},
}
SECTIONS = ['1.1','1.2','1.3','1.4','1.5','2.1','2.2','2.3','2.4','2.5','2.6']
BOOK = Path(os.environ.get('ASSESSMENT_SOURCE_DIR', str(ROOT/'Foundations-of-LLMs')))
if not BOOK.is_dir():
    raise SystemExit('找不到 ZJU 教材。請先 clone Foundations-of-LLMs，或設定 ASSESSMENT_SOURCE_DIR 指向該資料夾。')
SOURCE_PATHS = {
 'ch1': next((BOOK).rglob('第1章 *.pdf')),
 'ch2': next((BOOK).rglob('第2章 *.pdf')),
 'english': next((BOOK/'Foundations_of_LLMs(English_version)').glob('*.pdf')),
 'papers': BOOK/'大模型经典论文列表/readme.md',
 'analysis_spec': Path(__file__).resolve().parents[1]/'planning/HOMEWORK_ANALYSIS_LITERATURE_AND_ALGORITHM.md',
}

conn = sqlite3.connect(DB)
conn.execute('PRAGMA foreign_keys=ON')
conn.executescript('''
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT NOT NULL,content BLOB NOT NULL,content_kind TEXT NOT NULL,source_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skills(id TEXT PRIMARY KEY,section TEXT NOT NULL,prerequisites_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,skill_id TEXT NOT NULL REFERENCES skills(id));
CREATE TABLE IF NOT EXISTS question_versions(
 id TEXT PRIMARY KEY,question_id TEXT NOT NULL REFERENCES questions(id),version INTEGER NOT NULL,
 title TEXT NOT NULL,kind TEXT NOT NULL,prompt TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES sources(id),
 source_locator TEXT NOT NULL,scope TEXT NOT NULL,difficulty_design TEXT NOT NULL,
 payload_json TEXT NOT NULL,answer_json TEXT NOT NULL,rubric_json TEXT NOT NULL,analysis_metadata_json TEXT NOT NULL,
 runtime_json TEXT NOT NULL,tests_json TEXT NOT NULL,review_status TEXT NOT NULL CHECK(review_status IN ('draft','approved','rejected')),
 reviewed_by TEXT,reviewed_at TEXT,UNIQUE(question_id,version));
CREATE TABLE IF NOT EXISTS analysis_rules(id TEXT PRIMARY KEY,version INTEGER NOT NULL,spec_json TEXT NOT NULL,review_status TEXT NOT NULL CHECK(review_status IN ('draft','approved','rejected')));
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,version INTEGER NOT NULL,content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,role TEXT NOT NULL CHECK(role IN ('admin','learner')),display_name TEXT NOT NULL,password_hash TEXT);
CREATE TABLE IF NOT EXISTS learners(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),external_mapping_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES users(id),mode TEXT NOT NULL CHECK(mode IN ('practice','assessment')),status TEXT NOT NULL,settings_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignment_items(assignment_id TEXT REFERENCES assignments(id),question_version_id TEXT REFERENCES question_versions(id),position INTEGER NOT NULL,points REAL NOT NULL CHECK(points>=0),PRIMARY KEY(assignment_id,position));
CREATE TABLE IF NOT EXISTS assignment_recipients(assignment_id TEXT REFERENCES assignments(id),learner_id TEXT REFERENCES learners(id),PRIMARY KEY(assignment_id,learner_id));
CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,assignment_id TEXT NOT NULL REFERENCES assignments(id),learner_id TEXT NOT NULL REFERENCES learners(id),status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES submissions(id),context_json TEXT NOT NULL,snapshot_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS responses(id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES attempts(id),question_version_id TEXT NOT NULL REFERENCES question_versions(id),response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS interaction_events(id TEXT PRIMARY KEY,response_id TEXT NOT NULL REFERENCES responses(id),event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis_jobs(id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL REFERENCES attempts(id),input_hash TEXT NOT NULL,analyzer_version TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('queued','running','draft_ready','failed')),UNIQUE(attempt_id,input_hash,analyzer_version));
CREATE TABLE IF NOT EXISTS analysis_runs(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES analysis_jobs(id),provenance_json TEXT NOT NULL,result_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_findings(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES analysis_runs(id),response_id TEXT NOT NULL REFERENCES responses(id),finding_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_decisions(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES analysis_runs(id),reviewer_id TEXT NOT NULL REFERENCES users(id),decision_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS published_reports(id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES submissions(id),review_decision_id TEXT NOT NULL REFERENCES review_decisions(id),report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recommendations(id TEXT PRIMARY KEY,learner_id TEXT NOT NULL REFERENCES learners(id),question_version_id TEXT NOT NULL REFERENCES question_versions(id),reason_json TEXT NOT NULL,review_status TEXT NOT NULL);
''')

for key,path in SOURCE_PATHS.items():
    data=path.read_bytes()
    # A new source snapshot ID, rather than rewriting content used by an older question.
    digest=hashlib.sha256(data).hexdigest()
    source_id=f'{key}-{digest[:12]}'
    conn.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?)',(source_id,str(path),digest,data,path.suffix,'local_snapshot'))
    SOURCE_PATHS[key]=source_id
for case in REMOTE_CASE_SOURCES.values():
    data=js(case['data']).encode('utf-8')
    conn.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?)',(case['id'],case['url'],hashlib.sha256(data).hexdigest(),data,'verified_numeric_extract','primary_source_checked_2026-10-12'))
for i,sec in enumerate(SECTIONS):
    prereq = {'1.2':['1.1'],'1.3':['1.2'],'1.4':['1.1','1.3'],'1.5':['1.1'],'2.1':['1.5'],'2.2':['1.3'],'2.3':['2.2'],'2.4':['2.2'],'2.5':['2.2'],'2.6':['1.2','2.2']}.get(sec,[])
    conn.execute('INSERT OR IGNORE INTO skills VALUES(?,?,?)',(sec,sec,js(prereq)))

TESTS = {
 'bigram 計數實作': {'function':'bigram_counts','public':[{'args':[[['a','b','a'],['a','b']]],'expected':[[['a','b'],2],[['b','a'],1]],'encoding':'tuple_key_pairs'}], 'hidden':[{'args':[[['x'],['y']]],'expected':[],'encoding':'tuple_key_pairs'},{'args':[[]],'expected':[],'encoding':'tuple_key_pairs'}]},
 '注意力加權結果': {'function':'weighted_value','public':[{'args':[[.25,.75],[[2,0],[0,4]]],'expected':[.5,3]}],'hidden':[{'args':[[1],[[2,3]]],'expected':[2,3]},{'args':[[1],[[1],[2]]],'raises':'ValueError'},{'args':[[],[]],'raises':'ValueError'}],'abs_tol':1e-6},
 'top-p 實作': {'function':'nucleus_indices','public':[{'args':[[.5,.25,.15,.1],.8],'expected':[0,1,2]}],'hidden':[{'args':[[.5,.5],.5],'expected':[0]},{'args':[[.2,.8],1],'expected':[1,0]},{'args':[[],.5],'raises':'ValueError'},{'args':[[1],0],'raises':'ValueError'}]},
 'PPL 小函式': {'function':'perplexity','public':[{'args':[[.5,.25]],'expected':2.8284271247461903}],'hidden':[{'args':[[.5,.5]],'expected':2},{'args':[[]],'raises':'ValueError'},{'args':[[0]],'raises':'ValueError'},{'args':[[1.1]],'raises':'ValueError'}],'abs_tol':1e-6},
 'next-token 配對實作': {'function':'next_token_pairs','public':[{'args':[['BOS','A','B','EOS']],'expected':[['BOS','A','B'],['A','B','EOS']],'encoding':'tuple_as_array'}],'hidden':[{'args':[[]],'expected':[[],[]],'encoding':'tuple_as_array'},{'args':[['a']],'expected':[[],[]],'encoding':'tuple_as_array'}],'mutation_check':True},
}
PAYLOADS = {
 '條件機率拼圖':{'cards':['C(A)','C(A,B)','/'],'slots':['numerator','operator','denominator'],'counts':{'A':8,'AB':2}},
 'RNN 的一步計算':{'cards':['input','state_update','output_distribution','save_state'],'valid_order_constraints':[['input','state_update'],['state_update','output_distribution'],['state_update','save_state']]},
 'teacher forcing 與生成':{'left':['teacher_forcing','generation'],'right':['ground_truth_previous','generated_previous']},
 '注意力運算拼圖':{'cards':['qk','scale','mask','softmax','value'],'shape_note':'single_head; softmax over keys'},
 'top-k／top-p 候選集合':{'candidates':{'A':.5,'B':.25,'C':.15,'D':.1},'k':2,'p':.8},
 '三種架構分類':{'left':['BERT','T5','GPT'],'right':['encoder-only','encoder-decoder','decoder-only']},
 '注意力可見範圍':{'left':['bert_self','causal_self','cross'],'right':['bidirectional_input','prefix','encoder_memory']},
 'cross-attention 的來源':{'left':['Q','K','V'],'right':['decoder','encoder'],'reuse_right':True},
 '翻譯資料流':{'cards':['source_tokens','encoder_states','decoder_prefix_and_cross_attention','next_target']},
 '因果遮罩矩陣':{'rows':3,'columns':3,'row_role':'query','column_role':'key','allowed_values':[0,1]},
 'Mamba 與 TTT':{'left':['Mamba','TTT'],'right':['input_dependent_selection','test_time_learning']},
}

def rubric(criteria,proposal=False):
    if proposal:
        entries=[('case_understanding','案例解讀',criteria[0]),('mechanism_feasibility','改善機制與可行性',criteria[1]),('validation','驗證設計',criteria[2])]
        extra=[('problem','問題辨識與優先順序','指出證據支持的問題／限制，區分替代解釋並說明優先處理理由'),('limits','取捨與失敗判準','指出至少一項資源／品質代價，定義何時方案不成立及如何回應')]
        entries+=extra
    else:
        entries=[(f'criterion_{i+1}',f'要點{i+1}',c) for i,c in enumerate(criteria)]
    return {'version':1,'requires_human_review':True,'total_points':12,'criteria':[{'id':key,'name':name,'points':12/len(entries),'max_level':3,'levels':{'0':f'未展現「{anchor}」或明确相矛盾','1':f'觸及「{anchor}」，但關鍵关系错误或明显不完整','2':f'基本符合「{anchor}」，有小幅遺漏但不改變主要結論','3':f'完整符合「{anchor}」，且呈現本題要求的說明／證據'}} for key,name,anchor in entries]}

with conn:
    for i,(sec,kind,title,prompt,criteria) in enumerate(ITEMS+CASES,1):
        qid=f'ZJU-{i:03d}'
        proposal=kind=='case_proposal'
        scope='case_reading_and_improvement' if proposal else ('extension' if kind=='python' else 'chapter_core')
        conn.execute('INSERT OR IGNORE INTO questions VALUES(?,?)',(qid,sec))
        metadata={'target_skill':sec,'required_evidence':criteria,'not_allowed_inference':['motivation','personality','psychometric_score'],'rules':['LLM-CONCEPT','LLM-COMPLETE','LLM-REASON'],'proposal_required':proposal,'case_origin':'others_published_material' if proposal else None,'status_note':'題干、正解、規準、測試均待管理者人工覆核','hint':'先列出題目要求、已知資訊及成立條件，再作答。','hint_status':'draft','alternative_explanations':['題意未理解','操作失誤','表達省略','支援條件不同']}
        runtime={'gpu_required':False,'practice':'browser_python_worker' if kind=='python' else 'browser_interaction','official_grading':'isolated_backend_runner_and_human_review' if kind=='python' else 'backend_rules_or_llm_draft_and_human_review','packages':['stdlib'],'budget_design':{'cpu_seconds':3,'memory_mb':256} if kind=='python' else None}
        source=REMOTE_CASE_SOURCES.get(title)
        payload=PAYLOADS.get(title,{'response':'structured_text'})
        if proposal:
            payload={'response':'case_proposal','fields':['observation','problem_and_alternatives','improvement_and_mechanism','validation_baseline_controls_metrics','constraints_and_failure'],'reference_data':source['data'] if source else None}
        locator=source['locator'] if source else f'section {sec}; case specifics in prompt'
        values=(f'{qid}-v1',qid,1,title,kind,prompt,source['id'] if source else SOURCE_PATHS[f'ch{sec[0]}'],locator,scope,'standard' if kind!='case_proposal' else 'advanced',js(payload),js({'expected_elements':criteria,'allow_equivalent_answers':True,'unique_solution':not proposal,'teaching_guide':guide(title,sec,kind,locator)}),js(rubric(criteria,proposal)),js(metadata),js(runtime),js(TESTS.get(title,{})),'draft',None,None)
        conn.execute('INSERT OR IGNORE INTO question_versions VALUES('+','.join(['?']*len(values))+')',values)
        old=conn.execute('SELECT answer_json,review_status FROM question_versions WHERE id=?',(f'{qid}-v1',)).fetchone()
        answer=json.loads(old[0])
        if old[1]=='draft' and 'teaching_guide' not in answer:
            answer['teaching_guide']=guide(title,sec,kind,locator)
            conn.execute('UPDATE question_versions SET answer_json=? WHERE id=?',(js(answer),f'{qid}-v1'))
    rules={
      'LLM-CONCEPT':'明确主張與核准概念矛盾；引用原句并保留操作／表达替代解释',
      'LLM-COMPLETE':'題干明确要求的部分未展現；区分未作答与无法解析',
      'LLM-CONDITION':'结论缺少题目要求的条件；列出适用界线',
      'LLM-REASON':'答案未呈現必要推理連結；不能只比關鍵字',
      'LLM-FORMULA':'可定位的分母、shape、量纲或数值错误',
      'LLM-IMPLEMENT':'定位失败测试，区分环境失败与代码问题',
      'LLM-MONITOR':'存在未处理的前后矛盾；不推断心理状态',
      'LLM-REVISION':'修订回应原缺口；不代表已能独立迁移',
    }
    for key,description in rules.items():
        conn.execute('INSERT OR IGNORE INTO analysis_rules VALUES(?,?,?,?)',(key,1,js({'activation':description,'evidence_required':True,'origin':'project_design_adapted_from_existing_analysis_spec','requires_review':True}),'draft'))
    path=Path(__file__).resolve().parents[1]/'planning/LLM互動評量網站規劃.md'
    conn.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?)',('planning-v1','LLM互動評量網站規劃',1,path.read_text(encoding='utf-8')))

from extra_bank import seed
with conn:seed(conn)
from storage import initialize
initialize()
conn.row_factory=sqlite3.Row
from revise_bank import apply
with conn:apply(conn)
from collab_bank import seed as seed_canvas
with conn:seed_canvas(conn)
assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert not conn.execute('PRAGMA foreign_key_check').fetchall()
print(js({'database':str(DB),'draft_questions':conn.execute('SELECT count(*) FROM question_versions').fetchone()[0],'case_proposals':conn.execute("SELECT count(*) FROM question_versions WHERE kind='case_proposal'").fetchone()[0],'integrity':'ok','assigned':conn.execute('SELECT count(*) FROM assignment_recipients').fetchone()[0]}))
conn.close()
