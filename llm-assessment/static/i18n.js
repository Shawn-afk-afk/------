/* Interface localization only: question content and editable values are preserved. */
'use strict';
const i18n=(()=>{
 const locales={'zh-TW':'繁體中文',en:'English',ja:'日本語',es:'Español'};
 const dateLocales={'zh-TW':'zh-TW',en:'en-US',ja:'ja-JP',es:'es-ES'};
 const entries=window.INTERFACE_TRANSLATIONS||[];
 const catalog=new Map(entries.map(([source,en,ja,es])=>[source,{en,ja,es}]));
 const fragments=entries.map(e=>e[0]).filter(s=>s.length>=4&&!/[{}]/.test(s)).sort((a,b)=>b.length-a.length);
 const escapeRegex=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 const fragmentRegex=new RegExp(fragments.map(escapeRegex).join('|'),'g');
 const protectedSelector='[data-no-i18n],script,style,textarea,pre,code,blockquote,.prompt,.question-title,.card-text,.selection-options,.guide-answer,.guide-box li,.case-chart,.avatar,.profile .tiny,.studio-unit strong,.studio-material-list strong,.model-source-row strong,.model-slot p,#canvas-independent-prompt,[data-proposal],.select-question b,.selected-row .tiny,.match-row>span,label:has([data-recipient]),.task-card h3';
 const originals=new WeakMap(),attributes=new WeakMap(),dateValues=new Map();
 let locale='zh-TW',observer,scheduled=false,preferenceQueue=Promise.resolve();
 try{const stored=localStorage.getItem('zhixu.ui.locale');if(locales[stored])locale=stored;}catch{}
 function t(source){return locale==='zh-TW'?source:catalog.get(source)?.[locale]||source;}
 function text(source){
  if(locale==='zh-TW')return source;
  const trimmed=source.trim(),exact=catalog.get(trimmed);
  if(exact)return source.replace(trimmed,exact[locale]);
  const patterns=[
   [/^(\d+) \/ (\d+) 段$/,['$1 / $2 chunks','$1 / $2段','$1 / $2 fragmentos']],
   [/^相似度 ([\d.-]+)$/,['Similarity $1','類似度 $1','Similitud $1']],
   [/^期限：(.+)$/, ['Due: $1','期限：$1','Fecha límite: $1']],
   [/^顯示 (\d+) 題$/,['Showing $1 questions','$1問を表示','$1 preguntas']],
   [/^(\d+) 題可選$/,['$1 questions available','$1問を選択可能','$1 preguntas disponibles']],
   [/^第 (\d+) \/ (\d+) 題 · ([\d.]+) 分$/,['Question $1 / $2 · $3 points','$1 / $2問 · $3点','Pregunta $1 / $2 · $3 puntos']],
   [/^(\d+) 題 · 總分 ([\d.]+)$/,['$1 questions · $2 points','$1問 · 合計$2点','$1 preguntas · $2 puntos']],
   [/^(\d+) 題 \/ (\d+) 人$/,['$1 questions / $2 members','$1問 / $2人','$1 preguntas / $2 integrantes']],
   [/^第 (\d+) 回合 · (.+)$/,['Round $1 · $2','$1回目 · $2','Ronda $1 · $2']],
   [/^題 (\d+) · ([\d.]+) 分$/,['Question $1 · $2 points','問題$1 · $2点','Pregunta $1 · $2 puntos']],
   [/^已核准 (\d+) 題$/,['Approved $1 questions','$1問を承認しました','$1 preguntas aprobadas']],
   [/^已匯入 (\d+) 題待覆核草稿$/,['Imported $1 drafts for review','$1問の草稿を取り込みました','$1 borradores importados']],
   [/^已新增 (\d+) 題待覆核草稿，請至題庫核准$/,['Added $1 drafts. Approve them in the question bank.','$1問の草稿を追加しました。問題バンクで承認してください。','$1 borradores añadidos. Apruébalos en el banco.']],
   [/^來源已載入：(\d+) 個單元$/,['Loaded $1 material units','$1単元を読み込みました','$1 unidades cargadas']],
   [/^版本 (\d+) · (.+)$/,['Version $1 · $2','版$1 · $2','Versión $1 · $2']],
   [/^(\d+) 份等待或正在分析$/,['$1 queued or analyzing','$1件が待機・分析中','$1 en espera o análisis']],
   [/^(\d+) 題 · 題幹、答案、規準與版本統一管理。$/,['$1 questions · Prompts, answers, rubrics and versions in one place.','$1問 · 問題文・解答・基準・版を一元管理。','$1 preguntas · Enunciados, respuestas, criterios y versiones unificados.']],
   [/^這份評量共有 (\d+) 題。繳交後會開始背景批改；尚未作答的部分會記為未展現。$/,['This assessment has $1 questions. Grading starts after submission; unanswered parts have no evidence.','この評価は$1問です。提出後に採点され、未回答の部分は根拠なしと扱われます。','Esta evaluación tiene $1 preguntas. Las partes sin respuesta se consideran sin evidencia.']],
   [/^通過 (\d+) \/ (\d+) 個公開與隱藏測試$/,['Passed $1 / $2 public and hidden tests','公開・非公開テスト $1 / $2件に合格','$1 / $2 pruebas públicas y ocultas superadas']],
   [/^分項評分規準 · ([\d.]+) 分$/,['Rubric · $1 points','項目別基準 · $1点','Criterios · $1 puntos']],
   [/^選擇 (.+)$/,['Select $1','$1を選択','Seleccionar $1']],
   [/^(.+) 的對應$/,['Match for $1','$1の対応','Relación de $1']],
  ];
  const languageIndex={en:0,ja:1,es:2}[locale];
  for(const [pattern,translations] of patterns){const match=trimmed.match(pattern);if(match){const result=translations[languageIndex].replace(/\$(\d+)/g,(_,index)=>t(match[Number(index)]));return source.replace(trimmed,result);}}
  let output=source.replace(fragmentRegex,key=>t(key));
  output=output.replace(/(^|[\s·/（:：])(可用|尚未就緒|待評|已儲存|未設定|已核准|已驗證)(?=$|[\s·/（）:：])/g,(_,prefix,value)=>prefix+t(value));
  output=output.replace(/(\d+(?:\.\d+)?)\s*分(?![\u4e00-\u9fff])/g,(_,n)=>({en:`${n} points`,ja:`${n}点`,es:`${n} puntos`}[locale]));
  output=output.replace(/(\d+)\s*級/g,(_,n)=>({en:`Level ${n}`,ja:`レベル${n}`,es:`Nivel ${n}`}[locale]));
  return output;
 }
 function date(value){
  const rendered=new Date(value).toLocaleString(dateLocales[locale],{timeZone:'Asia/Taipei',hour12:false});
  dateValues.set(rendered,value);if(dateValues.size>5000)dateValues.delete(dateValues.keys().next().value);
  return rendered;
 }
 function localizeNode(node){
  const parent=node.parentElement;if(!parent||parent.closest(protectedSelector)||!node.nodeValue.trim())return;
  const old=originals.get(node),source=old&&node.nodeValue===old.output?old.source:node.nodeValue;
  const value=dateValues.get(source.trim());
  const output=value!==undefined?source.replace(source.trim(),date(value)):text(source);
  originals.set(node,{source,output});if(output!==node.nodeValue)node.nodeValue=output;
 }
 function apply(root=document.body){
  if(!root)return;
  observer?.disconnect();
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode())localizeNode(node);
  for(const element of root.querySelectorAll('[placeholder],[aria-label],[title]')){
   if(element.closest('[data-no-i18n],pre,code'))continue;
   let saved=attributes.get(element);if(!saved){saved={};attributes.set(element,saved);}
   for(const name of ['placeholder','aria-label','title'])if(element.hasAttribute(name)){
    const current=element.getAttribute(name),old=saved[name],source=old&&old.output===current?old.source:current,output=text(source);
    saved[name]={source,output};if(output!==current)element.setAttribute(name,output);
   }
  }
  document.documentElement.lang=locale==='zh-TW'?'zh-Hant':locale;
  document.title=t('知序 · LLM 理解與實作評量');
  for(const panel of root.querySelectorAll('.login'))panel.setAttribute('data-window-title',t('知序 · LLM Assessment Studio — 登入'));
  const selector=document.getElementById('interface-language');if(selector)selector.value=locale;
  observer?.observe(document.body,{childList:true,subtree:true,characterData:true});
 }
 function set(next){if(!locales[next])throw Error('Unsupported interface language');locale=next;try{localStorage.setItem('zhixu.ui.locale',next);}catch{}apply();if(typeof clockTick==='function')clockTick();if(typeof retroAudio!=='undefined')retroAudio.render();}
 async function savePreference(){
  if(typeof state==='undefined'||!state.session?.user)return;
  const chosen=locale,userId=state.session.user.id;
  preferenceQueue=preferenceQueue.catch(()=>{}).then(async()=>{
   if(state.session?.user?.id!==userId)return;
   await api('/api/preferences',{locale:chosen});
   if(state.session?.user?.id===userId)state.session.user.ui_locale=chosen;
  });
  await preferenceQueue;
 }
 async function syncUser(user){
  if(!user)return;
  let pending;try{pending=localStorage.getItem('zhixu.ui.locale.pending');}catch{}
  const chosen=locales[pending]?pending:user.ui_locale;
  if(locales[chosen])set(chosen);
  if(pending||!user.ui_locale){try{await savePreference();localStorage.removeItem('zhixu.ui.locale.pending');}catch{}}
 }
 function init(){
  const selector=document.getElementById('interface-language');selector.value=locale;
  selector.addEventListener('change',async()=>{
   set(selector.value);
   if(typeof state!=='undefined'&&state.session?.user){try{await savePreference();}catch{toast(t('語言已套用；帳號偏好尚未保存，請稍後重試。'));}}
   else try{localStorage.setItem('zhixu.ui.locale.pending',locale);}catch{}
  });
  observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;apply();});}});apply();
 }
 document.addEventListener('DOMContentLoaded',init,{once:true});
 return {get locale(){return locale;},locales,t,text,date,set,syncUser,apply};
})();
