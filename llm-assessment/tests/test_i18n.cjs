const path=require('node:path');const projectDir=path.resolve(__dirname,'..');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const textNodes=[['工作區總覽',false],['登入你的工作區',false],['管理者',true],['第 1 / 3 題 · 12 分',false],['MY REPORTS',false]].map(([source,protectedContent])=>({nodeValue:source,parentElement:{closest:()=>protectedContent?{}:null}}));
const input={value:'正在寫的中文答案',hasAttribute:name=>name==='placeholder',getAttribute:()=>input.placeholder,setAttribute:(name,value)=>input.placeholder=value,placeholder:'請具體說明，並連結案例證據。',closest:()=>null};
const selector={value:'zh-TW'};const events={};
const context={window:{},localStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},Intl,Date,Map,WeakMap,RegExp,Error,NodeFilter:{SHOW_TEXT:4},queueMicrotask,MutationObserver:class{observe(){}disconnect(){}},document:{body:{querySelectorAll:selector=>selector.startsWith('[placeholder]')?[input]:[]},documentElement:{lang:'zh-Hant'},getElementById:()=>selector,addEventListener:(name,cb)=>events[name]=cb,createTreeWalker:()=>{let i=0;return{nextNode:()=>textNodes[i++]||null};}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(projectDir,'static/translations.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(projectDir,'static/i18n.js'),'utf8')+';window.testLocale=i18n;',context);
const rows=context.window.INTERFACE_TRANSLATIONS;assert(rows.length>450);assert(rows.every(r=>r.length===4&&r.every(v=>v.trim())));assert.equal(new Set(rows.map(r=>r[0])).size,rows.length);
const api=context.window.testLocale;
for(const [locale,overview,login] of [['en','Overview','Sign in to your workspace'],['ja','概要','ワークスペースにログイン'],['es','Resumen','Accede a tu espacio'],['zh-TW','工作區總覽','登入你的工作區']]){
 api.set(locale);assert.equal(textNodes[0].nodeValue,overview);assert.equal(textNodes[1].nodeValue,login);assert.equal(textNodes[2].nodeValue,'管理者');assert.equal(input.value,'正在寫的中文答案');assert.equal(selector.value,locale);
 if(locale==='en')assert.equal(textNodes[3].nodeValue,'Question 1 / 3 · 12 points');
}
api.set('en');assert.equal(api.text('日期 [C++]'),'日期 [C++]');assert.throws(()=>api.set('fr'));assert.equal(api.locale,'en');
console.log('Locale catalog and reversible interface checks passed:',rows.length,'entries, four locales; content and input values preserved.');
