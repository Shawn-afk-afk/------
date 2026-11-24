import {
  Y, EditorState, StateEffect, StateField, Prec, EditorView, Decoration, WidgetType,
  keymap, lineNumbers, defaultKeymap, yCollab, yUndoManagerKeymap,
} from "./editor-deps.js";

export function mountWriting(root, { session, styleNonce }) {
  const $ = id => root.querySelector("#" + id);
  const encode = bytes => {
    let result = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      result += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    }
    return btoa(result);
  };
  const decode = text => Uint8Array.from(atob(text), char => char.charCodeAt(0));
  const timeLabel = new Intl.DateTimeFormat("zh-TW", { hour: "2-digit", minute: "2-digit" });
  const dateLabel = new Intl.DateTimeFormat("zh-TW", { dateStyle: "medium", timeStyle: "short" });

  let disposed = false;
  let current = null;
  let rooms = [];
  let switching = false;
  let noticeTimer;
  let textAction;
  let roomAction;
  let compareVersion;
  let automatic = false;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function button(text, className, action) {
    const element = node("button", text, className);
    element.type = "button";
    element.addEventListener("click", action);
    return element;
  }

  function notice(text) {
    $("notice").textContent = text;
    $("notice").hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 4200);
  }

  async function api(path, payload) {
    const options = { cache: "no-store" };
    if (payload !== undefined) {
      options.method = "POST";
      options.headers = { "Content-Type": "application/json", "X-CSRF-Token": session?.csrf || "" };
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(response.status === 401 ? "登入已逾時，請重新登入知序" : data.error || "連線失敗");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function action(path, payload, ctx = current) {
    return api(`/api/writing/rooms/${ctx.room.id}${path}`, payload);
  }

  function busy(element, fn) {
    return async event => {
      event?.preventDefault();
      element.disabled = true;
      try { await fn(); }
      catch (error) { notice(error.message); }
      finally { element.disabled = false; }
    };
  }

  const setGhost = StateEffect.define();
  const setLocked = StateEffect.define();
  const lockedField = StateField.define({
    create: () => false,
    update(value, transaction) {
      for (const effect of transaction.effects) if (effect.is(setLocked)) value = effect.value;
      return value;
    },
  });
  class Ghost extends WidgetType {
    constructor(text) { super(); this.text = text; }
    eq(other) { return this.text === other.text; }
    toDOM() {
      const el = node("span", this.text, "ghost");
      el.setAttribute("aria-hidden", "true");
      return el;
    }
  }
  const ghostField = StateField.define({
    create: () => null,
    update(value, tr) {
      if (tr.docChanged || tr.selection) value = null;
      for (const effect of tr.effects) if (effect.is(setGhost)) value = effect.value;
      return value;
    },
    provide: field => EditorView.decorations.from(field, value => value
      ? Decoration.set(Decoration.widget({ widget: new Ghost(value.text), side: 1 }).range(value.at))
      : Decoration.none),
  });
  const setCursors = StateEffect.define();
  class PeerCursor extends WidgetType {
    constructor(name) { super(); this.name = name; }
    eq(other) { return this.name === other.name; }
    toDOM() {
      const marker = node("span", undefined, "peer-cursor");
      marker.title = this.name;
      marker.setAttribute("aria-label", `${this.name} 的游標`);
      return marker;
    }
  }
  const cursorField = StateField.define({
    create: () => Decoration.none,
    update(value, tr) {
      if (tr.docChanged) value = value.map(tr.changes);
      for (const effect of tr.effects) if (effect.is(setCursors)) value = effect.value;
      return value;
    },
    provide: field => EditorView.decorations.from(field),
  });

  function getGhost(view) { return view.state.field(ghostField); }
  function clearGhost(view) {
    if (!getGhost(view)) return false;
    view.dispatch({ effects: setGhost.of(null) });
    return true;
  }
  function acceptGhost(view) {
    const suggestion = getGhost(view);
    if (!suggestion || view.composing) return false;
    view.dispatch({
      changes: { from: suggestion.at, insert: suggestion.text },
      selection: { anchor: suggestion.at + suggestion.text.length },
      userEvent: "input.complete",
    });
    return true;
  }

  function backupKey(ctx) { return `zixu-writing:${session.user.id}:${ctx.file.id}`; }
  function backup(ctx) {
    try {
      if (ctx.pending) localStorage.setItem(backupKey(ctx), encode(ctx.pending));
      else localStorage.removeItem(backupKey(ctx));
      return true;
    } catch { return false; }
  }
  function mergeUpdate(ctx, update) {
    ctx.pending = ctx.pending ? Y.mergeUpdates([ctx.pending, update]) : update;
    const stored = backup(ctx);
    if (current === ctx) $("sync-status").textContent = stored ? "本機暫存，等待同步" : "等待同步";
    scheduleSync(ctx, 350);
  }

  function refreshEditor(ctx) {
    const content = ctx.editor.state.doc.toString();
    const count = Array.from(content.replace(/[\s\p{P}]/gu, "")).length;
    $("editor-count").textContent = ctx.room.target ? `${count} / ${ctx.room.target} 字` : `${count} 字`;
    const headings = [];
    for (const match of content.matchAll(/^#{1,6}\s+([^\n]+)$/gm)) {
      headings.push(button(match[1], "outline-link", () => jump(ctx, match.index, match[0].length)));
      if (headings.length >= 50) break;
    }
    $("outline").replaceChildren(...(headings.length ? headings : [node("p", "以 # 開頭的標題會顯示在這裡。")]));
  }

  function jump(ctx, at, length) {
    ctx.editor.dispatch({ selection: { anchor: at, head: at + length }, scrollIntoView: true });
    ctx.editor.focus();
  }

  function mountEditor(ctx, shared) {
    ctx.doc = new Y.Doc();
    ctx.file.version = shared.version;
    Y.applyUpdate(ctx.doc, decode(shared.state), "server");
    let recovered;
    try { recovered = localStorage.getItem(backupKey(ctx)); } catch { /* Available when browser storage is enabled. */ }
    if (recovered) {
      try {
        ctx.pending = decode(recovered);
        Y.applyUpdate(ctx.doc, ctx.pending, "recovery");
      } catch {
        ctx.pending = null;
        backup(ctx);
        notice("無法讀取此瀏覽器的暫存版本");
      }
    }
    const text = ctx.doc.getText("body");
    ctx.doc.on("update", (update, origin) => {
      if (origin !== "server") mergeUpdate(ctx, update);
    });
    ctx.editor = new EditorView({
      parent: $("editor"),
      state: EditorState.create({
        doc: text.toString(),
        extensions: [
          EditorView.cspNonce.of(styleNonce),
          lockedField,
          EditorState.readOnly.compute([lockedField], state => state.field(lockedField)),
          EditorView.editable.compute([lockedField], state => !state.field(lockedField)),
          EditorView.contentAttributes.of({ "aria-label": "文章正文", spellcheck: "false" }),
          EditorView.lineWrapping, lineNumbers(), yCollab(text, null), ghostField, cursorField,
          Prec.highest(keymap.of([
            { key: "Tab", run: acceptGhost }, { key: "Escape", run: clearGhost },
            { key: "Mod-s", run: () => { sync(ctx, true).catch(error => notice(error.message)); return true; } },
            { key: "Mod-Enter", run: () => { askInline(ctx, true); return true; } },
            ...yUndoManagerKeymap.map(binding => ({
              ...binding, run: view => !ctx.locked && binding.run(view),
            })),
          ])),
          keymap.of(defaultKeymap),
          EditorView.updateListener.of(update => {
            if (current !== ctx) return;
            $("inline-label").hidden = !getGhost(update.view);
            if (update.docChanged) refreshEditor(ctx);
            if (update.selectionSet) scheduleSync(ctx, 350);
            if (update.docChanged || update.selectionSet) clearTimeout(ctx.inlineTimer);
            if (automatic && update.docChanged && update.transactions.some(tr => tr.isUserEvent("input.type"))) {
              ctx.inlineTimer = setTimeout(() => askInline(ctx), 1150);
            }
          }),
        ],
      }),
    });
    refreshEditor(ctx);
  }

  async function askInline(ctx, manual = false) {
    if (!ctx || ctx !== current || ctx.locked || ctx.inlineBusy || ctx.editor.composing || ctx.room.policy === "off") return;
    if (ctx.room.suggestion_limit === 0) return;
    const { state } = ctx.editor;
    const { head, empty } = state.selection.main;
    const line = state.doc.lineAt(head);
    const before = state.doc.sliceString(Math.max(0, head - 1100), head);
    if (!empty || head !== line.to || !before.trim() || /[。！？.?!\n]\s*$/.test(before)) {
      if (manual) notice("把游標放在未寫完句子的行尾");
      return;
    }
    ctx.inlineBusy = true;
    if (manual) ctx.editor.focus();
    try {
      const reply = await action("/complete", { doc: ctx.file.id, before }, ctx);
      if (ctx !== current || ctx.locked || ctx.room.policy === "off" || ctx.editor.composing) return;
      const latest = ctx.editor.state;
      if (latest.doc !== state.doc || latest.selection.main.head !== head || !latest.selection.main.empty) return;
      if (reply.text) ctx.editor.dispatch({ effects: setGhost.of({ text: reply.text, at: head }) });
      else if (manual) notice("這裡暫時沒有自然的接法");
    } catch (error) {
      if (manual && ctx === current) notice(error.message);
    } finally {
      ctx.inlineBusy = false;
    }
  }

  function scheduleSync(ctx, wait = 1400) {
    clearTimeout(ctx.timer);
    if (ctx !== current) return;
    ctx.timer = setTimeout(() => sync(ctx).catch(error => {
      if (current !== ctx) return;
      $("sync-status").textContent = error.status === 401 || error.status === 413 ? error.message : "同步暫停，將重試";
      scheduleSync(ctx, 3000);
    }), wait);
  }

  function applyShared(ctx, shared) {
    if (!shared || shared.id !== ctx.file.id || shared.version < ctx.file.version) return;
    if (ctx.editor.composing) return;
    ctx.file.version = shared.version;
    Y.applyUpdate(ctx.doc, decode(shared.state), "server");
  }

  async function sync(ctx, flush = false) {
    if (!ctx || ctx !== current) return;
    if (ctx.saving) {
      await ctx.saving;
      if (flush && !ctx.locked && (ctx.pending || ctx.editor.composing)) return sync(ctx, true);
      return;
    }
    if (flush && ctx.editor.composing) throw new Error("請先完成目前輸入");
    const save = async () => {
      const pending = ctx.locked ? null : ctx.pending;
      const cursor = encode(Y.encodeRelativePosition(Y.createRelativePositionFromTypeIndex(
        ctx.doc.getText("body"), ctx.editor.state.selection.main.head,
      )));
      if (pending || cursor !== ctx.lastCursor || Date.now() - ctx.presence > 10000) {
        try {
          const shared = await action("/sync", { doc: ctx.file.id, update: pending ? encode(pending) : null, cursor }, ctx);
          if (pending && ctx.pending === pending) ctx.pending = null;
          // A later pending update may include edits the server has already acknowledged.
          backup(ctx);
          ctx.presence = Date.now();
          ctx.lastCursor = cursor;
          if (ctx === current) applyShared(ctx, shared);
        } catch (error) {
          if (!pending || error.status !== 409) throw error;
          // A teammate may have submitted while these edits were still local.
        }
      }
      const query = new URLSearchParams({ doc: ctx.file.id, version: String(ctx.file.version) });
      const state = await action(`?${query}`, undefined, ctx);
      if (ctx !== current) return;
      applyShared(ctx, state.shared);
      renderRoom(ctx, state);
      $("sync-status").textContent = ctx.locked
        ? (ctx.pending ? "已繳交，另有本機暫存修改" : "已繳交")
        : (ctx.pending ? "本機暫存，等待同步" : "已同步");
    };
    ctx.saving = save();
    try { await ctx.saving; }
    finally { ctx.saving = null; }
    if (flush && ctx.pending && !ctx.locked) return sync(ctx, true);
    scheduleSync(ctx);
  }

  function updateRooms() {
    const old = $("room-select").value;
    const groups = [
      ["老師發出的題目", rooms.filter(room => !room.owner)],
      ["我的自由稿", rooms.filter(room => room.owner)],
    ];
    $("room-select").replaceChildren(...groups.filter(([, entries]) => entries.length).map(([label, entries]) => {
      const group = node("optgroup");
      group.label = label;
      group.append(...entries.map(room => {
        const option = node("option", room.title);
        option.value = room.id;
        return option;
      }));
      return group;
    }));
    $("room-select").value = current?.room.id || old || rooms[0]?.id || "";
    $("room-select").hidden = rooms.length === 0;
  }

  async function openRoom(roomId, docId, initial = false) {
    if (switching) return;
    switching = true;
    try {
      if (current?.pending) await sync(current, true);
      let state = await api(`/api/writing/rooms/${roomId}`);
      const file = state.docs.find(doc => doc.id === docId) || state.docs[0];
      state = await api(`/api/writing/rooms/${roomId}?doc=${file.id}`);
      if (disposed) return;
      if (current) {
        if (current.pending) await sync(current, true);
        if (disposed) return;
        clearTimeout(current.timer);
        clearTimeout(current.inlineTimer);
        current.editor.destroy();
        current.doc.destroy();
      }
      $("editor").replaceChildren();
      const ctx = { room: state.room, file, pending: null, presence: 0, signature: {}, quote: null };
      current = ctx;
      updateRooms();
      $("studio").hidden = false;
      $("welcome").hidden = true;
      $("chapter-title").textContent = file.title;
      $("message").value = "";
      setQuote(null);
      mountEditor(ctx, state.shared);
      renderRoom(ctx, state);
      await selectPane("chat");
      const query = new URLSearchParams({ room: roomId, doc: file.id });
      history.replaceState(null, "", `/writing?${query}`);
      scheduleSync(ctx, 100);
      if (!initial) ctx.editor.focus();
      return ctx;
    } finally {
      switching = false;
      updateRooms();
    }
  }

  function rendered(ctx, part, value) {
    const signature = JSON.stringify(value);
    if (signature === ctx.signature[part]) return true;
    ctx.signature[part] = signature;
    return false;
  }

  function renderRoom(ctx, state) {
    ctx.room = state.room;
    ctx.docs = state.docs;
    const room = state.room;
    if (!rendered(ctx, "chapters", state.docs.map(({ id, title }) => [id,title]))) {
      $("chapter-list").replaceChildren(...state.docs.map(file => {
        const item = button("", "", busyPlaceholder(() => openRoom(room.id, file.id)));
        item.append(node("span", "▤", "file-mark"), document.createTextNode(file.title));
        item.firstChild.setAttribute("aria-hidden", "true");
        if (file.id === ctx.file.id) item.setAttribute("aria-current", "true");
        return item;
      }));
    }
    if (!rendered(ctx, "room", room)) {
      const mode = { themed: "主題式寫作", paragraph: "段落寫作", free: "自由寫作" }[room.mode];
      $("mode-status").textContent = mode;
      $("settings").hidden = !room.owner;
      $("brief-text").textContent = room.prompt || (room.mode !== "free"
        ? "依下列教材範圍寫作。" : "這個作品可以自由發展。");
      $("room-references").replaceChildren(...room.references.map(ref => {
        const detail = node("details", undefined, "sunken-panel");
        detail.append(node("summary", ref.title), node("small", [ref.subject, ref.locator].filter(Boolean).join(" · ")),
          node("p", ref.excerpt, "excerpt"));
        return detail;
      }));
      if (room.policy === "off" || !room.suggestion_limit) clearGhost(ctx.editor);
      $("mention").disabled = room.policy === "off";
      refreshEditor(ctx);
    }
    renderSubmission(ctx, state.submission);
    const paused = room.paused_until > Date.now() / 1000;
    const policy = { off: "助教關閉", called: "助教 · 僅受呼叫時回應", active: paused ? "助教 · 主動發言已暫停" : "助教 · 可以主動發言" };
    $("policy-label").textContent = policy[room.policy];
    $("pause").hidden = room.policy !== "active" || paused;
    if (!rendered(ctx, "people", state.people)) {
      $("people").replaceChildren(...state.people.map(user => {
        const person = node("span", user.display_name, "person");
        const file = state.docs.find(doc => doc.id === user.doc_id);
        person.dataset.online = Boolean(file);
        person.title = file ? `正在編輯〈${file.title}〉` : "未在線";
        return person;
      }));
    }
    const peers = state.people.filter(person => person.id !== session.user.id && person.doc_id === ctx.file.id && person.cursor);
    if (!ctx.editor.composing && !rendered(ctx, "cursors", [ctx.file.version, peers])) {
      const cursors = [];
      const text = ctx.doc.getText("body");
      for (const peer of peers) {
        try {
          const anchor = Y.decodeRelativePosition(decode(peer.cursor));
          const position = Y.createAbsolutePositionFromRelativePosition(anchor, ctx.doc);
          if (position?.type === text && position.index <= ctx.editor.state.doc.length) {
            cursors.push(Decoration.widget({ widget: new PeerCursor(peer.display_name), side: -1 }).range(position.index));
          }
        } catch { /* A stale or malformed remote cursor can be ignored. */ }
      }
      ctx.editor.dispatch({ effects: setCursors.of(Decoration.set(cursors, true)) });
    }
    if (!rendered(ctx, "messages", state.messages)) renderMessages(ctx, state.messages);
  }

  function renderSubmission(ctx, submission) {
    const locked = Boolean(submission && !submission.reopened_at);
    if (locked !== Boolean(ctx.locked)) {
      ctx.locked = locked;
      ctx.editor.dispatch({ effects: setLocked.of(locked) });
      clearGhost(ctx.editor);
    }
    const room = ctx.room;
    $("submission-bar").hidden = !room.can_submit;
    $("submit-writing").disabled = locked;
    $("submit-writing").textContent = locked ? "已繳交" : submission ? "重新繳交" : "繳交作業";
    $("submission-progress").textContent = locked
      ? (submission.reviewed_at ? "已批改，可查看回饋" : "作業已送到老師的批改清單")
      : submission ? "老師已開放修訂，完成後請重新繳交" : "尚未繳交 · 寫完後請按繳交作業";
    $("show-feedback").hidden = !room.can_submit;
    $("snapshot").disabled = locked;
    $("new-chapter").hidden = locked || room.mode === "paragraph";
    $("inline-enabled").disabled = $("try-inline").disabled = locked || room.policy === "off" || !room.suggestion_limit;
    if (rendered(ctx, "submission", submission)) return;
    $("submission-status").textContent = submission
      ? `第 ${submission.revision} 次繳交 · ${submission.reopened_at ? "已開放修訂" : submission.reviewed_at ? "已批改" : "等待老師批改"}`
      : "尚未繳交。";
    $("review-score").textContent = submission?.reviewed_at ? `${submission.score} / 100` : "";
    $("review-feedback").textContent = submission?.feedback || "";
  }

  function busyPlaceholder(fn) {
    return async () => {
      try { await fn(); }
      catch (error) { notice(error.message); }
    };
  }

  function renderMessages(ctx, messages) {
    const view = $("messages");
    const atEnd = view.scrollHeight - view.scrollTop - view.clientHeight < 45;
    const entries = messages.map(message => {
      const entry = node("article", undefined, "entry");
      entry.dataset.ai = message.kind !== "human";
      const title = node("h3", message.author);
      if (message.kind === "observation") title.append(node("small", "主動提問"));
      else title.append(node("time", timeLabel.format(new Date(message.created_at * 1000))));
      entry.append(title);
      if (message.quote) entry.append(button(message.quote, "quote-link", busyPlaceholder(() => showQuote(ctx, message))));
      entry.append(node("p", message.body));
      if (message.example) {
        entry.append(node("small", "助教示例"), node("blockquote", message.example));
        entry.append(button("在游標處插入", "button quiet", () => {
          const { editor } = ctx;
          if (ctx.locked || editor.composing) return;
          const { head } = editor.state.selection.main;
          editor.dispatch({
            changes: { from: head, insert: message.example },
            selection: { anchor: head + message.example.length }, userEvent: "input.complete",
          });
          editor.focus();
        }));
      }
      const pending = { queued: "等待助教", running: "助教思考中", failed: "助教暫時無法回答，可再次呼叫", cancelled: "助教已關閉" };
      if (pending[message.tutor_status]) entry.append(node("small", pending[message.tutor_status]));
      return entry;
    });
    view.replaceChildren(...(entries.length ? entries : [node("p", "還沒有訊息。可以討論稿件，或用 @助教 問一個問題。", "writing-empty")]));
    if (atEnd) view.scrollTop = view.scrollHeight;
  }

  async function showQuote(ctx, message) {
    if (message.doc_id !== ctx.file.id) ctx = await openRoom(ctx.room.id, message.doc_id);
    const content = ctx.editor.state.doc.toString();
    const start = content.indexOf(message.quote);
    if (start < 0) throw new Error("被引用的文字已修改，討論中保留原文");
    jump(ctx, start, message.quote.length);
  }

  function setQuote(quote) {
    if (current) current.quote = quote;
    $("quoted").hidden = !quote;
    $("quoted-text").textContent = quote?.text || "";
  }

  async function selectPane(pane) {
    const chat = pane === "chat";
    const versions = pane === "versions";
    $("show-chat").setAttribute("aria-pressed", String(chat));
    $("show-versions").setAttribute("aria-pressed", String(versions));
    $("show-feedback").setAttribute("aria-pressed", String(pane === "feedback"));
    $("chat-pane").hidden = !chat;
    $("versions-pane").hidden = !versions;
    $("feedback-pane").hidden = pane !== "feedback";
    if (versions) await loadVersions(current);
  }

  async function loadVersions(ctx) {
    const { versions } = await action(`/versions?doc=${ctx.file.id}`, undefined, ctx);
    if (ctx !== current) return;
    $("versions").replaceChildren(...(versions.length ? versions.map(version => {
      const item = button(version.label, "version-item", busyPlaceholder(() => viewVersion(ctx, version.id)));
      item.append(node("small", `${version.display_name} · ${dateLabel.format(new Date(version.created_at * 1000))}`));
      return item;
    }) : [node("p", "存下初稿或修訂稿，就能在這裡比對。", "writing-empty")]));
  }

  async function viewVersion(ctx, id) {
    await sync(ctx, true);
    const version = await action(`/version?doc=${ctx.file.id}&id=${id}`, undefined, ctx);
    if (ctx !== current) return;
    compareVersion = { id, version: version.version, ctx };
    $("saved-label").textContent = version.label;
    $("saved-body").textContent = version.saved || "（空白）";
    $("current-body").textContent = version.current || "（空白）";
    $("restore").hidden = !ctx.room.owner;
    $("version-dialog").showModal();
  }

  function editSettings(room) {
    roomAction = room?.id ? "edit" : "create";
    $("room-dialog-title").textContent = room?.id ? "作品設定" : "開始自由寫作";
    $("room-title").value = room?.title || "";
    $("room-policy").value = room?.policy || "called";
    $("room-dialog").showModal();
  }

  function textDialog(title, label, max, callback) {
    textAction = callback;
    $("text-dialog-title").textContent = title;
    $("text-label").textContent = label;
    $("dialog-input").value = "";
    $("dialog-input").maxLength = max;
    $("text-dialog").showModal();
  }

  async function getRooms() {
    const result = await api("/api/writing/rooms");
    if (disposed || JSON.stringify(rooms) === JSON.stringify(result.rooms)) return;
    rooms = result.rooms;
    updateRooms();
  }

  async function boot() {
    await getRooms();
    if (disposed) return;
    $("role-label").textContent = "學生寫作區";
    $("new-room").textContent = "自由寫作";
    $("workspace-controls").hidden = false;
    if (!rooms.length) {
      $("welcome-text").textContent = "老師發出的題目會出現在作品清單，你也可以先開始自己的自由寫作。";
      $("welcome-create").textContent = "開始自由寫作";
      $("welcome-create").hidden = false;
      $("sync-status").textContent = "已登入";
      return;
    }
    const params = new URLSearchParams(location.search);
    const selected = rooms.find(room => room.id === params.get("room")) || rooms[0];
    await openRoom(selected.id, params.get("doc"), true);
  }

  $("new-room").onclick = $("welcome-create").onclick = () => editSettings();
  $("settings").onclick = () => editSettings(current.room);
  $("room-select").onchange = () => busyPlaceholder(() => openRoom($("room-select").value))();
  const refreshRooms = async () => {
    if (disposed) return;
    try {
      await getRooms();
      if (!disposed && !current && rooms.length && !$("room-dialog").open) {
        await openRoom(rooms[0].id, undefined, true);
      }
    } catch { /* Keep the current workspace usable when the connection drops. */ }
  };
  window.addEventListener("focus", refreshRooms);
  const roomTimer = setInterval(refreshRooms, 8000);
  $("room-form").onsubmit = busy($("room-form").querySelector('[type="submit"]'), async () => {
    const data = {
      title: $("room-title").value, policy: $("room-policy").value,
    };

    const target = roomAction === "edit" ? current.room.id : null;
    const result = target ? await action("/settings", data) : await api("/api/writing/rooms", data);
    $("room-dialog").close();
    await getRooms();
    if (target) await sync(current);
    else await openRoom(result.id);
    notice(target ? "設定已儲存" : "作品已建立");
  });
  $("text-form").onsubmit = busy($("text-form").querySelector('[type="submit"]'), async () => {
    await textAction($("dialog-input").value);
    $("text-dialog").close();
  });
  for (const close of root.querySelectorAll("[data-close]")) close.onclick = () => close.closest("dialog").close();

  $("new-chapter").onclick = () => textDialog("新增篇章", "篇章名稱", 100, async title => {
    const ctx = current;
    await sync(ctx, true);
    const data = await action("/chapter", { title }, ctx);
    await openRoom(ctx.room.id, data.id);
  });
  $("snapshot").onclick = () => textDialog("儲存版本", "版本名稱", 80, async label => {
    const ctx = current;
    await sync(ctx, true);
    await action("/snapshot", { doc: ctx.file.id, label }, ctx);
    await selectPane("versions");
    notice("已儲存版本");
  });
  $("restore").onclick = busy($("restore"), async () => {
    const { ctx, id, version } = compareVersion;
    await sync(ctx, true);
    const shared = await action("/restore", { doc: ctx.file.id, id, version }, ctx);
    applyShared(ctx, shared);
    $("version-dialog").close();
    await loadVersions(ctx);
    notice("已還原。還原前的稿件已保存為版本");
  });
  $("export").onclick = () => {
    const ctx = current;
    const text = ctx.editor.state.doc.toString();
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const link = node("a");
    link.href = url;
    link.download = `${ctx.file.title.replace(/[\\/:*?"<>|]/g, "-")}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  };
  $("pause").onclick = busy($("pause"), async () => {
    await action("/pause", {});
    await sync(current);
    notice("已暫停主動發言十分鐘，仍可 @助教");
  });
  $("show-chat").onclick = () => selectPane("chat");
  $("show-versions").onclick = busyPlaceholder(() => selectPane("versions"));
  $("show-feedback").onclick = () => selectPane("feedback");
  $("submit-writing").onclick = () => {
    $("submit-note").textContent = current.room.distribution === "group"
      ? "將繳交整組目前的稿件。繳交後，等老師開放修訂才能繼續改。"
      : "將繳交目前的稿件。繳交後，等老師開放修訂才能繼續改。";
    $("submit-dialog").showModal();
  };
  $("confirm-writing").onclick = busy($("confirm-writing"), async () => {
    const ctx = current;
    try {
      await sync(ctx, true);
      const { submission } = await action("/submit", { doc: ctx.file.id, version: ctx.file.version }, ctx);
      if (ctx !== current) return;
      renderSubmission(ctx, submission);
      $("sync-status").textContent = "已繳交";
      $("submit-dialog").close();
      await selectPane("feedback");
      notice("作業已繳交");
    } catch (error) {
      $("submit-note").textContent = error.message;
    }
  });
  $("quote-selection").onclick = () => {
    const { state } = current.editor;
    const { from, to } = state.selection.main;
    const text = state.doc.sliceString(from, to).trim().slice(0, 450);
    if (!text) return notice("先在編輯器選取要討論的文字");
    selectPane("chat");
    setQuote({ text, id: current.file.id });
    $("message").focus();
  };
  $("remove-quote").onclick = () => setQuote(null);
  $("mention").onclick = () => {
    const target = $("message");
    if (!target.value.includes("@助教")) target.setRangeText("@助教 ", 0, 0, "end");
    target.focus();
  };
  $("message-form").onsubmit = busy($("send"), async () => {
    const text = $("message").value.trim();
    if (!text) return;
    const ctx = current;
    await sync(ctx, true);
    const quote = ctx.quote;
    await action("/message", { text, doc: quote?.id || ctx.file.id, quote: quote?.text || "" }, ctx);
    if (ctx !== current) return;
    $("message").value = "";
    setQuote(null);
    await sync(ctx);
  });
  try { automatic = localStorage.getItem("zixu-writing:inline") === "on"; } catch { /* Preference is optional. */ }
  $("inline-enabled").checked = automatic;
  $("inline-enabled").onchange = () => {
    automatic = $("inline-enabled").checked;
    try { localStorage.setItem("zixu-writing:inline", automatic ? "on" : "off"); } catch { /* Browser storage may be unavailable. */ }
    if (!automatic && current) {
      clearTimeout(current.inlineTimer);
      clearGhost(current.editor);
    }
  };
  $("try-inline").onclick = busy($("try-inline"), () => askInline(current, true));

  boot().catch(error => {
    if (disposed) return;
    $("studio").hidden = true;
    $("welcome").hidden = false;
    $("welcome-text").textContent = error.message;
    $("sync-status").textContent = "連線失敗";
  });

  return function unmount() {
    disposed = true;
    window.removeEventListener("focus", refreshRooms);
    clearInterval(roomTimer);
    clearTimeout(noticeTimer);
    const ctx = current;
    current = null;
    if (!ctx) return;
    clearTimeout(ctx.timer);
    clearTimeout(ctx.inlineTimer);
    if (ctx.pending && !ctx.locked) {
      // The browser backup remains until a subsequent sync acknowledges it.
      action("/sync", { doc: ctx.file.id, update: encode(ctx.pending) }, ctx).catch(() => {});
    }
    ctx.editor.destroy();
    ctx.doc.destroy();
  };
}
