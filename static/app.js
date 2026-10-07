/**
 * ExamCrafter AI - 前端核心控制器 (Pure Vanilla JavaScript)
 * 100% 離線原生代碼，嚴格不使用 TailwindCSS
 * 實作完整工作流：
 * 步驟一：教材匯入與選定範圍 -> 參數與大題架構設定 (自訂或舊卷克隆)
 * 步驟二：SSE 即時串流出題與線上審題微調 (支援單題抽換)
 * 步驟三：一鍵成套 Word 匯出下載 (試題卷 + 作答紙 + 教師詳解本)
 */

// 1. 五大科目預設常規模板
const SUBJECT_TEMPLATES = {
  English: {
    title: "115學年度第一學期七年級英語科第二次定期評量試題本",
    sections: [
      { id: "sec_1", title: "一、 文意字彙選擇 (每題 2 分)", type: "CHOICE", count: 10, score: 2 },
      { id: "sec_2", title: "二、 語法與綜合選擇 (每題 2 分)", type: "CHOICE", count: 10, score: 2 },
      { id: "sec_3", title: "三、 克漏字測驗 (每題 2 分)", type: "CHOICE", count: 4, score: 2 },
      { id: "sec_4", title: "四、 閱讀測驗題組 (每題 3 分)", type: "GROUP_PASSAGE", passages: 3, q_per_p: 3, score: 3 },
      { id: "sec_5", title: "五、 依提示作答與翻譯 (每題 5 分)", type: "SENTENCE_REWRITE", count: 5, score: 5 }
    ]
  },
  Geography: {
    title: "臺中市立大業國民中學 114學年度第1學期第3次定期評量八年級地理科試卷",
    sections: [
      { id: "sec_1", title: "一、 填圖選擇題 (第 1-14 題，每題 2.5 分)", type: "CHOICE", count: 14, score: 2.5 },
      { id: "sec_2", title: "二、 綜合選擇題 (第 15-28 題，每題 2.5 分)", type: "CHOICE", count: 14, score: 2.5 },
      { id: "sec_3", title: "三、 氣候數據題組 (第 29-40 題，每題 2.5 分)", type: "GROUP_PASSAGE", passages: 4, q_per_p: 3, score: 2.5 }
    ]
  },
  History: {
    title: "臺中市立大業國中 113學年度第1學期第3次定期評量八年級歷史科試卷",
    sections: [
      { id: "sec_1", title: "一、 單選題 (第 1-30 題，每題 3 分)", type: "CHOICE", count: 30, score: 3 },
      { id: "sec_2", title: "二、 條約與史料題組 (第 31-35 題，每題 2 分)", type: "GROUP_PASSAGE", passages: 2, q_per_p: 2.5, score: 2 }
    ]
  },
  Civics: {
    title: "臺中市大業國中 114學年度第1學期八年級第三次定期評量公民試題",
    sections: [
      { id: "sec_1", title: "一、 基礎選舉與地方自治選擇 (第 1-35 題，每題 2 分)", type: "CHOICE", count: 35, score: 2 },
      { id: "sec_2", title: "二、 時事案例與情境選擇 (第 36-45 題，每題 3 分)", type: "CHOICE", count: 10, score: 3 }
    ]
  },
  Chinese: {
    title: "115年國中教育會考國文科模擬試題本",
    sections: [
      { id: "sec_1", title: "一、 語文常識與字音字形 (每題 2 分)", type: "CHOICE", count: 10, score: 2 },
      { id: "sec_2", title: "二、 白話文與生活情境選擇 (每題 2 分)", type: "CHOICE", count: 15, score: 2 },
      { id: "sec_3", title: "三、 文言文與古典詩詞選擇 (每題 3 分)", type: "CHOICE", count: 5, score: 3 },
      { id: "sec_4", title: "四、 綜合閱讀題組 (每題 3 分)", type: "GROUP_PASSAGE", passages: 4, q_per_p: 3, score: 3 }
    ]
  }
};

// 全域狀態變數
let currentSubject = "English";
let currentSections = [];
let currentExamData = null;
let currentUnitsList = [];

// DOM 初始化
document.addEventListener("DOMContentLoaded", () => {
  loadSubjectTemplate("English");
  checkBackendStatus();
  loadUnitsList();
  setupDragAndDrop();
  setupEventListeners();
  setupDropzones();
});

// ==============================================================================
// 1. 系統連線狀態檢測
// ==============================================================================
async function checkBackendStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const dot = document.getElementById("ollama-dot");
    const text = document.getElementById("ollama-status-text");
    if (data.ollama_online) {
      dot.className = "status-dot";
      text.innerText = `本地 Ollama 在線 (${data.model || 'gemma4:e4b'})`;
    } else {
      dot.className = "status-dot offline";
      text.innerText = "Ollama 離線 (雲端備援)";
    }
  } catch (e) {
    console.error("後端連線檢測失敗", e);
  }
}

// ==============================================================================
// 2. 教材管理模組 (動態上傳、文字貼上、示範載入、清空與範圍勾選)
// ==============================================================================

// 切換教材匯入頁籤 (檔案上傳 vs 直接貼上)
function switchTextbookTab(tab) {
  document.getElementById("tab-tb-upload").classList.toggle("active", tab === "upload");
  document.getElementById("tab-tb-paste").classList.toggle("active", tab === "paste");
  document.getElementById("tb-upload-panel").style.display = (tab === "upload") ? "block" : "none";
  document.getElementById("tb-paste-panel").style.display = (tab === "paste") ? "block" : "none";
}

// 載入目前系統中的教材清單
async function loadUnitsList() {
  try {
    const res = await fetch(`/api/units?subject=${currentSubject}`);
    const data = await res.json();
    currentUnitsList = data.units || [];
    renderUnitsList();
  } catch (e) {
    console.error("載入教材清單失敗", e);
  }
}

// 渲染教材單元晶片清單
function renderUnitsList() {
  const container = document.getElementById("units-list-container");
  const statsBadge = document.getElementById("units-stats-badge");
  container.innerHTML = "";

  if (currentUnitsList.length === 0) {
    container.innerHTML = `
      <div class="empty-units-state">
        <div style="font-size: 1.5rem; margin-bottom: 0.4rem;">📂</div>
        <strong>尚未匯入任何教材檔案或文字內容</strong>
        <p style="font-size: 0.82rem; margin-top: 0.3rem;">請於上方拖曳上傳 PDF/Word 檔案、貼上課文內容，或點擊右上角「載入示範教材」以開始出題。</p>
      </div>
    `;
    statsBadge.innerText = "尚未索引任何單元";
    statsBadge.style.color = "#94a3b8";
    return;
  }

  let totalVocab = 0;
  let totalGrammar = 0;

  currentUnitsList.forEach((u, idx) => {
    totalVocab += (u.vocab_count || 0);
    totalGrammar += (u.grammar_count || 0);

    const chip = document.createElement("div");
    chip.className = "unit-chip selected";
    chip.dataset.uid = u.unit_id;
    chip.innerHTML = `
      <input type="checkbox" class="unit-checkbox" id="ucb-${u.unit_id}" value="${u.unit_id}" checked onchange="toggleUnitChipClass(this)">
      <label for="ucb-${u.unit_id}" style="cursor: pointer; flex: 1; min-width: 0; margin-bottom: 0;">
        <div style="font-weight: 700; font-size: 0.85rem; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${u.unit_id}: ${u.title || u.unit_id}</div>
        <span class="unit-chip-details">${u.vocab_count || 0} 個詞彙 · ${u.grammar_count || 0} 個句型/概念</span>
      </label>
      <button type="button" class="unit-delete-btn" title="從測驗範圍移除此單元" onclick="deleteSingleUnit(event, '${u.unit_id}')">🗑️</button>
    `;
    container.appendChild(chip);
  });

  statsBadge.innerText = `● 已索引 ${currentUnitsList.length} 個單元 (含 ${totalVocab} 個詞彙、${totalGrammar} 個句型/概念)`;
  statsBadge.style.color = "#10b981";
}

function toggleUnitChipClass(cb) {
  const chip = cb.closest(".unit-chip");
  if (chip) {
    chip.classList.toggle("selected", cb.checked);
  }
}

function selectAllUnits(checked) {
  document.querySelectorAll(".unit-checkbox").forEach(cb => {
    cb.checked = checked;
    toggleUnitChipClass(cb);
  });
}

// 單獨刪除特定單元教材
async function deleteSingleUnit(event, unitId) {
  event.stopPropagation();
  event.preventDefault();
  if (!confirm(`確定要從本次測驗範圍中移除單元【${unitId}】嗎？`)) return;

  try {
    const res = await fetch("/api/delete-unit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit_id: unitId })
    });
    const data = await res.json();
    if (data.success) {
      currentUnitsList = data.units || [];
      renderUnitsList();
      const statusDiv = document.getElementById("tb-upload-status");
      statusDiv.innerHTML = `<span style="color: #64748b; font-size: 0.82rem;">🗑️ ${data.message}</span>`;
    } else {
      alert(data.message || "刪除失敗");
    }
  } catch (e) {
    console.error("刪除單元出錯", e);
    alert("連線失敗: " + e);
  }
}

// 處理教材檔案上傳 (支援多檔、無限制大小與單元數)
async function handleTextbookUpload(files) {
  if (!files || files.length === 0) return;
  const statusDiv = document.getElementById("tb-upload-status");
  statusDiv.innerHTML = `
    <div style="display: flex; align-items: center; gap: 0.5rem; color: #2563eb; font-weight: 600; font-size: 0.88rem;">
      <span>⏳ 正在逐檔讀取並解析 ${files.length} 個教材檔案 (抽取課文、單字與句型結構)...</span>
    </div>
  `;

  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append("files", files[i]);
  }
  formData.append("subject", currentSubject);

  try {
    const res = await fetch("/api/upload-textbooks", { method: "POST", body: formData });
    const data = await res.json();
    if (data.success) {
      let html = "";
      if (data.message) {
        html += `<div style="color: #10b981; font-weight: 600; margin-bottom: 0.4rem;">✅ ${data.message} 已同步更新至下方測驗範圍！</div>`;
      }
      if (data.warnings && data.warnings.length > 0) {
        html += `<div style="margin-top: 0.5rem; padding: 0.6rem 0.8rem; background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; color: #b45309; font-size: 0.82rem; text-align: left;">
          ⚠️ <strong>注意（純圖片掃描檔，已略過）：</strong><br>` + data.warnings.map(w => `• ${w}`).join('<br>') + `
        </div>`;
      }
      if (data.errors && data.errors.length > 0) {
        html += `<div style="margin-top: 0.5rem; padding: 0.6rem 0.8rem; background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; color: #dc2626; font-size: 0.82rem; text-align: left;">
          ❌ <strong>檔案讀取失敗或格式損毀（已隔離略過）：</strong><br>` + data.errors.map(e => `• ${e}`).join('<br>') + `
        </div>`;
      }
      statusDiv.innerHTML = html;
      currentUnitsList = data.units || [];
      renderUnitsList();
      const inputEl = document.getElementById("tb-files-input");
      if (inputEl) inputEl.value = "";
    } else {
      statusDiv.innerHTML = `<span style="color: #ef4444;">解析出錯: ${data.detail || '未知錯誤'}</span>`;
    }
  } catch (e) {
    statusDiv.innerHTML = `<span style="color: #ef4444;">上傳連線失敗: ${e}</span>`;
  }
}

// 處理直接貼上教材文字內容
async function submitPastedTextbook() {
  const title = document.getElementById("tb-paste-title").value.trim();
  const content = document.getElementById("tb-paste-content").value.trim();
  const statusDiv = document.getElementById("tb-paste-status");

  if (!content) {
    alert("請輸入貼上的教材內容！");
    return;
  }

  statusDiv.innerHTML = `<span style="color: #2563eb; font-weight: 600;">⏳ 正在分析貼上的教材文本與結構化切片...</span>`;

  try {
    const res = await fetch("/api/paste-textbook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: title || "自訂課次",
        content: content,
        subject: currentSubject
      })
    });
    const data = await res.json();
    if (data.success) {
      statusDiv.innerHTML = `<span style="color: #10b981; font-weight: 600;">✅ ${data.message}</span>`;
      document.getElementById("tb-paste-title").value = "";
      document.getElementById("tb-paste-content").value = "";
      currentUnitsList = data.units || [];
      renderUnitsList();
    } else {
      statusDiv.innerHTML = `<span style="color: #ef4444;">解析失敗: ${data.detail || '格式錯誤'}</span>`;
    }
  } catch (e) {
    statusDiv.innerHTML = `<span style="color: #ef4444;">送出出錯: ${e}</span>`;
  }
}

// 一鍵載入示範教材 (12單元)
async function loadSampleTextbooks() {
  const statusDiv = document.getElementById("tb-upload-status");
  statusDiv.innerHTML = `<span style="color: #2563eb; font-weight: 600;">⏳ 正在載入國中七年級 12 單元示範教材...</span>`;
  try {
    const res = await fetch("/api/load-sample-textbooks", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      statusDiv.innerHTML = `<span style="color: #10b981; font-weight: 600;">✅ 已成功載入 12 個課次示範教材！</span>`;
      currentUnitsList = data.units || [];
      renderUnitsList();
    } else {
      statusDiv.innerHTML = `<span style="color: #ef4444;">載入失敗: ${data.message}</span>`;
    }
  } catch (e) {
    statusDiv.innerHTML = `<span style="color: #ef4444;">連線出錯: ${e}</span>`;
  }
}

// 一鍵清空教材
async function clearTextbooks() {
  if (!confirm("確定要清空目前已讀取的所有教材範圍嗎？")) return;
  try {
    const res = await fetch("/api/clear-textbooks", { method: "POST" });
    const data = await res.json();
    currentUnitsList = [];
    renderUnitsList();
    document.getElementById("tb-upload-status").innerHTML = "";
    document.getElementById("tb-paste-status").innerHTML = "";
  } catch (e) {
    console.error("清空教材出錯", e);
  }
}

// ==============================================================================
// 3. 大題架構與常規模板模組
// ==============================================================================

// 切換科目並載入預設模板
function loadSubjectTemplate(subject) {
  currentSubject = subject;
  const tpl = SUBJECT_TEMPLATES[subject];
  if (!tpl) return;

  document.getElementById("exam-title").value = tpl.title;
  currentSections = JSON.parse(JSON.stringify(tpl.sections));
  renderSectionCards();
  updateScoreSummary();
  loadUnitsList();
}

// 渲染大題卡片清單
function renderSectionCards() {
  const container = document.getElementById("section-list");
  container.innerHTML = "";

  currentSections.forEach((sec, idx) => {
    const card = document.createElement("div");
    card.className = "section-card";
    card.draggable = true;
    card.dataset.index = idx;

    const isPassage = sec.type === "GROUP_PASSAGE";

    card.innerHTML = `
      <div class="drag-handle" title="按住拖曳排序">☰</div>
      <div class="section-meta">
        <input type="text" class="section-title-input" value="${sec.title}" 
               onchange="updateSectionTitle(${idx}, this.value)" title="點擊修改大題名稱">
      </div>
      <div class="section-controls">
        <select class="form-select" style="width: 140px; font-size: 0.82rem;" onchange="updateSectionType(${idx}, this.value)">
          <option value="CHOICE" ${sec.type === 'CHOICE' ? 'selected' : ''}>選擇題</option>
          <option value="GROUP_PASSAGE" ${sec.type === 'GROUP_PASSAGE' ? 'selected' : ''}>閱讀題組</option>
          <option value="SENTENCE_REWRITE" ${sec.type === 'SENTENCE_REWRITE' ? 'selected' : ''}>改寫與非選</option>
          <option value="FILL_BLANK" ${sec.type === 'FILL_BLANK' ? 'selected' : ''}>字彙填空</option>
          <option value="TRANSLATION" ${sec.type === 'TRANSLATION' ? 'selected' : ''}>翻譯題</option>
        </select>
        ${isPassage ? `
          <div class="inline-field">
            <span>篇數:</span>
            <input type="number" min="1" max="15" value="${sec.passages || 2}" onchange="updatePassageCount(${idx}, this.value)">
            <span>× 題數:</span>
            <input type="number" min="1" max="8" value="${sec.q_per_p || 3}" onchange="updatePassageQPerP(${idx}, this.value)">
          </div>
        ` : `
          <div class="inline-field">
            <span>題數:</span>
            <input type="number" min="1" max="60" value="${sec.count || 5}" onchange="updateSectionCount(${idx}, this.value)">
          </div>
        `}
        <div class="inline-field">
          <span>每題:</span>
          <input type="number" step="0.5" min="0.5" max="20" value="${sec.score || 2}" onchange="updateSectionScore(${idx}, this.value)">
          <span>分</span>
        </div>
        <button class="btn-icon" onclick="removeSection(${idx})" title="刪除此大題">✕</button>
      </div>
    `;

    container.appendChild(card);
  });
}

// 動態即時計算題數與總分 (Sticky Summary Bar)
function updateScoreSummary() {
  let totalQ = 0;
  let totalScore = 0;

  currentSections.forEach(s => {
    let qCount = 0;
    if (s.type === "GROUP_PASSAGE") {
      qCount = (parseInt(s.passages) || 1) * (parseInt(s.q_per_p) || 3);
    } else {
      qCount = parseInt(s.count) || 0;
    }
    const scoreEach = parseFloat(s.score) || 0;
    totalQ += qCount;
    totalScore += (qCount * scoreEach);
  });

  document.getElementById("stat-total-q").innerText = totalQ;
  document.getElementById("stat-total-score").innerText = totalScore.toFixed(1).replace(/\.0$/, "");
}

function updateSectionTitle(idx, val) {
  currentSections[idx].title = val;
}
function updateSectionType(idx, val) {
  currentSections[idx].type = val;
  if (val === "GROUP_PASSAGE" && !currentSections[idx].passages) {
    currentSections[idx].passages = 2;
    currentSections[idx].q_per_p = 3;
  }
  renderSectionCards();
  updateScoreSummary();
}
function updateSectionCount(idx, val) {
  currentSections[idx].count = parseInt(val) || 1;
  updateScoreSummary();
}
function updatePassageCount(idx, val) {
  currentSections[idx].passages = parseInt(val) || 1;
  updateScoreSummary();
}
function updatePassageQPerP(idx, val) {
  currentSections[idx].q_per_p = parseInt(val) || 1;
  updateScoreSummary();
}
function updateSectionScore(idx, val) {
  currentSections[idx].score = parseFloat(val) || 1;
  updateScoreSummary();
}
function removeSection(idx) {
  currentSections.splice(idx, 1);
  renderSectionCards();
  updateScoreSummary();
}
function addNewSection() {
  const newIdx = currentSections.length + 1;
  currentSections.push({
    id: `sec_${Date.now()}`,
    title: `第 ${newIdx} 大題 (每題 2 分)`,
    type: "CHOICE",
    count: 5,
    score: 2
  });
  renderSectionCards();
  updateScoreSummary();
}

// 拖曳大題排序
function setupDragAndDrop() {
  const container = document.getElementById("section-list");
  let draggedItem = null;

  container.addEventListener("dragstart", (e) => {
    draggedItem = e.target.closest(".section-card");
    if (draggedItem) draggedItem.classList.add("dragging");
  });

  container.addEventListener("dragend", (e) => {
    if (draggedItem) draggedItem.classList.remove("dragging");
    draggedItem = null;
  });

  container.addEventListener("dragover", (e) => {
    e.preventDefault();
    const afterElement = getDragAfterElement(container, e.clientY);
    if (draggedItem) {
      if (afterElement == null) {
        container.appendChild(draggedItem);
      } else {
        container.insertBefore(draggedItem, afterElement);
      }
    }
  });

  container.addEventListener("drop", () => {
    const cards = container.querySelectorAll(".section-card");
    const newSecs = [];
    cards.forEach(c => {
      const idx = parseInt(c.dataset.index);
      newSecs.push(currentSections[idx]);
    });
    currentSections = newSecs;
    renderSectionCards();
  });
}

function getDragAfterElement(container, y) {
  const draggableElements = [...container.querySelectorAll(".section-card:not(.dragging)")];
  return draggableElements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) {
      return { offset: offset, element: child };
    } else {
      return closest;
    }
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

// ==============================================================================
// 4. 舊考卷參考模板骨架克隆 (方案 B)
// ==============================================================================
async function handleCloneUpload(file) {
  if (!file) return;
  const statusDiv = document.getElementById("clone-status");
  statusDiv.innerHTML = `<span style="color: #2563eb; font-weight: 600;">⏳ 正在解析舊考卷骨架結構 (三段式容錯管線)...</span>`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/clone-skeleton", { method: "POST", body: formData });
    const data = await res.json();

    if (!data.success && data.is_scanned_image) {
      statusDiv.innerHTML = `<span style="color: #ef4444;">${data.message}</span>`;
      return;
    }

    if (data.cloned_title) {
      document.getElementById("exam-title").value = data.cloned_title;
    }

    // 將克隆出的大題完全規範化回填至方案 A 介面
    if (data.sections && data.sections.length > 0) {
      currentSections = data.sections.map((s, idx) => {
        const secType = s.section_type || s.type || "CHOICE";
        const qCount = parseInt(s.question_count || s.count || 5);
        const scoreEach = parseFloat(s.score_per_question || s.score || 2);
        const pCount = parseInt(s.passages_count || s.passages || Math.max(1, Math.round(qCount / 3)));
        const qPerP = parseInt(s.questions_per_passage || s.q_per_p || Math.max(1, Math.round(qCount / pCount)));

        return {
          id: `cloned_${idx}`,
          title: s.section_name || s.title || `第 ${idx+1} 大題`,
          type: secType,
          count: qCount,
          score: scoreEach,
          passages: pCount,
          q_per_p: qPerP
        };
      });

      renderSectionCards();
      updateScoreSummary();
      switchModeTab("manual");
      statusDiv.innerHTML = `<span style="color: #10b981; font-weight: 600;">✅ 克隆解析成功！已自動回填 ${data.sections.length} 個大題結構至下方設定面板。</span>`;
    }
  } catch (e) {
    statusDiv.innerHTML = `<span style="color: #ef4444;">上傳解析出錯: ${e}</span>`;
  }
}

// ==============================================================================
// 5. 核心考卷生成 (SSE 即時串流進度條 + 子批次分塊出題)
// ==============================================================================
async function startGenerateExam() {
  // 檢查是否有選取教材範圍
  const selectedUnits = [];
  document.querySelectorAll(".unit-checkbox:checked").forEach(cb => {
    selectedUnits.push(cb.value);
  });

  if (selectedUnits.length === 0) {
    if (currentUnitsList.length > 0) {
      alert("請至少在教材範圍清單中勾選一個課次單元！");
      return;
    } else {
      if (confirm("尚未匯入教材，是否自動載入 12 單元示範教材進行出題？")) {
        await loadSampleTextbooks();
        document.querySelectorAll(".unit-checkbox").forEach(cb => {
          cb.checked = true;
          selectedUnits.push(cb.value);
        });
      } else {
        return;
      }
    }
  }

  // 切換至步驟二 (審題面板)
  switchStep(2);
  const progressBox = document.getElementById("gen-progress-box");
  const progressFill = document.getElementById("gen-progress-fill");
  const progressText = document.getElementById("gen-progress-text");
  const qListContainer = document.getElementById("generated-q-list");

  progressBox.style.display = "block";
  progressFill.style.width = "5%";
  progressText.innerText = "出題引擎準備中...";
  qListContainer.innerHTML = "";

  // 規範化傳送的大題設定
  const normalizedSections = currentSections.map(s => ({
    id: s.id,
    title: s.title,
    section_title: s.title,
    type: s.type,
    section_type: s.type,
    count: parseInt(s.count) || 5,
    question_count: parseInt(s.count) || 5,
    score: parseFloat(s.score) || 2,
    score_per_question: parseFloat(s.score) || 2,
    passages: parseInt(s.passages) || 2,
    passages_count: parseInt(s.passages) || 2,
    q_per_p: parseInt(s.q_per_p) || 3,
    questions_per_passage: parseInt(s.q_per_p) || 3
  }));

  const payload = {
    metadata: {
      title: document.getElementById("exam-title").value,
      subject: currentSubject,
      total_score: parseFloat(document.getElementById("stat-total-score").innerText),
      time_minutes: parseInt(document.getElementById("exam-time").value) || 45
    },
    unit_ids: selectedUnits,
    sections_config: normalizedSections
  };

  try {
    // 優先使用 SSE 串流以獲取實時進度回饋
    const response = await fetch("/api/generate-exam-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`伺服器錯誤: ${response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop(); // 保留尚未完整的最後一行

      for (const chunk of chunks) {
        const cleanChunk = chunk.trim();
        if (cleanChunk.startsWith("data: ")) {
          try {
            const data = JSON.parse(cleanChunk.substring(6));
            if (data.type === "progress") {
              progressFill.style.width = data.percent + "%";
              progressText.innerText = data.message;
            } else if (data.type === "complete") {
              progressFill.style.width = "100%";
              progressText.innerText = data.message;
              currentExamData = data.exam_data;
              renderExamPreview(data.exam_data);
            }
          } catch (jsonErr) {
            console.warn("SSE 解析警告:", jsonErr);
          }
        }
      }
    }

  } catch (e) {
    console.warn("SSE 串流失敗，改用標準同步調用回退:", e);
    progressText.innerText = "正在使用備援生成通道出題中，請稍候...";
    try {
      const res = await fetch("/api/generate-exam", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const examResult = await res.json();
      currentExamData = examResult;
      progressFill.style.width = "100%";
      progressText.innerText = "全卷生成完成！請在下方審閱題目。";
      renderExamPreview(examResult);
    } catch (fallbackErr) {
      progressText.innerText = `生成失敗: ${fallbackErr}`;
      alert(`出題失敗: ${fallbackErr}`);
    }
  }
}

// ==============================================================================
// 6. 線上審題與微調面板 (支援單題即時抽換)
// ==============================================================================
function renderExamPreview(examData) {
  const container = document.getElementById("generated-q-list");
  container.innerHTML = "";

  const sections = examData.sections || [];
  let totalQuestionsRendered = 0;

  sections.forEach((sec, sIdx) => {
    const sHeader = document.createElement("div");
    sHeader.style.margin = "1.8rem 0 0.8rem 0";
    sHeader.style.padding = "0.5rem 0.75rem";
    sHeader.style.backgroundColor = "#f1f5f9";
    sHeader.style.borderRadius = "6px";
    sHeader.style.display = "flex";
    sHeader.style.justifyContent = "space-between";
    sHeader.style.alignItems = "center";

    const questionsCount = (sec.questions || []).length + (sec.passages || []).reduce((acc, p) => acc + (p.sub_questions || []).length, 0);
    totalQuestionsRendered += questionsCount;

    sHeader.innerHTML = `
      <h3 style="font-size: 1rem; font-weight: 700; color: #1e293b; margin: 0;">${sec.section_title || `大題 ${sIdx+1}`}</h3>
      <span style="font-size: 0.82rem; color: #64748b; font-weight: 600;">共 ${questionsCount} 題 · 小計 ${sec.total_section_score || 0} 分</span>
    `;
    container.appendChild(sHeader);

    // 選擇題與非選卡片
    (sec.questions || []).forEach(q => {
      const qCard = document.createElement("div");
      qCard.className = "q-card";
      qCard.id = `q-card-${q.question_number}`;

      const isImageQ = q.has_chart || !!q.image_path;
      const chartImgHtml = isImageQ && q.image_path ? `
        <div style="text-align: center; margin: 0.85rem 0;">
          <img src="/${q.image_path.replace(/\\/g, '/')}" alt="題目插圖" style="max-width: 100%; max-height: 280px; border-radius: 6px; border: 1px solid #cbd5e1; box-shadow: 0 1px 3px rgba(0,0,0,0.1);" />
        </div>
      ` : '';

      const toggleBtnHtml = isImageQ ? `
        <button class="btn-sm-text" style="color: #475569;" onclick="toggleImageQuestion(${sIdx}, ${q.question_number}, false)">📝 轉回純文字題</button>
      ` : `
        <button class="btn-sm-text" style="color: #2563eb;" onclick="toggleImageQuestion(${sIdx}, ${q.question_number}, true)">🖼️ 轉為圖片題</button>
      `;

      const optionsHtml = Object.keys(q.options || {}).length > 0 ? `
        <div class="q-options-grid">
          ${Object.entries(q.options || {}).map(([optK, optV]) => `
            <div class="q-opt ${q.answer === optK ? 'correct' : ''}">
              (${optK}) ${optV}
            </div>
          `).join('')}
        </div>
      ` : '';

      qCard.innerHTML = `
        <div class="q-header">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span style="font-weight: 700; color: #1e293b;">第 ${q.question_number} 題</span>
            <span class="q-badge">${q.bloom_level || '應用'}</span>
            ${isImageQ ? '<span class="q-badge" style="background-color: #fef08a; color: #854d0e;">圖表題</span>' : ''}
            <span style="font-size: 0.78rem; color: #64748b;">(${q.score || 2} 分)</span>
          </div>
          <div style="display: flex; gap: 0.4rem;">
            ${toggleBtnHtml}
            <button class="btn-sm-text" onclick="regenerateQuestion(${sIdx}, ${q.question_number})">🔄 換一題</button>
          </div>
        </div>
        <div class="q-stem">${q.stem}</div>
        ${chartImgHtml}
        ${optionsHtml}
        <div class="q-explanation">
          <strong>【解答】${q.answer || '無'}</strong> ｜ <strong>【解析】</strong>${q.explanation || '依據文法與語境推導。'}
        </div>
      `;
      container.appendChild(qCard);
    });

    // 閱讀題組卡片
    (sec.passages || []).forEach((p, pIdx) => {
      const pBox = document.createElement("div");
      pBox.style.backgroundColor = "#f8fafc";
      pBox.style.border = "1px solid #cbd5e1";
      pBox.style.borderRadius = "8px";
      pBox.style.padding = "1.2rem";
      pBox.style.marginBottom = "1.2rem";

      const subQCount = (p.sub_questions || []).length;
      pBox.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.4rem;">
          <h4 style="font-size: 0.95rem; font-weight: 700; color: #1e293b;">📖 題組第 ${pIdx+1} 篇 (第 ${p.range_str || ''} 題)：${p.title || '閱讀文章'}</h4>
          <span style="font-size: 0.78rem; color: #64748b;">${subQCount} 題</span>
        </div>
        <p style="font-size: 0.88rem; line-height: 1.65; color: #334155; margin-bottom: 0.8rem; white-space: pre-line;">${p.content}</p>
      `;

      (p.sub_questions || []).forEach(sq => {
        pBox.innerHTML += `
          <div class="q-card" style="margin-top: 0.8rem; border-color: #e2e8f0;">
            <div class="q-header">
              <span style="font-weight: 700; font-size: 0.88rem;">第 ${sq.question_number} 題</span>
              <span class="q-badge">${sq.bloom_level || '理解'}</span>
            </div>
            <div class="q-stem" style="font-size: 0.88rem;">${sq.stem}</div>
            <div class="q-options-grid">
              ${Object.entries(sq.options || {}).map(([optK, optV]) => `
                <div class="q-opt ${sq.answer === optK ? 'correct' : ''}">(${optK}) ${optV}</div>
              `).join('')}
            </div>
            <div class="q-explanation" style="font-size: 0.8rem;">
              <strong>【解答】${sq.answer || 'A'}</strong> ｜ ${sq.explanation || '無'}
            </div>
          </div>
        `;
      });

      container.appendChild(pBox);
    });
  });

  const summaryBanner = document.createElement("div");
  summaryBanner.style.textAlign = "center";
  summaryBanner.style.padding = "1rem";
  summaryBanner.style.color = "#047857";
  summaryBanner.style.fontWeight = "600";
  summaryBanner.innerHTML = `✅ 全卷 ${sections.length} 個大題、共 ${totalQuestionsRendered} 題已全部呈現，請確認無誤後點擊下方匯出 Word 文件。`;
  container.prepend(summaryBanner);
}

// 單題一鍵抽換
async function regenerateQuestion(sIdx, qNum) {
  const card = document.getElementById(`q-card-${qNum}`);
  if (!card) return;

  const oldHtml = card.innerHTML;
  card.innerHTML = `<div style="text-align: center; padding: 1.5rem; color: #2563eb; font-weight: 600;">🔄 正在運用單元教材考點生成全新原創題...</div>`;

  const selectedUnits = [];
  document.querySelectorAll(".unit-checkbox:checked").forEach(cb => {
    selectedUnits.push(cb.value);
  });

  const targetSection = currentExamData.sections[sIdx];
  const targetQ = (targetSection.questions || []).find(x => x.question_number === qNum) || {};

  try {
    const res = await fetch("/api/regenerate-question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: currentSubject,
        unit_ids: selectedUnits,
        old_question: targetQ
      })
    });
    const newQ = await res.json();

    // 更新快取
    if (currentExamData && currentExamData.sections && currentExamData.sections[sIdx]) {
      const qs = currentExamData.sections[sIdx].questions || [];
      const targetIdx = qs.findIndex(x => x.question_number === qNum);
      if (targetIdx !== -1) {
        qs[targetIdx] = newQ;
      }
    }

    renderExamPreview(currentExamData);
  } catch (e) {
    alert(`抽換失敗: ${e}`);
    card.innerHTML = oldHtml;
  }
}

// 單選題與圖片題雙向切換
async function toggleImageQuestion(sIdx, qNum, toImage) {
  const card = document.getElementById(`q-card-${qNum}`);
  if (!card) return;

  const oldHtml = card.innerHTML;
  card.innerHTML = toImage
    ? `<div style="text-align: center; padding: 1.5rem; color: #2563eb; font-weight: 600;">🖼️ 正在繪製黑白高對比圖表並生成看圖題目...</div>`
    : `<div style="text-align: center; padding: 1.5rem; color: #2563eb; font-weight: 600;">📝 正在將題目轉回純文字單選題...</div>`;

  const selectedUnits = [];
  document.querySelectorAll(".unit-checkbox:checked").forEach(cb => {
    selectedUnits.push(cb.value);
  });

  const targetSection = currentExamData.sections[sIdx];
  const targetQ = (targetSection.questions || []).find(x => x.question_number === qNum) || {};

  const endpoint = toImage ? "/api/convert-to-image-question" : "/api/convert-to-text-question";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: currentSubject,
        unit_ids: selectedUnits,
        question_number: qNum,
        current_question: targetQ
      })
    });
    const newQ = await res.json();

    if (currentExamData && currentExamData.sections && currentExamData.sections[sIdx]) {
      const qs = currentExamData.sections[sIdx].questions || [];
      const targetIdx = qs.findIndex(x => x.question_number === qNum);
      if (targetIdx !== -1) {
        qs[targetIdx] = newQ;
      }
    }

    renderExamPreview(currentExamData);
  } catch (e) {
    alert(`切換失敗: ${e}`);
    card.innerHTML = oldHtml;
  }
}


// ==============================================================================
// 7. 一鍵成套 Word 匯出下載 (試題卷 + 作答紙 + 教師詳解本)
// ==============================================================================
async function exportWordSuite() {
  if (!currentExamData) {
    alert("尚未生成考卷資料！");
    return;
  }

  const btn = document.getElementById("btn-export-suite");
  btn.innerText = "⏳ 正在渲染成套 Word 文件 (雙欄排版與矩陣作答紙)...";
  btn.disabled = true;

  try {
    const res = await fetch("/api/export-docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentExamData)
    });
    const result = await res.json();
    btn.innerText = "匯出完成！";
    btn.disabled = false;

    // 切換至步驟三
    switchStep(3);
    const linkBox = document.getElementById("download-links-box");
    linkBox.innerHTML = `
      <div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; padding: 1.25rem; border-radius: 8px; margin-bottom: 1.5rem;">
        <h3 style="color: #065f46; font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem;">🎉 成套考卷已成功生成完畢！</h3>
        <p style="color: #047857; font-size: 0.85rem;">雙欄排版、選項自適應、手寫留白、矩陣作答紙與詳解本全部正確封裝完成。</p>
      </div>
      <div style="display: flex; flex-direction: column; gap: 0.85rem;">
        <a href="/api/download?file=${encodeURIComponent(result.files.question_paper)}" class="btn btn-primary" download>
          📄 下載【試題卷】(雙欄排版、題組生字註腳、非選留白)
        </a>
        <a href="/api/download?file=${encodeURIComponent(result.files.answer_sheet)}" class="btn btn-secondary" download>
          📝 下載【學生手寫作答紙】(10題一列表格矩陣、專用得分欄)
        </a>
        <a href="/api/download?file=${encodeURIComponent(result.files.teacher_solution)}" class="btn btn-secondary" download>
          🔑 下載【教師詳細解析本】(答案速查表、逐題精闢解析、全文翻譯)
        </a>
      </div>
    `;
  } catch (e) {
    btn.innerText = "匯出出錯，重試";
    btn.disabled = false;
    alert(`匯出失敗: ${e}`);
  }
}

// ==============================================================================
// 8. 介面輔助與事件監聽
// ==============================================================================
function switchStep(stepNum) {
  document.querySelectorAll(".step-item").forEach((el, idx) => {
    el.classList.toggle("active", idx === stepNum - 1);
  });
  document.querySelectorAll(".view-panel").forEach((el, idx) => {
    el.classList.toggle("active", idx === stepNum - 1);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function switchModeTab(mode) {
  document.querySelectorAll(".mode-tab").forEach(tab => {
    if (tab.dataset.mode) {
      tab.classList.toggle("active", tab.dataset.mode === mode);
    }
  });
  document.getElementById("mode-manual-content").style.display = (mode === "manual") ? "block" : "none";
  document.getElementById("mode-clone-content").style.display = (mode === "clone") ? "block" : "none";
}

function setupDropzones() {
  // 教材檔案 Dropzone
  const tbDropzone = document.getElementById("tb-dropzone");
  const tbInput = document.getElementById("tb-files-input");

  if (tbDropzone && tbInput) {
    ['dragenter', 'dragover'].forEach(eventName => {
      tbDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        tbDropzone.style.borderColor = "var(--primary)";
        tbDropzone.style.backgroundColor = "var(--primary-light)";
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      tbDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        tbDropzone.style.borderColor = "";
        tbDropzone.style.backgroundColor = "";
      });
    });

    tbDropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) handleTextbookUpload(files);
    });

    tbInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) handleTextbookUpload(e.target.files);
    });
  }
}

function setupEventListeners() {
  document.getElementById("subject-select").addEventListener("change", (e) => {
    loadSubjectTemplate(e.target.value);
  });

  document.querySelectorAll(".mode-tab").forEach(tab => {
    if (tab.dataset.mode) {
      tab.addEventListener("click", () => switchModeTab(tab.dataset.mode));
    }
  });

  const cloneInput = document.getElementById("clone-file-input");
  if (cloneInput) {
    cloneInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) handleCloneUpload(e.target.files[0]);
    });
  }
}
