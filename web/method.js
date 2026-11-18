import { act, api, dialog, empty, esc, filteredTable, heading, navigate, number, pill, select, state,
  statusNames, table, toast } from "./app.js"

const blocks=["Фискальный блок","Администрирование","Контрольный блок","Сервисный блок","Управленческий блок"]
const cadences=[["month","Месяц"],["quarter","Квартал"],["year","Год"],["control","Контрольная дата"],["multi","Месяц, квартал и год"]]
const operations=[["ge","≥ Не менее"],["gt","> Больше"],["le","≤ Не более"],["lt","< Меньше"],["eq","= Равно"],["range","В диапазоне"]]
const presets=[
  ["A","Фактическое значение",["Фактическое значение"]],
  ["A/B*100","Факт ÷ план × 100",["Факт","План"]],
  ["A/B*100","Отношение × 100",["Числитель","Знаменатель"]],
  ["A/B*100","Темп роста",["Текущий период","Базовый период"]],
  ["(A+B)/2","Среднее арифметическое",["Первое значение","Второе значение"]],
  ["A+B","Сумма",["Первое значение","Второе значение"]],
  ["A-B","Разность",["Первое значение","Второе значение"]],
  ["A","Выполнение условия",["Значение для сравнения"],"eq"],
  ["A","Диапазон значений",["Значение для сравнения"],"range"],
  ["","Составная формула",[]],
]
const formValues=form=>Object.fromEntries(new FormData(form))
const input=(label,key,value="",type="text",options="")=>`<label class="field"><span>${esc(label)}</span>
  <input type="${type}" name="${key}" value="${esc(value)}" ${options}></label>`
const area=(label,key,value="")=>`<label class="field full"><span>${esc(label)}</span><textarea name="${key}">${esc(value)}</textarea></label>`
const fmt=value=>new Date(value).toLocaleString("ru-RU")
const grade=(key,label)=>`<label class="field"><span>${esc(label)}</span>${key}</label>`
const compareFields={indicator:"Индикатор",indicator_name:"Название индикатора",metric:"Показатель",metric_name:"Название показателя",
  block:"Блок",metric_weight:"Вес показателя",weight:"Вес субкомпонента",name:"Субкомпонент",department:"Подразделение",
  source:"Источник",instruction:"Методика",cadence:"Периодичность",control_dates:"Контрольные даты",cumulative:"Нарастающий итог",applicability:"Применимость",inactive:"Исключён",
  rule:"Правило",blockers:"Расхождения",resolution:"Решение"}

export async function renderMethods(container) {
  const versions=await api("/methods")
  const editable=state.user.role==="method"
  container.innerHTML=heading("Конструктор методики","Версии, правила расчёта и утверждение изменений",
    editable?'<button class="btn primary" data-new>＋ Создать версию</button>':"")+
   `<section class="panel"><div class="panel-inner panel-title"><div><h2>Версии методики</h2><p>Публикации привязаны к отчётным периодам</p></div></div>
   ${table(["Версия","Контур","Действует с","Статус","Основание","Утвердил","Действие"],versions.map(v=>`<tr><td class="row-name">${esc(v.name)}</td>
    <td>${esc(v.track==="demo"?"Демонстрационный":"Исходные документы")}</td><td>${esc(v.effective)}</td><td>${pill(v.status,v.id==="source-v1"?"Справочник проекта":null)}</td>
    <td>${esc(v.reason)}</td><td>${esc(v.approver||"—")}</td><td><button data-ver="${v.id}" class="btn small">Открыть</button></td></tr>`))}</section>`
  container.querySelectorAll("[data-ver]").forEach(b=>b.onclick=()=>navigate("version",b.dataset.ver))
  container.querySelector("[data-new]")?.addEventListener("click",()=>{
    dialog("Новая версия методики",`<form class="form">${grade(select(versions.filter(v=>v.status==="published").map(v=>[v.id,v.name]),"demo-v1","parent"),"Исходная версия")}
    ${input("Название версии","name","","text","required maxlength=200")}${input("Начало действия","effective","2026-11","month","required")}
    ${area("Основание изменений","reason")}<button class="btn primary">Создать черновик</button></form>`,node=>{
      node.querySelector("form").onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const v=await api("/methods",{method:"POST",json:formValues(e.target)})
          node.close();navigate("version",v.id)
        },e.submitter)
      }
    })
  })
}

function rowEditor(item,editable) {
  const app=item.applicability
  const rule=item.rule
  return `<form class="form" id="entry-form"><fieldset ${editable?"":"disabled"}>
   <div class="fields">
    ${input("Код субкомпонента","code",item.code,"text",item.code?"readonly":"required")}
    ${input("Название субкомпонента","name",item.name,"text","required")}
    ${input("Код индикатора","indicator",item.indicator,"text","required")}
    ${input("Название индикатора","indicator_name",item.indicator_name,"text","required")}
    ${input("Код показателя","metric",item.metric,"text","required")}
    ${input("Название показателя","metric_name",item.metric_name,"text","required")}
    ${input("Вес показателя, %","metric_weight",item.metric_weight,"number",'min="0.001" max="100" step="any" required')}
    ${input("Вес субкомпонента, %","weight",item.weight,"number",'min="0.001" max="100" step="any" required')}
    ${grade(select(blocks.map(x=>[x,x]),item.block,"block"),"Функциональный блок")}
    ${grade(select(cadences,item.cadence,"cadence"),"Периодичность")}
    <div data-control-dates ${item.cadence==="control"?"":"hidden"}>${input("Контрольные даты ММ-ДД через запятую","control_dates",
      item.control_dates?.join(", ")||(item.cadence==="control"?"09-15, 12-31":""))}</div>
    ${input("Подразделение КГД","department",item.department,"text","required")}
    ${input("Источник данных","source",item.source,"text","required")}
    ${grade(select([["dgd","ДГД"],["ctl","ЦТЛ"]],app.kind,"subject"),"Применимость")}
    ${input("Коды регионов через запятую","regions",app.regions?.join(", "))}
    <label><input type="checkbox" name="cumulative" ${item.cumulative?"checked":""}> Нарастающим итогом</label>
    <label><input type="checkbox" name="inactive" ${item.inactive?"checked":""}> Исключить из расчёта</label>
    ${area("Текст правила и исключений","instruction",item.instruction)}
   </div>
   <div class="details"><h3>Расчёт фактического значения</h3>
    ${grade(select([["","Выберите шаблон"],...presets.map((p,i)=>[String(i),p[1]])],"","preset"),"Тип формулы")}
    <div class="spaced">${input("Формула","expression",rule?.expression||"A","text","required maxlength=220")}</div>
    <div data-fields class="stack spaced"></div><button type="button" class="btn small spaced" data-add-field>＋ Поле</button>
   </div>
   <div class="details"><h3>Начисление баллов</h3><small>Первое выполненное условие определяет балл.</small>
    <div data-bands class="stack spaced"></div><button type="button" class="btn small spaced" data-add-band>＋ Порог</button>
    <div class="spaced">${input("Баллы при невыполнении условий","fallback",rule?.default??"","number",'step="any" min="0"')}</div>
    <details class="spaced"><summary>Контекстные шкалы${rule?.variants?.length?" · "+rule.variants.length:""}</summary>
      <p class="muted spaced">Условия определяют, когда применять шкалу вместо основной. Пересечения проверяются при сохранении.</p>
      <div data-variants class="stack"></div><button type="button" class="btn small spaced" data-add-variant>＋ Вариант шкалы</button>
    </details>
   </div>
   ${item.blockers?.length?`<div class="details"><p class="note">Требуется уточнение методики · ${esc(item.blockers.join(", "))}</p>
    ${editable?area("Основание решения по расхождению","resolution"):""}</div>`:""}
   </fieldset>
   <div class="actions">${editable?'<button class="btn primary">Сохранить правило</button>':""}<button type="button" class="btn" data-preview>Проверить расчёт</button></div>
   </form>`
}

function mountRows(form,item){
  const fields=form.querySelector("[data-fields]")
  const bands=form.querySelector("[data-bands]")
  function fieldRow(f={key:"",label:"",min:0}){
    const element=document.createElement("div")
    element.className="editor-row"
    element.dataset.fieldRow=""
    element.innerHTML=`${input("Код","fkey",f.key,"text",'required maxlength=16')}${input("Название поля","flabel",f.label,"text","required")}
      ${input("Минимум","fmin",f.min??"","number",'step="any"')}<button type="button" class="btn icon align-end" aria-label="Удалить поле">×</button>`
    element.querySelector("button").onclick=()=>element.remove()
    fields.append(element)
  }
  function bandRow(b={op:"ge",target:0,points:0},target=bands){
    const element=document.createElement("div")
    element.className="editor-row band-row"
    element.dataset.bandRow=""
    element.innerHTML=`${grade(select(operations,b.op,"bop"),"Условие")}${input("Порог / нижняя граница","btarget",b.target,"number",'required step="any"')}
     ${input("Верхняя граница","bupper",b.upper??"","number",'step="any"')}
     ${input("Баллы","bpoints",b.points,"number",'required step="any" min="0"')}
     <button type="button" class="btn icon align-end" aria-label="Удалить порог">×</button>`
    const condition=element.querySelector("[name=bop]")
    const toggle=()=>{ element.querySelector("[name=bupper]").closest("label").hidden=condition.value!=="range" }
    condition.onchange=toggle
    toggle()
    element.querySelector("button").onclick=()=>element.remove()
    target.append(element)
  }
  function variantRow(v={}){
    const element=document.createElement("div")
    element.className="report-component"
    element.dataset.variantRow=""
    element.innerHTML=`<div class="fields">
      ${input("Год","vyear",v.year??"","number",'min="2000" max="2199"')}
      ${input("Месяцы от 1 до 12 через запятую","vmonths",v.months?.join(", "))}
      ${grade(select([["","Любой период"],["month","Месяц"],["quarter","Квартал"],["year","Год"]],v.period_type||"","vperiod"),"Вид периода")}
      ${input("Код исходного поля","vfield",v.field??"")}
      ${input("Поле от","vlow",v.low??"","number",'step="any"')}
      ${input("Поле до","vhigh",v.high??"","number",'step="any"')}</div>
      <div data-variant-bands class="stack spaced"></div><div class="actions spaced">
      <button type="button" class="btn small" data-variant-add>＋ Порог</button>
      <button type="button" class="btn small warn" data-variant-delete>Убрать вариант</button></div>`
    const list=element.querySelector("[data-variant-bands]")
    for(const band of v.bands||[{op:"ge",target:100,points:0}]) bandRow(band,list)
    element.querySelector("[data-variant-add]").onclick=()=>bandRow(undefined,list)
    element.querySelector("[data-variant-delete]").onclick=()=>element.remove()
    form.querySelector("[data-variants]").append(element)
  }
  for(const v of item.rule?.variants||[]) variantRow(v)
  form.querySelector("[data-add-variant]").onclick=()=>variantRow()
  for(const f of item.rule?.fields||[{key:"A",label:"Фактическое значение",min:0}]) fieldRow(f)
  for(const b of item.rule?.bands||[{op:"ge",target:100,points:100}]) bandRow(b)
  form.elements.cadence.onchange=()=>form.querySelector("[data-control-dates]").hidden=form.elements.cadence.value!=="control"
  form.querySelector("[data-add-field]").onclick=()=>fieldRow()
  form.querySelector("[data-add-band]").onclick=()=>bandRow()
  form.elements.preset.onchange=()=>{
    const index=form.elements.preset.value
    if(index==="") return
    const [expression,,labels,condition]=presets[Number(index)]
    if(!expression) return
    form.elements.expression.value=expression
    fields.replaceChildren()
    labels.forEach((label,i)=>fieldRow({key:"AB"[i],label,min:0}))
    if(condition) {
      bands.replaceChildren()
      bandRow({op:condition,target:condition==="eq"?1:0,upper:100,points:Number(form.elements.weight.value)*Number(form.elements.metric_weight.value)/100})
    }
  }
}

function parseEntry(form,item){
  const values=formValues(form)
  const read=(row,name)=>row.querySelector(`[name=${name}]`).value
  const fields=[...form.querySelectorAll("[data-field-row]")].map(r=>({
    key:read(r,"fkey").trim(),label:read(r,"flabel").trim(),min:read(r,"fmin")===""?null:Number(read(r,"fmin"))}))
  const parseBands=target=>[...target.querySelectorAll("[data-band-row]")].map(r=>{
    const op=read(r,"bop")
    const b={op,target:Number(read(r,"btarget")),points:Number(read(r,"bpoints"))}
    if(op==="range") b.upper=read(r,"bupper")===""?null:Number(read(r,"bupper"))
    return b
  })
  const rule={expression:values.expression,fields,bands:parseBands(form.querySelector("[data-bands]")),
              default:values.fallback===""?null:Number(values.fallback)}
  const variants=[...form.querySelectorAll("[data-variant-row]")].map(row=>{
    const condition={bands:parseBands(row)}
    if(read(row,"vyear")) condition.year=Number(read(row,"vyear"))
    if(read(row,"vmonths").trim()) condition.months=read(row,"vmonths").split(",").map(x=>Number(x.trim()))
    if(read(row,"vperiod")) condition.period_type=read(row,"vperiod")
    if(read(row,"vfield").trim()){
      condition.field=read(row,"vfield").trim()
      condition.low=read(row,"vlow")===""?null:Number(read(row,"vlow"))
      condition.high=read(row,"vhigh")===""?null:Number(read(row,"vhigh"))
    }
    return condition
  })
  if(variants.length) rule.variants=variants
  return {...item,...Object.fromEntries(["code","name","indicator","indicator_name","metric","metric_name","block",
    "department","source","cadence","instruction"].map(k=>[k,values[k].trim()])),
    weight:Number(values.weight),metric_weight:Number(values.metric_weight),rule,
    cumulative:Boolean(values.cumulative),inactive:Boolean(values.inactive),
    control_dates:values.cadence==="control"?(values.control_dates||"").split(",").map(s=>s.trim()).filter(Boolean):[],
    applicability:{kind:values.subject,regions:(values.regions||"").split(",").map(s=>s.trim()).filter(Boolean)}}
}

function preview(version,item){
  const fields=item.rule?.fields||[{key:"A",label:"Фактическое значение"}]
  dialog("Контрольный расчёт",`<form class="form">${input("Отчётный период","period",state.period,"month","required")}
    ${grade(select([["month","Месяц"],["quarter","Квартал"],["year","Год"]],state.kind,"kind"),"Вид периода")}
    ${fields.map(f=>input(f.key+" · "+f.label,"field_"+f.key,"","text","required inputmode=decimal")).join("")}
    <button class="btn primary">Рассчитать</button><output class="readout" hidden></output></form>`,node=>{
      node.querySelector("form").onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const v=formValues(e.target)
          const result=await api("/methods/"+version.id+"/preview",{method:"POST",json:{period:v.period,
            kind:v.kind,code:item.code,entry:item,values:Object.fromEntries(fields.map(f=>[f.key,v["field_"+f.key]]))}})
          const out=node.querySelector("output")
          out.hidden=false
          out.textContent=`${statusNames[result.status]} · факт ${number(result.actual)} · ${number(result.points)} из ${number(result.base)} баллов`
        },e.submitter)
      }
    })
}

export async function renderVersion(container,id) {
  let version=await api("/methods/"+id)
  let selected=version.content.entries[0]?.code
  const writable=state.user.role==="method"&&version.status==="draft"
  const stage=({draft:["submit","Направить на утверждение"],approved:["publish","Опубликовать"]})[version.status]
  const stateActions=state.user.role==="method"&&stage?`<button class="btn primary" data-step="${stage[0]}">${stage[1]}</button>`:
    state.user.role==="approver"&&version.status==="review"?'<button class="btn" data-step="send_back">Вернуть в черновик</button><button class="btn primary" data-step="approve">Утвердить версию</button>':""
  container.innerHTML=heading(version.name,`Действует с ${version.effective} · ${version.reason}`,
    `<div class="actions"><button class="btn" data-back>← К версиям</button>${pill(version.status,version.id==="source-v1"?"Справочник проекта":null)}</div>`)
    + `<div class="tool-row"><div class="actions">
    ${version.parent?'<button class="btn" data-diff>Сравнить с исходной версией</button>':""}<button class="btn" data-history>Журнал изменений</button>
    ${writable?'<button class="btn" data-new>＋ Субкомпонент</button>':""}
    ${writable&&Object.values(version.content.aggregate_blockers||{}).some(x=>x.length)?
      '<button class="btn" data-aggregate>Решение по итоговому расчёту</button>':""}</div><div class="actions">${stateActions}</div></div>
    <div class="rule-grid"><section class="panel panel-inner"><h2>Справочник</h2><input class="search spaced" data-search placeholder="Код или наименование" aria-label="Поиск в справочнике">
    <div class="metric-list" data-list></div></section><section class="panel panel-inner" data-edit></section></div>`
  const holder=container.querySelector("[data-edit]")
  function drawList(){
    const term=container.querySelector("[data-search]").value.trim().toLowerCase()
    container.querySelector("[data-list]").innerHTML=version.content.entries
      .filter(e=>[e.code,e.name,e.metric_name,e.indicator_name].join(" ").toLowerCase().includes(term))
      .map(e=>`<button class="rule-choice ${e.code===selected?"selected":""}" data-item="${esc(e.code)}"><b>${esc(e.code)}</b><span>${esc(e.name)}${e.inactive?" · Исключён":""}</span></button>`).join("")
    container.querySelectorAll("[data-item]").forEach(b=>b.onclick=()=>{
      selected=b.dataset.item
      drawList();drawEditor()
    })
  }
  function drawEditor(){
    const original=version.content.entries.find(e=>e.code===selected)||null
    const item=original||{code:"",indicator:"",metric:"",cadence:"month",weight:100,metric_weight:100,applicability:{kind:"dgd"},block:blocks[0]}
    holder.innerHTML=`<div class="panel-title"><div><h2>${esc(original?.name||"Новый субкомпонент")}</h2>${original?`<p>${esc(original.code)} · ${esc(original.metric)}</p>`:""}</div></div>`
      +rowEditor(item,writable)
    const form=holder.querySelector("form")
    mountRows(form,item)
    form.onsubmit=e=>{
      e.preventDefault()
      act(async()=>{
        const next=parseEntry(form,item)
        const result=await api("/methods/"+id+"/entry",{method:"PUT",json:{entry:next,original,resolution:form.elements.resolution?.value}})
        version=await api("/methods/"+id)
        selected=result.code;toast("Правило сохранено.");drawList();drawEditor()
      },e.submitter)
    }
    holder.querySelector("[data-preview]").onclick=()=>{
      if(writable&&!form.reportValidity()) return
      const candidate=writable?parseEntry(form,item):item
      if(form.elements.resolution?.value.trim()) candidate.blockers=[]
      preview(version,candidate)
    }
  }
  container.querySelector("[data-aggregate]")?.addEventListener("click",()=>{
    const subjects=[["dgd","ДГД"],["ctl","ЦТЛ"],["deputy","Заместитель"]].filter(([key])=>version.content.aggregate_blockers[key]?.length)
    dialog("Решение по итоговому расчёту",`<form class="form">${grade(select(subjects,subjects[0][0],"subject"),"Объект расчёта")}
      <div class="note" data-issue></div><div data-denominator>${input("Знаменатель по пункту 25","denominator","","number",'step="any" min="0"')}</div>
      ${area("Утверждённое решение и реквизиты","reason")}<button class="btn primary">Сохранить в черновике</button></form>`,node=>{
        const form=node.querySelector("form")
        const draw=()=>{
          const key=form.elements.subject.value
          node.querySelector("[data-issue]").textContent=version.content.aggregate_blockers[key].join(", ")
          node.querySelector("[data-denominator]").hidden=key!=="ctl"
        }
        form.elements.subject.onchange=draw
        draw()
        form.onsubmit=e=>{
          e.preventDefault()
          act(async()=>{
            await api("/methods/"+id+"/aggregate",{method:"PUT",json:formValues(form)})
            node.close();toast("Решение внесено в черновик.");navigate("version",id)
          },e.submitter)
        }
    })
  })
  container.querySelector("[data-search]").oninput=drawList
  container.querySelector("[data-back]").onclick=()=>navigate("methods")
  container.querySelector("[data-new]")?.addEventListener("click",()=>{selected=null;drawList();drawEditor()})
  container.querySelectorAll("[data-step]").forEach(b=>b.onclick=()=>act(async()=>{
    await api("/methods/"+id+"/"+b.dataset.step,{method:"POST",json:{}})
    toast("Статус версии обновлён.");navigate("version",id)
  },b))
  container.querySelector("[data-history]").onclick=e=>act(async()=>{
    const events=await api("/methods/"+id+"/history")
    const labels={new_method:"Создана версия",save_rule:"Изменено правило",aggregate_decision:"Решение по итогу",submit:"Направлено",approve:"Утверждено",send_back:"Возвращено",publish:"Опубликовано"}
    dialog("Журнал изменений",events.length?table(["Действие","Сотрудник","Дата"],events.map(x=>
      `<tr><td>${esc(labels[x.action]||x.action)} ${esc(x.detail.code||"")}</td><td>${esc(x.name)}</td><td>${esc(fmt(x.happened))}</td></tr>`)):empty())
  },e.target)
  container.querySelector("[data-diff]")?.addEventListener("click",e=>act(async()=>{
    const changes=await api("/methods/"+id+"/diff")
    const view=value=>typeof value==="object"?JSON.stringify(value):String(value??"—")
    dialog("Отличия от исходной версии",changes.length?changes.map(c=>`<details class="details"><summary>${esc(c.code+" · "+(c.after||c.before).name)}</summary>
    <div class="instruction">${esc(Object.keys(compareFields).filter(key=>view(c.before?.[key])!==view(c.after?.[key]))
    .map(key=>`${compareFields[key]}\nБыло: ${view(c.before?.[key])}\nСтало: ${view(c.after?.[key])}`).join("\n\n"))}</div></details>`).join(""):empty("Изменений пока нет."))
  },e.target))
  drawList();drawEditor()
}


export async function renderDeputies(container) {
  const [deputies,regions]=await Promise.all([api("/deputies"),api("/regions")])
  const names=Object.fromEntries(regions.map(r=>[r.id,r.name]))
  const writable=state.user.role==="method"
  container.innerHTML=heading("Курирование","Должности, направления и периоды работы",
    writable?'<button class="btn primary" data-add>Добавить назначение</button>':"")
    + `<div class="panel"><div class="panel-inner panel-title"><div><h2>Реестр назначений</h2><p>Синтетические сотрудники</p></div>
    <input class="search" data-search placeholder="Имя или организация" aria-label="Найти заместителя"></div><div data-table></div></div>`
  filteredTable(container,deputies,d=>`<tr><td class="row-name">${esc(d.name)}</td><td>${esc(names[d.region])}</td><td>${esc(d.title)}</td>
    <td>${esc(d.starts)} — ${esc(d.ends||"действует")}</td><td>${esc(Object.entries(d.assignments).map(([k,v])=>k+": "+v.join(", ")).join(" · "))}</td>
    <td>${writable&&!d.ends?`<button class="btn small" data-prev="${esc(d.id)}">Изменить курирование</button>`:""}</td></tr>`,
    ["Заместитель","Организация","Должность","Период","Коды","Действие"],{text:d=>[d.name,names[d.region],d.title].join(" ")})
  const choose=(previous=null)=>{
    dialog(previous?"Изменение курирования":"Новое назначение",`<form class="form">
     ${grade(select(regions.map(r=>[r.id,r.name]),previous?.region||regions[0].id,"region"),"Организация")}
     ${input("Имя","name",previous?.name,"text","required")}${input("Должность","title",previous?.title,"text","required")}
     <div class="fields">${input("Начало","starts","","date","required")}${input("Окончание","ends","","date")}</div>
     ${grade(select([["demo","Демонстрационный"],["source","Исходные документы"]],"demo","track"),"Контур")}
     ${input("Коды субкомпонентов через запятую","assignments",previous?.assignments.demo?.join(", "),"text","required")}
     <button class="btn primary">Сохранить назначение</button></form>`,node=>{
       node.querySelector("form").onsubmit=e=>{
         e.preventDefault()
         act(async()=>{
           const body=formValues(e.target)
           body.assignments=body.assignments.split(",").map(v=>v.trim()).filter(Boolean)
           if(previous) body.previous=previous.id
           await api("/deputies",{method:"POST",json:body})
           node.close();toast("Назначение сохранено.");navigate("assignments")
         },e.submitter)
       }
    })
  }
  container.querySelector("[data-add]")?.addEventListener("click",()=>choose())
  container.addEventListener("click",event=>{
    const b=event.target.closest("[data-prev]")
    if(b) choose(deputies.find(d=>d.id===b.dataset.prev))
  })
}

const accountRoles=[["reporter","Специалист ДГД / ЦТЛ"],["reviewer","Проверяющий"],["signer","Подписант"],
  ["analyst","Аналитик УСР"],["technical","Технический администратор"],["method","Администратор методики"],["approver","Утверждающий"]]
export async function renderTechnical(container) {
  const [data,regions]=await Promise.all([api("/technical"),api("/regions")])
  container.innerHTML=heading("Техническое администрирование","Учётные записи, журнал и состояние подключений",
    '<button class="btn primary" data-add>Создать учётную запись</button>')
    + `<section class="panel panel-inner section"><h2>Состояние среды</h2>
       <div class="meta-grid"><div><small>Сервис</small><strong>Доступен</strong></div><div><small>База данных</small><strong>${esc(data.database)}</strong></div>
       <div><small>Режим подписи</small><strong>Демонстрационная подпись</strong></div></div></section>
     <section class="panel section"><div class="panel-inner panel-title"><div><h2>Учётные записи</h2></div>
       <input class="search" data-search placeholder="Логин, имя или роль" aria-label="Поиск учётной записи"></div><div data-table></div></section>
     <section class="panel section"><div class="panel-inner"><h2>Интеграции</h2></div>
       ${table(["Источник","Состояние"],data.integrations.map(r=>`<tr><td class="row-name">${esc(r.name)}</td><td>${esc(r.status)}</td></tr>`))}</section>
     <section class="panel"><div class="panel-inner"><h2>Журнал действий</h2></div>
       ${table(["Время","Сотрудник","Действие","Объект"],data.events.map(r=>`<tr><td>${esc(fmt(r.happened))}</td>
       <td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td>${esc(r.object)}</td></tr>`))}</section>`
  filteredTable(container,data.users,u=>`<tr><td class="row-name">${esc(u.id)}</td><td>${esc(u.name)}</td>
   <td>${esc(accountRoles.find(r=>r[0]===u.role)?.[1])}</td><td>${esc(u.scope||"—")}</td><td>
   ${u.active?pill("ok","Активна"):pill("na","Отключена")}</td><td>${u.id===state.user.id?"—":
   `<button class="btn small" data-user="${esc(u.id)}" data-active="${u.active}">${u.active?"Отключить":"Включить"}</button>`}</td></tr>`,
   ["Логин","Имя","Роль","Область доступа","Статус","Действие"],{text:u=>[u.name,u.id,u.role,u.scope].join(" ")})
  container.addEventListener("click",event=>{
    const b=event.target.closest("[data-user]")
    if(!b) return
    act(async()=>{
      await api("/technical/users",{method:"POST",json:{id:b.dataset.user,active:b.dataset.active==="0"}})
      toast("Доступ обновлён.");navigate("technical",null,false)
    },b)
  })
  container.querySelector("[data-add]").onclick=()=>{
    dialog("Учётная запись",`<form class="form">
    ${input("Логин","id","","text","required")}${input("Имя","name","","text","required")}
    ${grade(select(accountRoles.slice(0,5),"reporter","role"),"Роль")}
    <div data-org>${grade(select(regions.map(r=>[r.id,r.name]),regions[0].id,"region"),"Организация")}</div>
    <div data-dept hidden>${input("Подразделение КГД","department")}</div>
    ${input("Пароль","password","","password","required minlength=12 autocomplete=new-password")}
    <button class="btn primary">Создать</button></form>`,node=>{
      const form=node.querySelector("form")
      form.elements.role.onchange=()=>{
        const role=form.elements.role.value
        form.querySelector("[data-org]").hidden=role!=="reporter"
        form.querySelector("[data-dept]").hidden=!["reviewer","signer"].includes(role)
      }
      form.onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const values=formValues(form)
          const scope=values.role==="reporter"?values.region:["reviewer","signer"].includes(values.role)?values.department:""
          await api("/technical/users",{method:"POST",json:{...values,scope}})
          node.close();toast("Учётная запись создана.");navigate("technical")
        },e.submitter)
      }
    })
  }
}
