# 本機模型下載與 OmniEdu LoRA 接入

## 網頁操作

管理者 → 模型轉接槽 → 模型磁碟庫。下載來源可選 Ollama Library 或 Hugging Face 公開 GGUF。HF 可搜尋、查看模型卡／授權及檔案大小，再選主機 Ollama 或 LM Studio 下載。下載完不自動切換模型槽。Ollama 會登錄新來源；LM Studio 的下載 ID 與推論 ID 可能不同，請按「列舉本機模型」、選其實際回傳 ID，再保存來源與核對。

模型推論只能使用 localhost／127.0.0.1／::1。沒有 Hugging Face 雲端推論、付費 API、訂閱、結帳或自動接受 gated 模型條款。HF 只存取公開模型 metadata。Ollama cloud 模型不能接入。

LM Studio 需啟動本機伺服器，預設 http://127.0.0.1:1234。管理 API 需支援 /api/v1/models/download 與 download/status。若啟用 LM Studio API 身份驗證，金鑰由主機環境變數 ASSESSMENT_LMSTUDIO_TOKEN 提供，不存入 SQLite、網頁或 Git。下載工作監控中斷不會刪除 runtime cache；服務重新啟動後先在 runtime 查看狀態再重試。

## 自行上傳

接受 GGUF、Safetensors、adapter_config.json，最多32 GiB，1 MiB分塊保存在SQLite。每個區塊重試會比較原內容，最後核對總長度、標頭與SHA256。檔案格式檢查不能保證架構或推論品質相容。拒絕pickle、執行檔、任意路徑與瀏覽器指定主機目錄。

完整單檔 GGUF 可匯入 Ollama，先上傳 blob 再 create；禁止覆蓋既有模型名稱。新版 Ollama API 已停用直接掛載 LoRA adapters。Safetensors adapter 會保存，使用相容原生載入器或合併後的完整 GGUF，不把 e4b adapter 套到12B基底。公開下載的模型權重保存在下載引擎自己的本機 cache；SQLite 保存來源、工作進度與版本資訊。

## OmniEdu final 20261007

來源是使用者提供的原生模型包：google/gemma-4-E4B-it，revision ee0ef6023621cff504d758262d4e04895a5af4a2，rank8，adapter SHA256 ec4f6736e96d8f293558355a0ca56047571ea59b6ef5fb7fd652d6c0b1480b0c。

Register-OmniEdu.py 驗證包內底模manifest的所有檔案及adapter。小型adapter／config分塊封存到SQLite；16GB底模使用既有本機包，不再次下載或複製到Git。登錄來源為omniedu-final-20261007，保留既有Gemma 4 12B與GPT OSS20B模型槽選擇。

原生橋接 backend/omni_server.py 只綁127.0.0.1:8767，提供 /v1/models、/v1/chat/completions、/v1/unload。model ID為omniedu-gemma4-e4b-it-lora。所有from_pretrained均local_files_only、trust_remote_code=false、HF_HUB_OFFLINE=1。支援文字與最多兩張內嵌PNG，context8192，greedy、最多2048生成tokens。直接瀏覽器跨來源請求被拒絕，網頁經過自己的已登入後端呼叫。

Windows 建議 Python3.12 獨立環境：

```powershell
python -m venv .runtime/omni-env
.runtime/omni-env/Scripts/python.exe -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
.runtime/omni-env/Scripts/python.exe -m pip install -r requirements-omni.txt
python scripts/Register-OmniEdu.py --package "你的OmniEdu資料夾"
./scripts/Start-OmniEdu.ps1 -PackagePath "你的OmniEdu資料夾"
```

Ubuntu／WSL2：在獨立venv安裝相同requirements，以原生路徑或/mnt/c/...存取模型包，執行 python backend/omni_server.py --package /path/to/OmniEdu-final-20261007。Windows後端可經WSL localhost forwarding連127.0.0.1:8767。需要可用的NVIDIA CUDA與BF16。此NF4載入器不是M5 Max／CPU版；未來移轉M5需另外驗證MLX等相容載入器與adapter轉換。

RTX5070Ti Laptop單GPU上，網站使用全域推論鎖。接入原生OmniEdu前只釋放網站已登錄的Ollama模型；回到Ollama前呼叫本網站OmniEdu來源的unload。未登錄的其他應用模型不會被停止。不保證不同應用同時占用GPU時有足夠VRAM。

## 本次驗證

本機OmniEdu底模與adapter所有雜湊通過；RTX5070Ti Laptop、torch2.10.0+cu128、transformers5.18.0、peft0.21.2載入成功。文字推論成功，但MLM除錯解釋有不精確之處；圖像程式碼閱讀正確回傳 {"label_value":"[MASK]"}，JSON有效。第二次包含system prompt的圖片測試卻誤讀為['MASK']，未通過精確字串核對，顯示視覺回答品質仍不穩定。這只證明輸入輸出流程，不能視為教學準確率或正式評分校準。正式模型槽未自動切換。

Ollama下載流程以既有gpt-oss:20b實測完成；HF公開搜尋與11.28GiB GGUF檔案列舉實測成功。LM Studio已安裝但伺服器尚未啟動，使用官方協定模擬測試，尚未實際下載／推論。

官方參考：https://docs.ollama.com/api/pull 、https://docs.ollama.com/api/create 、https://github.com/ollama/ollama/blob/main/api/types.go 、https://huggingface.co/docs/hub/ollama 、https://lmstudio.ai/docs/developer/rest/download 、https://lmstudio.ai/docs/developer/rest/download-status 。
