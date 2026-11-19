import {DOMAIN} from '../constants/domain.js';
import {store,load} from '../stores/research.js';
import {gates} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {table} from '../components/common/table.js';
import {bindForm} from '../hooks/forms.js';
import {esc,fmt} from '../utils/format.js';
const GATE_STATES={locked:'已锁定待计算',completed:'已完成',failed:'失败需修复'};
const gateStatus=x=>`<span class="status ${x}">${GATE_STATES[x]||x}</span>`;
export async function render(){
 const writable=localStorage.getItem('research-role')!=='viewer';
 if(!store.studyId)return `<div class="eyebrow">06 / HELD-OUT GATE</div><h1>试印判定：先探索，再留验一次</h1><p class="method-note">还没有${DOMAIN.study_label}。先到来源录入页创建批次并录入观测。</p>`;
 const gate=await gates.get(store.studyId);
 const held=await gates.holdout(store.studyId);
 let suggestion=null;
 if(!gate)suggestion=await gates.suggestion(store.studyId);
 return `<div class="eyebrow">06 / HELD-OUT GATE</div><h1>试印判定：先探索，再留验一次</h1><p>探索分析照常使用已登记观测；用它的结果选一个门槛，再以登记后隔离的留验纸样做一次判定。留验读数不进入查询、普通分析和导出。</p>
 <div class="toolbar">${studySelect()}</div>
 <h2>① 探索与门槛</h2>
 <div class="method-note"><p>${suggestion?`探索样本 ${suggestion.exploration_size} 张（只显示统计量，不透露留验读数）。平均改善 ${fmt(suggestion.mean_improvement)} ΔE，中位 ${fmt(suggestion.median_improvement)} ΔE。建议门槛取中位改善 ${fmt(suggestion.suggested_threshold)} ΔE，请按业务判断修订。`:'探索样本的统计量可用于选择门槛；到此页查看建议。'}</p></div>
 <h2>② 留验纸样 <small>已登记 ${held.registered_count} 张 · ${held.locked?'锁定后不可补录':'登记后隔离'}</small></h2>
 ${writable&&!held.locked?`<form id="holdout-form" class="inline-form"><label>源记录编号<input name="source_key" placeholder="如 HOLD-001" required></label>${DOMAIN.fields.map(([key,label,kind])=>`<label>${esc(label)}<input name="${key}" type="${kind}" ${kind==='number'?'step="any" min="0"':''} required></label>`).join('')}<button type="submit">登记留验纸样</button></form>`:''}
 ${table(['留验编号','登记时间'],held.samples.map(r=>[r.source_key,r.created_at]))}
 <h2>③ 锁定门槛并判定</h2>
 ${gate?`${gate.sample_size?`<p>判定门槛 <strong>${fmt(gate.threshold)} ΔE</strong> · 样本数 <strong>${gate.sample_size}</strong> · ${gateStatus(gate.status)}</p>`:''}${gate.result?`<section class="result-intro"><strong>${esc(gate.result.conclusion)}</strong><p>方法：${esc(gate.result.test)}；零假设：${esc(gate.result.null_hypothesis)}。结果页展示门槛 ${fmt(gate.result.threshold)}、样本数 ${gate.result.sample_size}、p 值 ${fmt(gate.result.p_value)}。</p><p>${esc(gate.result.caveat)}</p></section>`:gate.status==='failed'?`<div class="error">判定失败：${esc(gate.error)}</div>`:'<p class="method-note">门槛已锁定，正在完成判定。刷新本页可继续同一次判定。</p>'}`:writable?`<form id="gate-form" class="worksheet"><label>判定门槛（原工艺减新工艺，ΔE）<input name="threshold" type="number" step="any" required value="${suggestion?.suggested_threshold??''}"></label><p>锁定后冻结当前全部留验纸样；并发锁定只认第一个门槛，之后补录不入样。每项研究只判定一次。</p><button type="submit">锁定门槛并判定 →</button></form>`:'<p class="method-note">等待分析师或负责人登记留验并锁定门槛。</p>'}
 <h2>历史判定</h2>
 ${table(['研究编号','门槛','样本数','p 值','状态'],(await gates.list()).map(g=>[g.study_id,fmt(g.threshold),g.sample_size,g.result?fmt(g.result.p_value):'—',gateStatus(g.status)]))}`;
}
export function bind(refresh){
 bindForm('holdout-form',async data=>{const source_key=data.source_key;delete data.source_key;const values=Object.fromEntries(DOMAIN.fields.map(([key,label,kind])=>[key,kind==='number'?+data[key]:data[key]]));await gates.register(store.studyId,{source_key,values});await load();refresh();});
 bindForm('gate-form',async data=>{await gates.lock(store.studyId,+data.threshold);await load();refresh();});
 const sel=document.getElementById('study-select');if(sel)sel.onchange=()=>{store.studyId=+sel.value;refresh();};
}
