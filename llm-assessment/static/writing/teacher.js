const modes = { themed: "主題式寫作", paragraph: "段落寫作", free: "自由寫作" };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function option(text, value) {
  const node = element("option", text);
  node.value = value;
  return node;
}

export function mountTeacher(root, { api }) {
  const $ = id => root.querySelector("#" + id);
  let assignments = [];
  let roster = [];
  let current = null;
  let references = [];
  let previewMaterial = null;
  let disposed = false;
  let selection = 0;
  let topicDraft = null;
  let review = null;

  function report(message) { $("teacher-status").textContent = message; }

  function resetPreview() {
    previewMaterial = null;
    $("material-preview").hidden = true;
    $("material-text").value = "";
  }

  function renderReferences() {
    const mode = $("room-mode").value;
    $("topic-generator").hidden = mode === "free";
    $("room-prompt").required = mode !== "free" && references.length === 0;
    $("room-prompt").placeholder = mode === "paragraph"
      ? "例如：用一段文字寫出主旨、至少兩個支持細節，以及收束句。"
      : "填寫主題、寫作情境或給學生的要求。";
    $("selected-materials").replaceChildren(...references.map(ref => {
      const row = element("div", undefined, "selected-material");
      const remove = element("button", "移除");
      remove.type = "button";
      remove.onclick = () => {
        references = references.filter(item => item.material_id !== ref.material_id);
        renderReferences();
      };
      row.append(element("span", `${ref.title}（${Array.from(ref.excerpt).length} 字）`), remove);
      return row;
    }));
  }

  function renderAssignments() {
    $("assignment-list").replaceChildren(...(assignments.length ? assignments.map(assignment => {
      const button = element("button", undefined, "assignment-item");
      button.type = "button";
      if (current?.id === assignment.id) button.setAttribute("aria-current", "true");
      button.append(element("strong", assignment.title), element("small",
        `${modes[assignment.mode]} · ${assignment.student_count} 位學生`));
      button.onclick = () => openAssignment(assignment.id).catch(error => report(error.message));
      return button;
    }) : [element("p", "還沒有寫作題目。", "writing-empty")]));
  }

  function renderStudents(students = []) {
    const assigned = new Set(students.map(student => student.student_id));
    $("assigned-students").replaceChildren(...students.map(student => element("span", student.display_name, "person")));
    $("assigned-students").hidden = students.length === 0;
    const available = roster.filter(student => !assigned.has(student.user_id));
    $("student-select").replaceChildren(...available.map(student =>
      option(`${student.display_name}（${student.email}）`, student.user_id)));
    $("student-select").disabled = available.length === 0;
    $("students-status").textContent = students.length
      ? `已分配給 ${students.length} 位學生，可繼續加入。`
      : available.length ? "選擇要收到這份寫作題目的學生。" : "請先到組員管理建立學生帳號。";
  }

  function showForm(data = null) {
    current = data?.assignment || null;
    references = data?.references.slice() || [];
    $("assignment-heading").textContent = current ? "寫作題目設定" : "出寫作題目";
    $("room-title").value = current?.title || "";
    $("room-mode").value = current?.mode || "themed";
    $("room-prompt").value = current?.prompt || "";
    $("room-target").value = current?.target ?? 0;
    $("room-limit").value = current?.suggestion_limit ?? 120;
    $("room-policy").value = current?.policy || "called";
    $("distribution").value = current?.distribution || "individual";
    $("distribution").disabled = Boolean(current);
    $("save-assignment").textContent = current ? "儲存題目設定" : "發出題目";
    $("submissions-panel").hidden = $("jump-submissions").hidden = !current;
    $("topic-instruction").value = "";
    $("topic-status").textContent = "";
    $("topic-preview").hidden = true;
    topicDraft = null;
    resetPreview();
    renderReferences();
    renderStudents(data?.students);
    renderAssignments();
    renderSubmissions(data?.submissions || []);
  }

  async function openAssignment(id) {
    const request = ++selection;
    const data = await api(`/api/writing/teacher?room=${encodeURIComponent(id)}`);
    if (disposed || request !== selection) return;
    showForm(data);
    report("");
    history.replaceState(null, "", `/writing?room=${encodeURIComponent(id)}`);
  }

  function newAssignment() {
    selection++;
    showForm();
    report("");
    history.replaceState(null, "", "/writing");
    $("room-title").focus();
  }

  $("new-assignment").onclick = newAssignment;
  $("jump-submissions").onclick = () => $("submissions-panel").scrollIntoView();
  $("refresh-submissions").onclick = async () => {
    if (!current) return;
    const id = current.id;
    try {
      const data = await api(`/api/writing/teacher?room=${encodeURIComponent(id)}`);
      if (!disposed && current?.id === id) renderSubmissions(data.submissions);
    } catch (error) { report(error.message); }
  };

  function renderSubmissions(submissions) {
    const items = submissions.map(submission => {
      const button = element("button", undefined, "version-item");
      button.type = "button";
      const status = submission.reopened_at ? "已開放修訂" : submission.reviewed_at ? `已批改 ${submission.score} 分` : "待批改";
      button.append(element("strong", submission.display_name),
        element("small", `第 ${submission.revision} 次繳交 · ${status}`));
      button.onclick = () => openReview(submission.id).catch(error => report(error.message));
      return button;
    });
    $("submission-list").replaceChildren(...(items.length ? items : [element("p", "目前還沒有學生繳交。")]));
    $("jump-submissions").textContent = `查看作業批改（${items.length}）`;
  }

  async function openReview(id) {
    const request = selection;
    const { submission } = await api(`/api/writing/review?id=${encodeURIComponent(id)}`);
    if (disposed || request !== selection) return;
    review = submission;
    const brief = element("p", submission.snapshot.prompt);
    const drafts = submission.snapshot.drafts.map(doc => {
      const section = element("section");
      section.append(element("h3", doc.title), element("pre", doc.body));
      return section;
    });
    $("review-title").textContent = `批改寫作作業 · ${submission.display_name}`;
    $("review-snapshot").replaceChildren(element("h3", submission.snapshot.title), brief, ...drafts);
    $("teacher-score").value = submission.score ?? "";
    $("teacher-feedback").value = submission.feedback || "";
    const reopened = Boolean(submission.reopened_at);
    for (const name of ["draft-review", "publish-review", "reopen-writing", "teacher-score", "teacher-feedback"]) {
      $(name).disabled = reopened;
    }
    $("review-status").textContent = reopened ? "此版本已開放修訂，可查看之前的批改。" : "";
    $("review-dialog").showModal();
  }

  $("close-review").onclick = () => $("review-dialog").close();
  $("draft-review").onclick = async () => {
    const id = review?.id;
    if (!id) return;
    const trigger = $("draft-review");
    trigger.disabled = true;
    $("review-status").textContent = "本機模型正在讀取稿件…";
    try {
      const result = await api("/api/writing/draft-review", { id });
      if (disposed || review?.id !== id || !$("review-dialog").open) return;
      $("teacher-score").value = result.score;
      $("teacher-feedback").value = result.feedback;
      $("review-status").textContent = result.partial
        ? "模型只閱讀了稿件前段。請人工核對全稿，再發布回饋。"
        : "已填入批改建議，可先修改再發布。";
    } catch (error) {
      if (!disposed && review?.id === id) $("review-status").textContent = error.message;
    } finally {
      if (!disposed && review?.id === id) trigger.disabled = false;
    }
  };

  async function finishReview(action) {
    const id = review?.id;
    if (!id) return;
    const button = $(action === "reopen" ? "reopen-writing" : "publish-review");
    button.disabled = true;
    try {
      const data = action === "reopen" ? { id, action } : {
        id, score: Number($("teacher-score").value), feedback: $("teacher-feedback").value,
      };
      await api("/api/writing/review", data);
      if (disposed || review?.id !== id) return;
      $("review-dialog").close();
      await $("refresh-submissions").onclick();
      report(action === "reopen" ? "已開放學生修訂並重新繳交。" : "批改回饋已發布。");
    } catch (error) {
      if (!disposed && review?.id === id) $("review-status").textContent = error.message;
    } finally {
      if (!disposed && review?.id === id) button.disabled = false;
    }
  }

  $("review-form").onsubmit = event => { event.preventDefault(); finishReview("publish"); };
  $("reopen-writing").onclick = () => finishReview("reopen");
  $("generate-topic").onclick = async () => {
    const trigger = $("generate-topic");
    const request = selection;
    const instruction = $("topic-instruction").value.trim();
    if (!instruction) {
      $("topic-status").textContent = "請先輸入你想怎麼引導學生的提示詞。";
      return;
    }
    trigger.disabled = true;
    $("topic-status").textContent = "本機模型正在起草題目…";
    try {
      const result = await api("/api/writing/generate-topic", {
        instruction, room: current?.id, mode: $("room-mode").value, target: Number($("room-target").value),
        references: references.map(({ material_id, excerpt }) => ({ material_id, excerpt })),
      });
      if (disposed || request !== selection) return;
      topicDraft = result;
      $("topic-result").textContent = `${result.title}\n\n${result.prompt}`;
      $("topic-preview").hidden = false;
      $("topic-status").textContent = "請檢查引導內容，再套用到題目設定。";
    } catch (error) {
      if (!disposed && request === selection) $("topic-status").textContent = error.message;
    } finally {
      if (!disposed) trigger.disabled = false;
    }
  };
  $("apply-topic").onclick = () => {
    if (!topicDraft) return;
    $("room-title").value = topicDraft.title;
    $("room-prompt").value = topicDraft.prompt;
    $("topic-status").textContent = "已套用，現在可修改題名和要求。";
  };
  $("room-mode").onchange = renderReferences;
  $("material-select").onchange = resetPreview;
  $("preview-material").onclick = async () => {
    const id = $("material-select").value;
    const request = selection;
    if (!id) return;
    try {
      const material = await api(`/api/writing/material?id=${encodeURIComponent(id)}`);
      if (disposed || request !== selection || id !== $("material-select").value) return;
      previewMaterial = material;
      $("material-title").textContent = material.title;
      $("material-text").value = material.text;
      $("material-text").setSelectionRange(0, 0);
      $("material-preview").hidden = false;
    } catch (error) { report(error.message); }
  };
  $("attach-material").onclick = () => {
    if (!previewMaterial) return;
    const editor = $("material-text");
    const selected = editor.value.slice(editor.selectionStart, editor.selectionEnd).trim();
    const excerpt = selected || Array.from(editor.value.trim()).slice(0, 1200).join("");
    if (!excerpt) return;
    if (Array.from(excerpt).length > 3000) return report("所選範圍最多 3000 字，請縮短選取。");
    const material_id = previewMaterial.id;
    const index = references.findIndex(item => item.material_id === material_id);
    if (index < 0 && references.length >= 5) return report("最多加入五份教材。");
    const reference = { material_id, title: previewMaterial.title, excerpt };
    if (index < 0) references.push(reference);
    else references[index] = reference;
    renderReferences();
    report("已加入教材範圍。");
  };

  $("assignment-form").onsubmit = async event => {
    event.preventDefault();
    const students = Array.from($("student-select").selectedOptions, node => node.value);
    if (!current && students.length === 0) return report("請選擇至少一位學生。");
    const submit = $("save-assignment");
    submit.disabled = true;
    try {
      const data = {
        title: $("room-title").value, mode: $("room-mode").value, prompt: $("room-prompt").value,
        target: Number($("room-target").value), suggestion_limit: Number($("room-limit").value),
        policy: $("room-policy").value,
        references: references.map(({ material_id, excerpt }) => ({ material_id, excerpt })),
      };
      let id = current?.id;
      if (id) {
        await api(`/api/writing/rooms/${id}/settings`, data);
        if (students.length) await api("/api/writing/teacher", { room: id, students });
      } else {
        ({ id } = await api("/api/writing/teacher", { ...data, students, distribution: $("distribution").value }));
      }
      if (disposed) return;
      ({ assignments } = await api("/api/writing/teacher"));
      await openAssignment(id);
      if (!disposed) report(students.length ? "題目已發出，學生可以開始作答。" : "題目設定已儲存。");
    } catch (error) {
      if (!disposed) report(error.message);
    } finally {
      if (!disposed) submit.disabled = false;
    }
  };

  async function boot() {
    showForm();
    $("preview-material").disabled = true;
    const [assignmentData, learnerData, materials] = await Promise.all([
      api("/api/writing/teacher"),
      api("/api/admin/learners"),
      api("/api/admin/exam/materials"),
    ]);
    if (disposed) return;
    assignments = assignmentData.assignments;
    roster = learnerData.learners.filter(student => !student.disabled);
    $("material-select").replaceChildren(...materials.materials.map(ref => option(`${ref.title} · ${ref.subject}`, ref.id)));
    $("preview-material").disabled = materials.materials.length === 0;
    $("materials-status").textContent = materials.materials.length
      ? "每份教材可選一段，最多加入五份。"
      : "目前沒有教材。可先到教材出題工作室匯入。";
    renderAssignments();
    renderStudents();
    const params = new URLSearchParams(location.search);
    const room = params.get("room");
    if (assignments.some(assignment => assignment.id === room)) {
      await openAssignment(room);
      if (!disposed && params.get("review")) await openReview(params.get("review"));
    }
  }

  boot().catch(error => { if (!disposed) report(error.message); });
  return () => { disposed = true; };
}
