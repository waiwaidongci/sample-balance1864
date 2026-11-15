<script setup lang="ts">
import{onMounted,ref,watch,computed}from 'vue';
import{samples,loadBatches}from '../stores/samples';
import{getVersions,getPackages,getPackage,importCorrection,resolvePackage,downloadVersion}from '../api/corrections';
import{canEdit}from '../stores/auth';
import{useTask}from '../hooks/useTask';
import{dateTime}from '../utils/format';
import{packageStatusLabels,fieldLabels}from '../constants/enums';
import type{RegisterVersion,CorrectionPackage,CorrectionDetail}from '../types/domain';
import PageHeading from '../components/common/PageHeading.vue';
import BatchSelect from '../components/BatchSelect.vue';
import ErrorNotice from '../components/common/ErrorNotice.vue';
import EmptyState from '../components/common/EmptyState.vue';

const selected=ref(1),showImport=ref(false),message=ref('');
const versions=ref<RegisterVersion[]>([]),packages=ref<CorrectionPackage[]>([]),detail=ref<CorrectionDetail|null>(null);
const form=ref({code:'',depends_on:'',base_version:'',csv_text:`code,zone,age_band,mode,trip_minutes,base_weight
YY0-0001,中心,青年,小汽车,25,1`});
const choices=ref<Record<number,{choice:string;value:string}>>({});
const{error,busy,execute}=useTask();

const latest=computed(()=>versions.value[0]?.version||0);
const openConflicts=computed(()=>(detail.value?.conflicts||[]).filter(c=>c.status==='open'));

const refresh=()=>execute(async()=>{
 await loadBatches();
 if(!samples.batches.length){versions.value=[];packages.value=[];return}
 if(!samples.batches.find(b=>b.id===selected.value))selected.value=samples.batches[0].id;
 const[v,p]=await Promise.all([getVersions(selected.value),getPackages(selected.value)]);
 versions.value=v;packages.value=p;
 if(detail.value)detail.value=await getPackage(selected.value,detail.value.id);
});
watch(selected,()=>{detail.value=null;refresh()});

const importing=()=>execute(async()=>{
 const body:{code:string;depends_on?:string;base_version?:number;csv_text:string}={code:form.value.code,csv_text:form.value.csv_text};
 if(form.value.depends_on.trim())body.depends_on=form.value.depends_on.trim();
 if(form.value.base_version.trim())body.base_version=Number(form.value.base_version);
 const r=await importCorrection(selected.value,body);
 message.value=r.status==='applied'?`更正包 ${r.code} 已合并为底册 v${r.applied_version}。`:`更正包 ${r.code} ${packageStatusLabels[r.status]}：${r.reason}`;
 showImport.value=false;await refresh();
});

const openDetail=(p:CorrectionPackage)=>execute(async()=>{
 detail.value=await getPackage(selected.value,p.id);
 choices.value=Object.fromEntries(openConflicts.value.map(c=>[c.id,{choice:'incoming',value:''}]));
});

const resolving=()=>execute(async()=>{
 if(!detail.value)return;
 const resolutions=openConflicts.value.map(c=>{
  const pick=choices.value[c.id]||{choice:'incoming',value:''};
  return pick.choice==='value'?{conflict_id:c.id,choice:pick.choice,value:pick.value}:{conflict_id:c.id,choice:pick.choice};
 });
 const r=await resolvePackage(selected.value,detail.value.id,resolutions);
 message.value=r.status==='applied'?`更正包 ${r.code} 已合并为底册 v${r.applied_version}。`:`更正包 ${r.code} 仍有待处理事项：${r.reason}`;
 detail.value=null;await refresh();
});

const download=(v:number)=>execute(()=>downloadVersion(selected.value,v));
onMounted(refresh);
</script>

<template>
<PageHeading index="05" title="样本更正包" subtitle="机构离线更正按包合并：字段级三向合并，冲突人工裁决，前序到达前不乱序写入。"/>
<ErrorNotice :message="error" @retry="refresh"/>
<p v-if="message" class="success">{{message}}</p>
<div class="toolbar">
 <BatchSelect v-model="selected" :items="samples.batches"/>
 <div v-if="canEdit"><button @click="showImport=!showImport">＋ 导入更正包</button><button v-if="latest" @click="download(latest)">下载当前底册 v{{latest}} ↓</button></div>
</div>
<form v-if="showImport&&canEdit" class="import-form" @submit.prevent="importing">
 <div class="form-grid">
  <label>包代码<input v-model="form.code" required pattern="[A-Za-z0-9_\-]+" minlength="2" maxlength="60" placeholder="如 YY-FIX-004"/></label>
  <label>前序包代码（可选）<input v-model="form.depends_on" pattern="[A-Za-z0-9_\-]+" maxlength="60" placeholder="留空表示无依赖"/></label>
 </div>
 <label>基线版本（可选，默认当前最新 v{{latest||'—'}}）<input v-model="form.base_version" type="number" min="1" :max="latest||undefined" placeholder="留空=最新底册"/></label>
 <label>更正行 CSV<textarea v-model="form.csv_text" rows="6" required/></label>
 <p>列为完整样本行：code, zone, age_band, mode, trip_minutes, base_weight。系统按基线版本逐字段比对，只合并发生变化的字段；同编号重复投递不会重复写入。</p>
 <button class="primary" :disabled="busy">校验并合并</button>
</form>

<div class="section-heading"><h2>更正包</h2><span>{{packages.length}}个 · 冲突只阻塞各自后继，独立包照常合并</span></div>
<EmptyState v-if="!packages.length" title="还没有更正包" hint="下载底册版本离线更正后，在上方导入更正包；同一样本同一字段被改成不同值时会列出冲突。"/>
<div class="table-wrap" v-else><table>
 <thead><tr><th>包代码</th><th>状态</th><th>前序</th><th>基线 → 底册版本</th><th>待处理原因 / 说明</th><th>投递时间</th><th></th></tr></thead>
 <tbody><tr v-for="p in packages" :key="p.id">
  <td class="mono">{{p.code}}</td>
  <td><span class="badge" :class="p.status">{{packageStatusLabels[p.status]||p.status}}</span></td>
  <td class="mono">{{p.depends_on||'—'}}</td>
  <td class="mono">v{{p.base_version}} → {{p.applied_version?'v'+p.applied_version:'—'}}</td>
  <td>{{p.reason||'—'}}</td>
  <td>{{dateTime(p.created_at)}}</td>
  <td><a v-if="p.status==='conflict'&&canEdit" href="javascript:;" @click="openDetail(p)">解决冲突</a><a v-else-if="p.conflict_count||p.status==='applied'" href="javascript:;" @click="openDetail(p)">查看</a></td>
 </tr></tbody>
</table></div>

<section v-if="detail" class="import-form">
 <h2>更正包 {{detail.code}} · {{packageStatusLabels[detail.status]}}</h2>
 <p v-if="detail.reason">待处理原因：{{detail.reason}}</p>
 <EmptyState v-if="!detail.conflicts.length" title="没有字段冲突" hint="该包没有需要裁决的字段。"/>
 <template v-else>
 <div class="table-wrap"><table>
  <thead><tr><th>样本</th><th>字段</th><th>基线值</th><th>当前底册</th><th>本包传入</th><th>裁决</th></tr></thead>
  <tbody><tr v-for="c in detail.conflicts" :key="c.id">
   <td class="mono">{{c.sample_code}}</td><td>{{fieldLabels[c.field]||c.field}}</td>
   <td>{{c.base_value}}</td><td><strong>{{c.current_value}}</strong></td><td><strong>{{c.incoming_value}}</strong></td>
   <td v-if="c.status==='open'&&canEdit">
    <label class="choice"><input type="radio" :name="'c'+c.id" value="incoming" v-model="choices[c.id].choice"/> 采用传入值</label>
    <label class="choice"><input type="radio" :name="'c'+c.id" value="current" v-model="choices[c.id].choice"/> 保留当前值</label>
    <label class="choice"><input type="radio" :name="'c'+c.id" value="value" v-model="choices[c.id].choice"/> 自定义</label>
    <input v-if="choices[c.id].choice==='value'" v-model="choices[c.id].value" placeholder="输入裁决值" style="margin-top:8px"/>
   </td>
   <td v-else>已裁决为 <strong>{{c.resolution}}</strong><small>{{c.resolved_by}}</small></td>
  </tr></tbody>
 </table></div>
 <div v-if="openConflicts.length&&canEdit" class="form-actions">
  <button class="primary" :disabled="busy" @click="resolving">提交全部 {{openConflicts.length}} 项裁决并合并</button>
  <small>裁决后整包原子合并；期间若有新冲突会再次列出。</small>
 </div>
 </template>
</section>

<div class="section-heading"><h2>底册版本</h2><span>每次变更留一份完整快照，可按版本下载</span></div>
<EmptyState v-if="!versions.length" title="还没有底册版本" hint="导入样本或合并更正包后自动生成版本快照。"/>
<div class="table-wrap" v-else><table>
 <thead><tr><th>版本</th><th>来源</th><th>样本数</th><th>登记时间</th><th></th></tr></thead>
 <tbody><tr v-for="v in versions" :key="v.id">
  <td class="mono">v{{v.version}}</td><td>{{v.source}}<small v-if="v.package_code" class="mono">{{v.package_code}}</small></td>
  <td>{{v.sample_count}}</td><td>{{dateTime(v.created_at)}}</td>
  <td><a href="javascript:;" @click="download(v.version)">下载 CSV ↓</a></td>
 </tr></tbody>
</table></div>
</template>
