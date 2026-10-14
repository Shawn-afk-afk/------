'use strict';
const retroAudio=(()=>{
 const files={click:'start-pcm.wav',dialog:'ding.wav',notice:'notify.wav',error:'chord.wav',success:'tada.wav',startup:'The Microsoft Sound.wav'};
 let enabled=true,volume=35,lastClick=0,priorityUntil=0,queue=Promise.resolve(),context=null,gain=null;
 function applyVolume(){const audio=player();if(gain){gain.gain.value=volume/100;audio.volume=1;}else if(audio)audio.volume=volume/100;}
 try{enabled=localStorage.getItem('zhixu.sound.enabled')!=='false';const saved=localStorage.getItem('zhixu.sound.volume');if(saved!==null&&Number.isFinite(Number(saved)))volume=Math.max(0,Math.min(100,Number(saved)));}catch{}
 const player=()=>document.getElementById('retro-system-player');
 function render(){const button=document.getElementById('system-sound-toggle');if(!button)return;button.innerHTML=`<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" shape-rendering="crispEdges"><path d="M1 6h4l4-4v12l-4-4H1z" fill="#ffff00" stroke="#000"/>${enabled&&volume>0?'<path d="M11 5h1v6h-1M13 3h1v2h1v6h-1v2h-1" fill="none" stroke="#000"/>':'<path d="m11 5 4 6m0-6-4 6" stroke="#800000" stroke-width="2"/>'}</svg>`;button.setAttribute('aria-pressed',String(enabled));button.setAttribute('aria-label',i18n.t(enabled?'靜音系統音效':'開啟系統音效'));button.title=i18n.t(enabled?'靜音系統音效':'開啟系統音效');const control=document.getElementById('sound-enabled');if(control)control.checked=enabled;const slider=document.getElementById('sound-volume');if(slider)slider.value=volume;const level=document.getElementById('sound-level');if(level)level.textContent=volume+'%';}
 function play(kind='click',preview=false){
  const audio=player(),now=performance.now();if(!audio||!files[kind]||(!enabled&&!preview)||volume===0)return;
  if(kind==='click'&&!preview&&(now-lastClick<100||now<priorityUntil))return;
  if(kind==='click')lastClick=now;else priorityUntil=now+400;
  try{const AudioEngine=window.AudioContext||window.webkitAudioContext;if(AudioEngine&&!context){context=new AudioEngine();gain=context.createGain();context.createMediaElementSource(audio).connect(gain);gain.connect(context.destination);}if(context?.state==='suspended')context.resume().catch(()=>{});}catch{}
  audio.pause();audio.src='/vendor/win98-sounds/'+encodeURIComponent(files[kind]);applyVolume();
  audio.dataset.sound=kind;audio.dataset.state='starting';
  const result=audio.play();if(result)result.then(()=>audio.dataset.state='playing').catch(()=>{audio.dataset.state='blocked';const hint=document.getElementById('sound-browser-hint');if(hint)hint.textContent=i18n.t('瀏覽器尚未允許播放，請再按一次試聽。');});
 }
 function persist(){
  try{localStorage.setItem('zhixu.sound.enabled',String(enabled));localStorage.setItem('zhixu.sound.volume',String(volume));}catch{}
  if(typeof state==='undefined'||!state.session?.user){try{localStorage.setItem('zhixu.sound.pending','1');}catch{}return;}
  const userId=state.session.user.id,chosen={enabled,volume};
  queue=queue.catch(()=>{}).then(async()=>{if(state.session?.user?.id!==userId)return;await api('/api/sound-preferences',chosen);if(state.session?.user?.id===userId){state.session.user.ui_sounds=Number(chosen.enabled);state.session.user.ui_volume=chosen.volume;}}).catch(()=>{toast('音效已套用；帳號偏好尚未保存，請稍後重試。','silent');});
 }
 function configure(nextEnabled,nextVolume){enabled=nextEnabled;volume=nextVolume;if(!enabled||volume===0)player()?.pause();render();persist();}
 async function syncUser(user){if(!user)return;let pending;try{pending=localStorage.getItem('zhixu.sound.pending');}catch{}if(!pending){enabled=user.ui_sounds===null?true:Boolean(user.ui_sounds);volume=user.ui_volume===null?35:user.ui_volume;render();}if(pending||user.ui_sounds===null){persist();await queue;try{localStorage.removeItem('zhixu.sound.pending');}catch{}}}
 function settings(){
  openModal('Windows 98 系統音效',`<div class="sound-panel"><p>按鈕、視窗提示與操作結果使用 Windows 98 原始 WAV 音效。</p><label class="sound-check"><input id="sound-enabled" type="checkbox" ${enabled?'checked':''}>啟用系統音效</label><label for="sound-volume">音量</label><div class="sound-volume"><input id="sound-volume" type="range" min="0" max="100" step="1" value="${volume}"><output id="sound-level">${volume}%</output></div><fieldset><legend>音效試聽</legend><div class="sound-samples">${Object.entries({click:'按鈕',dialog:'視窗提示',notice:'通知',error:'錯誤',success:'完成',startup:'開機音效'}).map(([kind,title])=>`<button data-sound-preview="${kind}">${title}<small data-no-i18n>${files[kind]}</small></button>`).join('')}</div></fieldset><p class="tiny muted">試聽可在靜音時播放；一般操作仍保持靜音。音量為 0 時不播放。</p><p id="sound-browser-hint" class="tiny" role="status"></p></div>`);
  document.getElementById('sound-enabled').onchange=e=>configure(e.target.checked,volume);
  document.getElementById('sound-volume').oninput=e=>{volume=Number(e.target.value);applyVolume();render();if(volume===0)player().pause();};
  document.getElementById('sound-volume').onchange=()=>persist();
  document.querySelectorAll('[data-sound-preview]').forEach(button=>button.onclick=()=>play(button.dataset.soundPreview,true));
 }
 document.addEventListener('DOMContentLoaded',()=>{
  player().addEventListener('ended',()=>player().dataset.state='ended');
  document.getElementById('system-sound-toggle').onclick=()=>{configure(!enabled,volume);if(enabled)play('click');};
  document.getElementById('system-sound-settings').onclick=settings;
  // Capture before handlers disable or replace clicked buttons; a dialog/result takes priority.
  document.addEventListener('click',event=>{const button=event.target.closest('button,a[href]');if(!button||button.disabled||button.closest('[data-sound-preview],#system-sound-toggle,#system-sound-settings'))return;queueMicrotask(()=>play('click'));},true);
  document.addEventListener('change',event=>{if(event.target.matches('select,input[type=radio],input[type=checkbox]')&&!event.target.closest('.sound-panel'))play('click');});
  render();
 },{once:true});
 return {play,render,syncUser};
})();
