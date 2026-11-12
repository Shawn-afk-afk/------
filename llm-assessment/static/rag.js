'use strict';
function studioRagBadge(material){
 const status=material.status||material.rag_status||'queued';
 const names={queued:'RAG 排隊中',running:'RAG 建置中',ready:'RAG 可檢索',failed:'RAG 建置失敗'};
 return `<span class="badge ${status==='ready'?'good':status==='failed'?'bad':'warn'}">${names[status]||status}</span><small>${material.completed??material.rag_completed??0} / ${material.chunk_count||0} 段</small>${material.error||material.rag_error?`<p class="note bad" data-no-i18n>${esc(material.error||material.rag_error)}</p>`:''}`;
}
function studioInitRag(){
 const owner=state.studio,current=()=>state.page==='examstudio'&&state.studio===owner&&$('#rag-preview');
 const refresh=async()=>{const result=await api('/api/admin/exam/rag-status');if(!current())return;for(const document of result.documents){const box=$$('[data-rag-status]').find(e=>e.dataset.ragStatus===document.material_id);if(box)box.innerHTML=studioRagBadge(document);}return result;};
 $$('[data-rag-rebuild]').forEach(button=>button.onclick=busy(button,async()=>{await api('/api/admin/exam/rag-rebuild',{id:button.dataset.ragRebuild});await refresh();toast('教材向量重建已排隊');}));
 $('#rag-search').onclick=busy($('#rag-search'),async()=>{const result=await api('/api/admin/exam/rag-search',{query:$('#rag-query').value,unit_ids:$$('[data-rag-unit]:checked').map(e=>e.dataset.ragUnit)});$('#rag-preview').innerHTML=result.results.map(item=>`<article class="rag-hit"><div><strong data-no-i18n>${esc(item.source_ref)}</strong><span>相似度 ${item.score.toFixed(3)}</span></div><small data-no-i18n>${esc(item.locator)}</small><pre>${esc(item.text)}</pre></article>`).join('');});
 async function poll(){if(!current())return;try{await refresh();}catch(e){if(e.name!=='AbortError'&&current())$('#rag-status-hint').textContent=e.message;}if(current())owner.ragPoll=setTimeout(poll,2500);}
 owner.ragPoll=setTimeout(poll,800);
}
