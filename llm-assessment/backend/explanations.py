"""Original teaching guides anchored to ZJU chapters 1–2, stored privately in SQLite."""
REPO='https://github.com/ZJU-LLMs/Foundations-of-LLMs'
SECTIONS={
 '1.1':('1.1.1–1.1.2','n-gram、條件機率、頻次估計','3–6'),
 '1.2':('1.2.1–1.2.2','RNN、隱藏狀態、teacher forcing','8–13'),
 '1.3':('1.3.1–1.3.2','scaled dot-product attention、因果遮罩','15–20'),
 '1.4':('1.4.1–1.4.2','greedy、beam search、top-k、top-p、temperature','22–27'),
 '1.5':('1.5.1–1.5.2','NLL、perplexity、內部與外部評測','28–35'),
 '2.1':('2.1.1–2.1.2','scaling laws、Chinchilla、能力評測','40–47'),
 '2.2':('2.2.1–2.2.2','三種 Transformer 架構與任務','49–54'),
 '2.3':('2.3.1–2.3.3','BERT、MLM、預訓練與下游任務','55–69'),
 '2.4':('2.4.1–2.4.3','cross-attention、T5、BART、去噪','70–78'),
 '2.5':('2.5.1–2.5.2','decoder-only、GPT、next-token prediction','79–91'),
 '2.6':('2.6.1–2.6.2','SSM、Mamba、TTT、狀態更新','100–113'),
}
# Each tuple is (worked reference answer, reasoning steps, likely errors, practical transfer).
GUIDES={
'n-gram 的取捨':('bigram 用前一個 token 估計下一個，trigram 用前兩個。上下文增加後，可能的組合數快速成長；有限語料中很多組合沒出現，最大概似估計便給零機率。這只是沒有觀察到，不表示語言上不可能。可用加性平滑或 backoff；前者分配部分機率給未見事件，後者回退到較短上下文。代價是估計偏差、超參數與機率重新分配。','先寫出兩種模型的條件；再考慮固定語料下未見組合；最後比較改善及代價。','把未見過等同不可能；只說增加語料但不處理測試時未見組合。','實作 bigram baseline，保留 held-out 句子，比較平滑前後零機率數與 NLL。'),
'條件機率拼圖':('卡片順序為 C(A,B) → / → C(A)。P(B|A)=2/8=0.25。已知 A 出現，樣本空間限制在 A 的 8 次出現，其中 2 次下一個是 B；因此分母是 C(A)，不是 C(B) 或所有 token 數。','辨認條件是 A；把聯合頻次放分子；除以條件頻次；檢查機率在 0–1。','分子分母倒置；把 P(A|B) 當 P(B|A)；C(A)=0 時直接除。','從 bigram 計數建立條件分布，檢查每個前綴的下一詞機率總和。'),
'bigram 計數實作':('對每句分別遍歷相鄰兩個 token，以 tuple 作為 dict key，遇到重複配對累加。不能先把所有句子攤平成一串，否則會把前句尾與後句頭配成不存在的 bigram。空資料、空句與單 token 句都不產生配對。','以句子為外層迴圈；zip(sentence, sentence[1:]) 產生相鄰對；用 dict.get 累加；以兩個單詞句檢查跨句錯誤。','flatten 後計數；覆蓋而未累加；使用不可雜湊 list 當 key。','這是統計語言模型資料管線的第一步；再做前綴計數與平滑。'),
'RNN 如何保留上下文':('x_t 是当前輸入表示，h_(t-1) 是先前序列摘要，h_t 是讀入 x_t 後的新狀態。f 通常含可學權重及非線性，例如 tanh(W_x x_t + W_h h_(t-1)+b)。同一序列的 h_t 依賴 h_(t-1)，因此無法直接同時計算所有時間步。不同序列仍可 batch；Transformer 訓練時利用已知序列和矩陣注意力平行處理位置。','先標示輸入、舊狀態、新狀態；畫出時間步相依；區分序列內與 batch 平行。','說 RNN 完全不能平行；把隱藏狀態等同原文完整儲存。','寫一個三步狀態更新迴圈，記錄每步輸入、狀態及 shape。'),
'RNN 的一步計算':('取得 x_t → 用 x_t 與 h_(t-1) 更新 h_t → 由 h_t 計算輸出分布 → 保留 h_t。更新後，輸出與保存狀態互換順序也合理，只要輸出使用新狀態，下一步取得 h_t。保存讓先前資訊能影響後續預測；開始新句時應按設定重設狀態。','先找更新所需輸入；輸出與保存都依赖已算好的 h_t；检查新句狀態初始化。','未更新就輸出；每步重設 h，導致失去上下文；不同句無意共享狀態。','在日志中比較重設與保留狀態後同一 token 的不同輸出。'),
'teacher forcing 與生成':('teacher forcing 的下一步輸入來自資料中的真實前序 token；自由生成的下一步輸入來自模型剛產生的 token。模型訓練時多看到正確前綴，推論時可能看到自身錯誤，造成分布差異與錯誤累積（exposure bias）。這是可能問題，不表示每段生成都必然崩壞。','分開畫訓練與推論資料流；確認下一步 token 的來源；追蹤一次錯誤如何改變後續前綴。','把訓練目標 token 提前餵給同一位置；宣稱 teacher forcing 直接解決錯誤累積。','用同一模型比較 gold-prefix 與 generated-prefix 的逐步 loss 或錯誤率。'),
'訓練平行與生成循序':('訓練時整段輸入已知，可把不同位置的表示放入矩陣運算；因果遮罩阻止每個位置使用未來目標。一般自回歸生成先得到第一個新 token，再將它接回前綴產生下一個。因此訓練的位置平行，不等於一次知道所有尚未生成的 token。KV cache 可減少重算，但不移除這項依賴。','分別列出訓練和推論已知的資訊；說明遮罩作用；檢查生成迴圈逐步追加前綴。','把矩陣平行等同未來答案可見；認為 KV cache 使 token 完全獨立。','實作簡單 generate 迴圈，記錄每步前綴長度與產生的 token。'),
'注意力運算拼圖':('QKᵀ → 除以 sqrt(d_k) → 遮罩禁止位置 → 沿 key 維 softmax → 乘 V。遮罩通常將禁止位置 logits 設為負無限，softmax 後權重為零。若 softmax 後才直接清零而不重新正規化，權重和可能不為 1。遮罩與縮放採一致定義時可有等價安排，但遮罩要在正規化前生效。','檢查 QKᵀ shape 為 query×key；縮放控制 logits 尺度；按每個 query 正規化；以權重合成 value。','沿 query 維 softmax；mask 用 0 代替負無限；把 V 當作權重。','用長度 3 的矩陣驗證未來位置權重為 0、每列權重和為 1。'),
'注意力加權結果':('輸出第 j 維為 Σ_i weights[i] × values[i][j]。題例 [0.25,0.75] 與 [[2,0],[0,4]] 得 [0.5,3]；輸入 n×d 的 values，輸出 d 維。先檢查 n 與列數一致、每列維度一致且非空，再檢查權重有限、非負且總和接近 1。','核對 n、d；建立 d 個零；按列累加每個維度；測試單列、shape 錯誤與空輸入。','沿錯維度加總；只處理第一列；用嚴格 float 相等驗證權重總和。','這是 attention 的 weighted-sum 核心，不需要下載大型模型。'),
'greedy 不一定最好':('greedy 第一步選 A=0.6，第二步 A→X 與 A→Y 平手，依字母選 X，AX=.6×.5=.30。保留 A、B 後四條路徑是 AX=.30、AY=.30、BX=.36、BY=.04，因此最高是 BX。第一步 B 較低，但後續條件機率讓整條序列較高。','列出全部兩步路徑；乘上條件機率；依序列機率排序；比較 greedy。','直接把兩步機率相加；以第二步 .9 當整條序列機率；忽略平手規則。','先窮舉小搜尋樹驗證 beam；長序列改用 log 機率加總，避免下溢。'),
'top-k／top-p 候選集合':('top-k(k=2) 保留 A、B。top-p(p=.8) 降序累積為 .50、.75、.90，所以最小達標前綴是 A、B、C。temperature 用 logits/T 再 softmax；正溫度提高通常讓分布更平坦。候選截斷後採樣要重新正規化；較高溫度不保證單次內容品質更好。','按機率排序；分別套固定數目與累積門檻；包含首次跨過門檻的元素。','top-p 只保留累積小於門檻的元素；把 p 當候選數；直接改機率卻不正規化。','固定模型與 prompts，比較候選數、重複率和任務成功率。'),
'top-p 實作':('保留原索引，按 (-機率,原索引) 排序，逐項累加並納入首次達到 p 的元素。題例得到 [0,1,2]；[.5,.5],p=.5 得 [0]；p=1 應取完整前綴。要驗證非空、有限非負、機率和約為 1，以及 0<p<=1。函式只選集合，不實際抽樣。','先驗證；穩定排序；先加入候選再判斷累積；以小容差處理浮點邊界。','先判斷再加入導致漏掉最後項；回傳排序後位置而不是原索引。','把它接到簡單 token 抽樣函式，分開測試截斷與隨機採樣。'),
'困惑度計算':('NLL=-(ln(.5)+ln(.25))/2=1.0397207708，四位小數為 1.0397。PPL=exp(NLL)=2.8284271247，四位小數為 2.8284。目標 token 的機率下降時，負對數損失增加，因此同條件下 PPL 增加。先以未四捨五入的 NLL 計算 PPL，再各自呈現。','對每個正確目標機率取 log；取負平均；exp；最後才四捨五入。','取所有候選機率平均；忘記負號；把 PPL 當準確率百分比。','比較兩組目標 token 機率，驗證 PPL 對低機率錯誤的敏感性。'),
'評測結論的界線':('不同 tokenizer 會改變 token 數與單位，PPL=10 與 12 不宜直接宣布前者更好。需對齊資料、tokenization、context、loss mask 與正規化。聊天品質另看任務正確性與事實支持度，例如可驗證 QA 的正確率、引用支持率，加上盲評規準判斷相關性與完整性。安全評測也可納入，但不是單靠 PPL 得出。','先檢查可比條件；區分語言預測與下游品質；指定能直接反映產品需求的測試。','跨 tokenizer 排名；只說人工覺得好而無盲評規準。','建立固定 prompts、版本與分項規準的小型離線評測集。'),
'PPL 小函式':('逐項驗證 0<p<=1，求 log(p) 的平均後取負並 exp。使用 log 避免直接連乘許多小數下溢；全是 .5 的 PPL 是 2，全是 1 的 PPL 是 1。非法資料應明確 ValueError。極小的正數可能使最終 exp 溢位，須說明函式的數值範圍；正式管線可直接保存 NLL。','驗證非空與有限值；math.fsum 累加 log；取平均；exp。','連乘後開根；空串列除零；偷偷把非法零機率改成一個 epsilon。','把函式用在 held-out token 機率，排除 padding 位置後計分。'),
'固定算力如何分配':('訓練 loss 受參數量與訓練 token 數共同影響。算力固定時，一味增大模型會減少能讀到的資料或訓練步數，可能使模型欠訓練。Chinchilla 的研究主張在其條件下共同配置模型與資料，而不是只追最大參數。最佳比例依資料品質、訓練方式與部署成本而異，不能把經驗法則當所有任務保證。','分開參數容量、資料量與算力；列出預算固定時的取捨；提出小規模配置對照。','把更多參數等同更充分訓練；把 20 當 universal optimum。','固定 token 計算预算，對比小模型多 token 與大模型少 token 的 held-out loss。'),
'Chinchilla 的訓練資料':('1.4T=1.4×10¹²，70B=70×10⁹，相除為 20 tokens/parameter。這是預訓練 token 使用量與參數量的比例，不是測試集樣本數，也不保證 20 個互不重複 token 分別配給每個參數。它是研究案例的配置值，不能無條件套用所有資料與模型。','統一 T 和 B 的數量級；相除保留單位；區分訓練與評測資料。','把 T/B 當 0.02；將比例理解為準確率或測試集大小。','在實驗表列出參數量、有效訓練 tokens、重複 epoch、算力與驗證集。'),
'能力提升如何驗證':('至少核對訓練資料與污染、prompt／示例數、評測指標及其閾值、計算預算、測試集樣本量。可固定資料與 prompt，測試多個相鄰規模與多個 seed，同時呈現連續分數和二元正確率；若只有閾值分數突然上升，可能是計分方式放大了平滑改變。圖中的相關不單獨證明規模造成能力跳變。','確認比較只改哪個因素；增加相鄰規模與重复測量；檢查量化指標是否帶閾值。','看到折線跳升便宣布新能力；比較不同 prompt 卻只歸因模型大小。','為現有模型建立一組固定推理題，保留逐題結果及不確定性。'),
'三種架構分類':('BERT：encoder-only，典型目標是恢復被遮罩的 token（MLM）。T5：encoder-decoder，典型 span corruption 以 sentinel 標記缺失片段，再由 decoder 生成缺失內容。GPT：decoder-only，以因果前綴預測下一個 token。這是典型對應，不代表每種架構只能做一種任務。','先看是否有 encoder／decoder；辨識可見上下文；再配訓練目標。','把 BERT 當一般 causal next-token 模型；把 T5 的 decoder 省略。','做分類或生成之前，先核對模型的 input、labels 和 attention mask 介面。'),
'任務選型與限制':('句子分類可用 encoder-only 的雙向表示接分類頭；自由續寫可用 decoder-only 以因果前綴逐步生成。理由是訓練目標與資訊可見範圍符合典型需求。decoder-only 也能透過 prompt 或分類頭分類，encoder-decoder 也可生成；最後需看資料、微調、延遲及品質，不能把典型適配當絕對能力界線。','列出任務輸入與輸出；對齊目標及注意力；用小基準驗證選型。','用參數大小代替任務適配；宣稱其他架構絕對做不到。','先做簡單 baseline，測正確率、推論時間與維護成本再升級。'),
'注意力可見範圍':('BERT encoder self-attention 看輸入的雙向上下文。自回歸 decoder self-attention 看當前及較早的前綴，不能看未來目標。cross-attention 的 Q 來自 decoder，中間表示去查询 encoder 輸出的 K、V；來源輸入通常可完整提供。三者不能用同一遮罩混為一談。','畫 query 与 key 的來源；逐一標示哪些位置允許可見；分開源句與目標句。','把完整來源句也遮成目標前綴；把 cross-attention Q、K 對調。','製作三種小型 mask，檢查每個 query 允許看的位置。'),
'MLM 的監督訊號':('遮罩位置應預測原 token「閱讀」。MLM 在可見輸入中使用雙向上下文恢復被遮罩內容；一般 GPT 依左側前綴預測下一位置，不能利用未來目標。MLM 的 loss 通常只在選定預測位置計算，而非要求所有輸入位置當作同一 causal 目標。','標出遮罩位置與其 label；確認上下文可見範圍；比較 label 位置與 next-token shift。','預測 [MASK] 字樣本身；直接拿相同 labels 交給 causal 模型。','寫出 input_ids、masked positions 與 labels，檢查只有目標位置算 loss。'),
'BERT 概念辨錯':('說法錯誤。「雙向」描述輸入中前後 token 可互相提供上下文，不是提前知道正確的下游標籤。情感分類時可完整輸入一句話，分類頭輸出正負類別，正確標籤在訓練／評估用於 loss 或比較，不是推論必要輸入。','區分輸入 token 與下游 label；畫分類頭資料流；檢查 label 僅在訓練計分使用。','把 bidirectional 當答案洩漏；把訓練 labels 放進測試文字。','檢查資料前處理是否意外把情感標籤串進模型輸入。'),
'分類模型的驗證':('可能是過擬合，也可能是測試域不同、標註規則不一致、資料切分或前處理出錯。先查切分、類別比例及相同文件是否跨 split，再分資料來源看 confusion matrix，手查錯誤樣本。若 train 好而同分布 validation 也下降，可再用學習曲線、正則化或 early stopping 驗證過擬合；不可直接宣布原因已證明。','列兩個競爭假設；設計能區分它們的檢查；優先排除資料管線錯誤。','只列名詞沒有可驗證步驟；用 test 反覆調參。','建立錯誤分析表：樣本、來源、標籤、預測、假設與驗證結果。'),
'cross-attention 的來源':('Q=decoder 的中間表示，K=encoder 輸出，V=encoder 輸出。生成當前目標 token 時，decoder 以自身需求查詢來源句表示，注意力加權取出有關輸入資訊。Q 的位置數對應目標長度，K／V 的位置數對應來源長度，二者不必相等。','標註源長度 S、目標長度 T；確認 QKᵀ 為 T×S；乘 V 後保留 T 個輸出位置。','Q 來自 encoder；要求來源和目標句等長。','用 S=4、T=2 的小矩陣驗證 cross-attention shape。'),
'T5 與 BART 的去噪':('T5 常以特殊 sentinel 替換連續缺失 spans，decoder 輸出 sentinel 與各缺失片段。BART 先損壞原文，例如 text infilling 或句序變換，再重建完整原文。兩者典型架構都是 encoder-decoder，但損壞策略與恢復目標格式不同。這裡比較的是預訓練設計，不是只看模型名稱猜產品用途。','先寫原文；製作損壞輸入；分別列出兩種目標序列。','把 T5 的 missing spans 目標寫成必然完整原文；把所有 BART 策略當每次都套用。','先實作一個 span corruptor，驗證 sentinel 順序、可還原性與 label 格式。'),
'翻譯資料流':('來源 token → encoder 表示 → decoder 結合已知目標前綴與 cross-attention → 下一個目標 token。來源句可完整讀取；decoder 目標 self-attention 必須遮住未來目標。訓練可 teacher force 已有的前綴，但 labels 要 shift，不能把同一位置應預測的答案提前當輸入。','先分來源與目標；畫 encoder 與 decoder；標出 target shift 與 causal mask。','來源句必須只能看一半；把未位移目標完整餵入導致 label leakage。','用兩句小資料逐個列 input、target 與 mask，確認第一步預測內容。'),
'decoder-only 的訓練目標':('輸入 [BOS,A,B]，目標 [A,B,EOS]。位置 0 在 BOS 上預測 A，位置 1 在 BOS,A 上預測 B，位置 2 預測 EOS。padding token 對應的 loss 通常忽略；attention mask 與 loss mask 是不同用途，不能只遮 attention 就假定 padding loss 消失。','將原序列左右移一格；逐位置對齊；再標示 padding 的 loss 排除。','使用相同未位移的輸入與目標；漏掉 EOS；把 attention mask 當 loss mask。','實作一個簡單 batch collator，打印 input_ids、labels 和 ignored positions。'),
'因果遮罩矩陣':('含對角線的允許矩陣為 [[1,0,0],[1,1,0],[1,1,1]]。第 1 query 只能看第一位置，(1,3)=0 以阻止未來資訊。當前位置可看，因為在 shift 後的訓練設計中，它要預測的是下一個 token。實際函式可能以 True 表示禁止位置或用 0／-∞ additive mask，需核對 API。','固定列 query、欄 key；畫下三角含對角線；核對 API 的布林語意。','用上三角；對角線全部禁止；不同框架 mask 值語意套錯。','在三 token 注意力範例測未來位置權重為零。'),
'next-token 配對實作':('長度至少 2 時回傳 tokens[:-1] 與 tokens[1:]；其他回傳兩個空串列。Python slicing 建立新串列，原始輸入不被修改。這只建立逐位置預測配對，尚未處理 batch padding、loss mask、attention mask、長文本切段及 tokenizer 特殊 token 規則。','先檢查長度；建立兩個切片；保存原輸入以做 mutation check。','pop 刪除原資料；兩邊都 tokens[:-1]；自行加入特殊 token 卻沒說明。','把函式接到資料 collator，檢查 labels 和 padding ignore index。'),
'SSM 的狀態':('SSM 透過狀態更新把先前資訊摘要到有限維狀態，再產生輸出；不必在每步显式建立所有 token-pair 注意力矩陣。這可改善長序列計算或記憶體成本，但狀態壓縮也可能影響精確回憶。實測需比較長序列品質、延遲、吞吐與記憶體，而不是只由漸近複雜度宣布勝負。','畫狀態更新與輸出；對比 token-pair 矩陣；選一個可測資源與品質取捨。','把摘要等同無損保存全部歷史；理論線性便宣稱所有長度都更快。','用簡化狀態模型和 attention toy model 比較不同長度的時間與記憶體。'),
'簡化狀態更新':('h₁=.5×0+2=2；h₂=.5×2+0=1；h₃=.5×1+2=2.5，且 y_t=h_t。舊資訊每步乘 .5 衰減。這只是固定係數標量示範，沒有向量狀態、輸入相依選擇、離散化及 Mamba 的完整模組與硬體演算法，不能用其結果聲稱重現 Mamba。','按時間順序計算；每步保留新狀態；列出 toy model 省略的機制。','每步拿 h₀ 更新；把固定係數等同 selective SSM。','寫五行迴圈並用 impulse input 看記憶隨時間衰減。'),
'Mamba 與 TTT':('Mamba 的 selection 讓狀態更新的部分參數依輸入變化；TTT 以測試時學習更新內部記憶，教材用模型參數作為狀態的思路說明。兩個名詞不足以決定優劣，需固定任務、context、硬體、精度與預算，再測品質、延遲和記憶體。也要區分訓練、prefill 和逐 token 推論。','配對機制；解釋記憶更新內容；訂出共同比較条件。','把 TTT 當重新訓練所有大模型權重；只比一張理論複雜度表。','先用教材公式寫狀態更新 toy example，再讀官方实现；不要求文書機重訓 Mamba。'),
}

CODE={
'bigram 計數實作':'''def bigram_counts(sentences):
    counts = {}
    for sentence in sentences:
        for a, b in zip(sentence, sentence[1:]):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return counts
''',
'注意力加權結果':'''import math
def weighted_value(weights, values):
    if not weights or len(weights) != len(values) or not values[0]:
        raise ValueError('empty input or shape mismatch')
    d = len(values[0])
    if any(len(row) != d for row in values):
        raise ValueError('ragged values')
    if any(not math.isfinite(w) or w < 0 for w in weights):
        raise ValueError('invalid weight')
    if not math.isclose(math.fsum(weights), 1.0, abs_tol=1e-8):
        raise ValueError('weights must sum to 1')
    return [math.fsum(w * row[j] for w, row in zip(weights, values)) for j in range(d)]
''',
'top-p 實作':'''import math
def nucleus_indices(probs, p):
    if not probs or not math.isfinite(p) or not 0 < p <= 1:
        raise ValueError('invalid p or empty probabilities')
    if any(not math.isfinite(x) or x < 0 for x in probs):
        raise ValueError('invalid probability')
    if not math.isclose(math.fsum(probs), 1.0, abs_tol=1e-8):
        raise ValueError('probabilities must sum to 1')
    order = sorted(range(len(probs)), key=lambda i: (-probs[i], i))
    chosen = []; total = 0.0
    for i in order:
        chosen.append(i); total += probs[i]
        if total >= p or math.isclose(total, p, abs_tol=1e-12):
            break
    return chosen
''',
'PPL 小函式':'''import math
def perplexity(probs):
    if not probs or any(not math.isfinite(p) or not 0 < p <= 1 for p in probs):
        raise ValueError('each probability must be in (0, 1]')
    return math.exp(-math.fsum(math.log(p) for p in probs) / len(probs))
''',
'next-token 配對實作':'''def next_token_pairs(tokens):
    if len(tokens) < 2:
        return [], []
    return tokens[:-1], tokens[1:]
''',
}

CASES={
'Chinchilla 案例：讀懂比例後規劃':[
 '觀察：1.4T/70B=20。此數值描述該研究的訓練配置，不是測試樣本量或所有任務的最佳比例。',
 '假設：既定模型欠訓練，固定算力下把部分參數預算改成更多有效 tokens，可能降低 held-out loss。替代解釋是資料品質或優化設定不合適。',
 '方案：先做小尺度配置網格，以 C≈6ND 作粗略訓練算力估計，再以實際耗時核對；比較較小 N／較大 D 與原配置。這是近似模型，不能忽略固定開銷。',
 '驗證：固定資料來源、tokenizer、上下文長度、評測集及總預算；至少 3 個 seed；記錄 held-out NLL／PPL、實際計算時間與下游任務結果。',
 '取捨／失敗：更多資料要去重和清理，也可能增加 I/O；若相同預算下未改善預先指定指標，便不能支持配置假設。先用小模型驗證，不在文書機重訓 70B。'],
'教材搜尋樹：改善生成策略':[
 '觀察：.10/.03≈3.33，序列機率較高約 3.33 倍，不是故事品質提升 3.33 倍。greedy 每步選局部最佳，可能錯過較好的全路徑。',
 '假設：開放生成的重複或單調與解碼策略有關；也可能是 prompt 或模型能力限制。',
 '方案：在既有同一模型比較 greedy、beam 與 top-p=.9 配合適中 temperature；機制是保留不同候選或改變分布，品質需驗證。',
 '驗證：固定 prompts、模型、長度和停止條件；每種策略多個 seed。記錄重複率、distinct n-grams、盲評一致性與故事連貫性、延遲。',
 '取捨／失敗：高溫可能不連貫；beam 較貴且可能偏向平庸輸出。若多樣性提升但連貫性下降超過預定容忍界線，方案不能算成功。'],
'PPL 與任務品質：下一步評測':[
 '觀察：這是教學假設。PPL 改善是平均目標 token 預測改善，不能直接代表事實正確或任務完成。',
 '競爭假設：模型在通用文本更好但與產品任務不匹配；或生成策略、上下文不足導致不可靠；也可能訓練／測試污染。',
 '方案：先將錯誤分為事實錯、未遵循要求、資訊不足與生成不穩定；優先針對頻率高且可修的原因，比較基準與一個干預，例如固定解碼策略或補足題目給定資訊。',
 '驗證：建立去重的 held-out 任務集，固定模型與規準，逐題核對答案與可追溯證據；主要指標任務正確率，另看幻覺率、延遲与成本。',
 '取捨／失敗：若只降低 PPL 而可靠性指標未改善，就否定「本次改動已改善產品可靠性」。保留原錯誤與改後結果，避免選成功樣本。'],
'BERT 案例的對照實驗設計':[
 '定位：教材 2.3.2 BERT 與 2.3.3 衍生模型，先核對原文提到的目標、資料或訓練步數；題目沒有授權捏造論文數字。',
 '假設：動態而非固定遮罩讓相同資料在不同步看到更多預測位置，可能改善有限預訓練下的表示。替代解釋是單純增加訓練量。',
 '方案：用現成小模型或合成小詞表做 tiny MLM，僅改固定／動態 mask，資料、初始化和總步數相同。CPU 跑小樣本；不聲稱重現完整 BERT。',
 '驗證：固定 vocabulary、mask 比率、train／validation split、優化器、批次和更新次數；多 seed 比 held-out masked-token loss 與一個小分類任務。',
 '取捨／失敗：動態資料處理較複雜。若預訓練 loss 改善但下游未改善，只能報告局部效果；預算內無穩定差異便不支持假設。'],
'T5／BART：去噪方案改進':[
 '觀察：T5 span corruption 恢復缺失 spans，BART 去噪重建原文；本例選 T5 的 span 長度，教材依據 2.4.2。',
 '假設：資料含較長固定短語，稍長 span 可能迫使模型學跨詞關係；也可能因輸入資訊過少而變難。',
 '方案：只改平均 span 長度，固定整體遮罩 token 比率；先實作可重現的 corruptor，保留 sentinel 與 labels，再用 tiny model。',
 '驗證：固定資料切分、模型、tokenizer、預算和 seed；先測重建目標格式與還原性，再比 held-out 重建 loss 與相同下游任務。',
 '取捨／失敗：更長 spans 不必然更好，生成目標長度也會改變成本。若下游品質或訓練效率退步超界線，回復基準並檢查資訊量假設。'],
'Mamba／Transformer：公平比較':[
 '觀察：教材 2.6.1 說明 selective SSM 與長序列效率；理論複雜度較低不足以證明全面勝過 Transformer。',
 '假設：在較長序列下狀態模型有資源優勢；替代解釋包括 kernel 優化、精度、模型大小或硬體差異。',
 '方案：先在 CPU 比同等輸入長度的小型狀態更新與 attention toy model，測 64、128、256、512 長度；只稱機制示範，實際 Mamba 需可用的官方實現。',
 '驗證：固定硬體、dtype、batch、執行緒與任務，分開訓練、prefill、逐 token decode。warm-up 後重复，記時間、峰值記憶體和品質；資料前處理不計入核心延遲但另記。',
 '取捨／失敗：若只有 toy model 快不能推論真實模型品質。短序列沒有速度優勢或長距離回憶較差都是有效負面結果；不刪除失敗長度。'],
'BERT Table 5：不是所有改動都改善':[
 '計算：84.9−77.8=7.1 F1 點；88.5−84.9=3.6 F1 點。應稱絕對 F1 差，不是 7.1% 相對提升。資料是 SQuAD dev，不是所有任務。',
 '解讀：BERT_BASE 對 LTR & No NSP 同時改變雙向／訓練目標與 NSP，不能把整個 10.7 點落差都歸因移除 NSP。No NSP 87.9 與基準差 .6 是另一個較聚焦對比。',
 '方案：優先核對雙向表示對 QA 的作用，設計控制相同資料、預訓練 token 預算與微調設定的方向／目標對照，或先實作 attention 可見範圍示範。',
 '驗證：多 seed 報告平均與變異，使用固定 SQuAD 切分與 F1／EM，再看一個其他任務；列清實際改變哪些因素，無法控制的變因要承認。',
 '取捨／失敗：完整重現成本高；CPU 小示範只驗證機制，不重現 88.5。若效果不穩定、EM／其他任務退步或成本超預算，不能稱普遍改善。'],
'Chinchilla 原論文：改善結論的限制':[
 '計算：(7.75−7.16)/7.75×100%=7.6129%，約 7.61%；絕對差 .59 PPL。這不是準確率提高 7.61 個百分點。',
 '解讀：作者在 §4.2.1 提醒資料量較大可能增加 train/test leakage；§4.1 也列出優化器、tokenizer 等設定。即使算力相當，也不能單由兩個結果把改善全部歸因比例。',
 '方案：先做資料去污染与重複檢查，建立時間上分離的 held-out 文字；在小模型控制訓練配置，分別比較資料量／參數量因素。',
 '驗證：對齊 tokenizer 或用合適的共同文字正規化單位，固定資料品質、預算與評測，呈現去污染前後 NLL／PPL 與多任務結果，多 seed 記成本。',
 '取捨／失敗：去污染可能誤刪合理相似文本；保留原與去污染版本。若去污染後改善消失，或只在一個集成立，便不能支持普遍 compute-optimal 優勢的強結論。'],
}

def guide(title,section,kind,locator):
    chapter_sections,keywords,pages=SECTIONS[section]
    origin='概念實作延伸' if kind=='python' else ('原論文案例延伸' if title in ('BERT Table 5：不是所有改動都改善','Chinchilla 原論文：改善結論的限制') else '教材概念與教學情境延伸' if kind=='case_proposal' else '教材概念應用')
    reading={'chapter':int(section[0]),'sections':chapter_sections,'keywords':keywords,'english_printed_pages':pages,'page_note':'頁碼是目前存入後端之英文版書內印刷頁碼；PDF 檢視器頁碼可能不同。中文版請用章節號與關鍵詞定位。','repository_url':REPO,'original_locator':locator}
    if title in CASES:
        parts=CASES[title]
        return {'origin':origin,'reference_answer':'\n\n'.join(parts),'steps':parts,'common_errors':['把觀察當已證明的原因；只說換更大模型而沒有機制或預算。','改善沒有基準、控制變因與失敗判準；把小型實驗當完整原論文重現。'],'practical_transfer':'先完成資料表／計算／小型管線，再提出一個預算內可執行的對照。案例題是多解題；可接受符合來源、機制、控制與驗證要求的替代方案。','reference_code':None,'reading':reading,'authorship':'本系統原創教學詳解；不是教材逐字答案，仍待管理者覆核。'}
    solution,steps,errors,practice=GUIDES[title]
    return {'origin':origin,'reference_answer':solution,'steps':steps.split('；'),'common_errors':errors.split('；'),'practical_transfer':practice,'reference_code':CODE.get(title),'reading':reading,'authorship':'本系統原創教學詳解；概念來自對應章節，數字或程式題為自行設計的教學例子，仍待管理者覆核。'}
