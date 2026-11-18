import { act, api, dialog, empty, esc, filteredTable, filters, heading, monthLabel, navigate, number,
  pill, query, select, state, toast } from "./app.js"

const actions = {create:"Создан черновик",save:"Сохранены сведения",submit:"Направлен на проверку",return:"Возвращён на доработку",
  check:"Проверены сведения",sign:"Демонстрационная подпись",revise:"Создана новая редакция",attach:"Добавлен файл",
  detach:"Удалён файл",source_prefill:"Заполнено из синтетического источника"}
const workflowNames = [["","Все статусы"],["missing","Ожидается"],["draft","Черновик"],["submitted","На проверке"],
  ["returned","На доработке"],["checked","К подписанию"],["signed","Подписан"]]
const cadenceNames = {month:"Месяц",quarter:"Квартал",year:"Год",control:"Контрольная дата",multi:"Месяц, квартал и год"}

export async function renderPackages(container) {
  const data=await api("/packages"+query())
  const reporter=state.user.role==="reporter"
  const labels={reporter:"Подготовка и представление сведений",reviewer:"Проверка показателей подразделения",signer:"Подписание пакетов подразделения",analyst:"Пакеты отчётности"}
  container.innerHTML=heading(labels[state.user.role],data.method)+filters()
    + data.notifications.map(n=>`<p class="note" role="status">${esc(n.label)} · ${n.count}</p>`).join("")
    + `<section class="panel"><div class="panel-inner panel-title"><div><h2>Пакеты на ${esc(monthLabel(state.period))}</h2>
       <p>${data.packages.length} · ${reporter?"по ответственным подразделениям":"по организациям и подразделениям"}</p></div><div class="filters">
       <input class="search" data-search placeholder="Организация или подразделение" aria-label="Поиск пакетов">
       ${select(workflowNames,"","status",'data-status aria-label="Статус пакета"')}</div></div><div data-table></div></section>`
  const order={returned:0,submitted:1,checked:2,draft:3,missing:4,signed:5}
  const rows=[...data.packages].sort((a,b)=>(state.user.role==="signer"?(a.status!=="checked")-(b.status!=="checked"):0)||order[a.status]-order[b.status])
  filteredTable(container,rows,r=>`<tr><td class="row-name">${esc(r.region_name)}</td><td>${esc(r.department)}</td>
    <td class="num">${r.count}</td><td>${pill(r.status,r.status==="missing"?"Ожидается":null)}</td><td>${r.revision??"—"}</td>
    <td><button class="btn small" data-package="${esc(r.id||"")}" data-department="${esc(r.department)}">
    ${r.id?"Открыть":reporter?"Создать пакет":"—"}</button></td></tr>`,
    ["Организация","Подразделение КГД","Субкомпоненты","Статус","Версия","Действие"],
    {text:r=>r.region_name+" "+r.department,empty:"Пакетов в этом периоде пока нет."})
  container.addEventListener("click",e=>{
    const b=e.target.closest("[data-package]")
    if(!b) return
    if(b.dataset.package) return navigate("package",b.dataset.package)
    if(reporter) act(async()=>{
      const created=await api("/packages"+query(),{method:"POST",json:{department:b.dataset.department}})
      navigate("package",created.id)
    },b)
  })
}

function componentHtml(entry,p,edit,canReturn) {
  const values=p.facts[entry.code]||{}
  const fields=entry.rule?.fields||[]
  const writable=edit&&(p.status!=="returned"||entry.code in p.notes)
  const files=p.attachments.filter(f=>f.component===entry.code)
  const score=entry.calculation
  const scale=entry.rule?.bands||[]
  const ruleLabel=row=>`${({ge:"≥",gt:">",le:"≤",lt:"<",eq:"=",range:"от"})[row.op]} ${number(row.target)}${row.op==="range"?" до "+number(row.upper):""} → ${number(row.points)} балл.`
  return `<article class="report-component"><div class="comp-title"><div><h3><b>${esc(entry.code)}</b>${esc(entry.name)}</h3>
   <small>${esc(entry.metric_name)} · ${esc(cadenceNames[entry.cadence])}${entry.cumulative?" · Нарастающим итогом":""}
   ${entry.cadence==="control"?" · "+esc((entry.control_dates||["09-15","12-31"]).join(", ")):""}</small></div>${pill(score.status)}</div>
   <div class="meta-grid"><div><small>Источник данных</small>${esc(entry.source)}</div><div><small>Подразделение</small>${esc(entry.department)}</div>
   <div><small>Результат и баллы</small>${number(score.actual)} · ${number(score.points)} из ${number(score.base)}</div></div>
   ${p.notes[entry.code]?`<p class="note">${esc(p.notes[entry.code])}</p>`:""}
   ${fields.length?"":'<p class="note">Исходные поля требуют уточнения методики.</p>'}
   <div class="fields">${fields.map(field=>`<label class="field"><span>${esc(field.key)} · ${esc(field.label)}</span>
    <input autocomplete="off" inputmode="decimal" name="${esc(entry.code)}:${esc(field.key)}" data-input value="${esc(values[field.key]??"")}" ${writable?"":"readonly"}></label>`).join("")}</div>
   <details class="details"><summary>Правило начисления баллов</summary>
   ${scale.length?`<p class="readout spaced">${esc(entry.rule.expression)} · ${esc(scale.map(ruleLabel).join(" · "))}</p>`:""}
   ${entry.rule?.variants?.length?`<div class="readout spaced">Варианты шкалы · ${entry.rule.variants.map(v=>esc(v.bands.map(ruleLabel).join(", "))).join(" / ")}</div>`:""}
   <div class="instruction">${esc(entry.instruction||"Правило описано в настройках версии.")}</div></details>
   ${files.length?`<div class="attachments">${files.map(f=>`<div class="attachment"><a href="/api/packages/${p.id}/attachment/${f.id}">↓ ${esc(f.name)}</a>
   <small>${Math.ceil(f.size/1024)} КБ</small>${writable?`<button type="button" class="btn small" data-remove="${f.id}">Удалить</button>`:""}</div>`).join("")}</div>`:""}
   ${writable?`<div class="spaced"><button class="btn small" type="button" data-upload="${esc(entry.code)}">Приложить файл</button></div>`:""}
   ${canReturn?`<label class="field spaced"><span>Замечание для возврата строки</span>
   <textarea maxlength="1500" data-comment="${esc(entry.code)}" placeholder="Укажите, что нужно исправить"></textarea></label>`:""}</article>`
}

export async function renderPackage(container,id) {
  const p=await api("/packages/"+id)
  const reporter=state.user.role==="reporter"
  const reviewer=state.user.role==="reviewer"
  const signer=state.user.role==="signer"
  const current=p.revisions[0]?.id===p.id
  const edit=reporter&&current&&["draft","returned"].includes(p.status)
  const canReturn=reviewer&&current&&["submitted","checked"].includes(p.status)
  const check=reviewer&&current&&p.status==="submitted"
  const sign=signer&&current&&p.status==="checked"
  const revise=reporter&&current&&p.status==="signed"
  container.innerHTML=heading(p.region_name,p.department+" · "+monthLabel(p.period),
   `<div class="actions"><button class="btn" data-back>← К пакетам</button>${pill(p.status)}</div>`)
   + `<section class="panel panel-inner section"><div class="panel-title"><div><h2>Пакет отчётности</h2><p>Редакция ${p.revision} · ${p.entries.length} субкомпонентов</p></div>
   <div class="actions"><a class="btn" href="/api/packages/${p.id}/template.xlsx">↓ Шаблон Excel</a>
   ${edit?`<button class="btn" data-import>Импорт Excel</button>${p.track==="demo"?'<button class="btn" data-prefill>Заполнить из источника</button>':""}`:""}</div></div>
   ${p.signature?`<div class="readout">${esc(p.signature.label)} · ${p.signature.valid_digest?"Целостность пакета проверена":"Нарушена целостность пакета"}
   · <a href="/api/packages/${p.id}/signature">Скачать подписанную версию</a></div>`:""}
   ${p.revisions.length>1?`<div class="spaced actions"><small>Редакции</small>
      ${p.revisions.map(v=>`<button type="button" class="btn small" data-rev="${v.id}" ${v.id===p.id?"disabled":""}>${v.revision} · ${esc(workflowNames.find(x=>x[0]===v.status)?.[1])}</button>`).join("")}</div>`:""}</section>
   <div class="card-list section">${p.entries.map(e=>componentHtml(e,p,edit,canReturn)).join("")}</div>
   <div class="actions section">
   ${edit?'<button class="btn" data-action="save">Сохранить черновик</button><button class="btn primary" data-action="submit">Отправить на проверку</button>':""}
   ${canReturn?'<button class="btn warn" data-action="return">Вернуть отмеченные строки</button>':""}
   ${check?'<button class="btn primary" data-action="check">Подтвердить проверку целого пакета</button>':""}
   ${sign?'<button class="btn primary" data-action="sign">Демонстрационная подпись</button>':""}
   ${revise?'<button class="btn primary" data-revise>Создать редакцию для исправления</button>':""}
   </div>
   <section class="panel panel-inner"><h2>История пакета</h2>${p.history.length?`<div class="stack spaced">${p.history.map(h=>`<div><strong>${esc(actions[h.action]||h.action)}</strong>
     <small> · ${esc(h.name)} · ${esc(new Date(h.happened).toLocaleString("ru-RU"))}</small>
     ${h.action==="return"?`<p class="note">${esc(Object.entries(h.detail||{}).map(([k,v])=>`${k} · ${v}`).join(" / "))}</p>`:""}
     ${h.action==="save"&&h.detail.changes&&Object.keys(h.detail.changes).length?
       `<details class="details"><summary>Изменённые поля</summary><div class="instruction">${esc(JSON.stringify(h.detail.changes,null,2))}</div></details>`:""}
     ${h.action==="revise"?`<p class="note">${esc(h.detail.reason)}</p>`:""}</div>`).join("")}</div>`:empty("Действий пока нет.")}</section>`
  let generation=p.generation
  const root="/packages/"+p.id
  const refresh=()=>navigate("package",p.id,false)
  const action=(name,data={})=>api(root+"/"+name,{method:"POST",json:{...data,generation}})
  const urlInfo=params=>"?"+new URLSearchParams({...params,generation})
  async function save() {
    const facts={}
    for(const input of container.querySelectorAll("[data-input]:not([readonly])")){
      const [code,key]=input.name.split(":")
      facts[code]??={}
      facts[code][key]=input.value.trim()
    }
    await action("save",{facts})
    generation++
  }
  container.querySelector("[data-back]").onclick=()=>navigate("packages")
  container.querySelectorAll("[data-rev]").forEach(b=>b.onclick=()=>navigate("package",b.dataset.rev,false))
  container.querySelectorAll("[data-action]").forEach(button=>button.onclick=()=>act(async()=>{
    const name=button.dataset.action
    if(name==="save"||name==="submit") await save()
    if(name==="return") {
      const comments=Object.fromEntries([...container.querySelectorAll("[data-comment]")]
        .filter(el=>el.value.trim()).map(el=>[el.dataset.comment,el.value.trim()]))
      await action(name,{comments})
    } else if(name!=="save"){
      await action(name)
    }
    toast(actions[name]||"Действие выполнено.")
    refresh()
  },button))
  container.querySelector("[data-prefill]")?.addEventListener("click",e=>act(async()=>{
    await save()
    await action("prefill")
    toast("Получены синтетические данные.")
    refresh()
  },e.target))
  container.querySelectorAll("[data-upload]").forEach(b=>b.onclick=()=>{
    dialog("Подтверждающий документ",'<form class="form"><label class="field"><span>PDF, PNG или JPEG · до 5 МБ</span><input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" required></label><button class="btn primary">Загрузить</button></form>',node=>{
      node.querySelector("form").onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const file=e.target.elements.file.files[0]
          await save()
          await api(root+"/attachment"+urlInfo({code:b.dataset.upload,name:file.name}),{method:"POST",body:file,headers:{"Content-Type":file.type}})
          node.close();toast("Файл приложен.");refresh()
        },e.submitter)
      }
    })
  })
  container.querySelectorAll("[data-remove]").forEach(b=>b.onclick=()=>act(async()=>{
    await save();await api(root+"/attachment/"+b.dataset.remove+urlInfo(),{method:"DELETE"})
    toast("Файл удалён.");refresh()
  },b))
  container.querySelector("[data-revise]")?.addEventListener("click",()=>{
    dialog("Новая редакция пакета",'<form class="form"><label class="field"><span>Основание корректировки</span><textarea name="reason" required minlength="3" maxlength="1500"></textarea></label><button class="btn primary">Создать редакцию</button></form>',node=>{
      node.querySelector("form").onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const result=await action("revise",{reason:e.target.elements.reason.value})
          node.close();toast("Редакция создана.");navigate("package",result.id)
        },e.submitter)
      }
    })
  })
  container.querySelector("[data-import]")?.addEventListener("click",()=>{
    dialog("Импорт Excel",`<form class="form"><p>Используйте шаблон пакета. Значения из книги можно проверить перед применением.</p>
    <input name="file" type="file" accept=".xlsx" required><div data-feedback></div><div class="actions">
    <button class="btn" name="check">Проверить книгу</button><button class="btn primary" name="apply" disabled>Применить</button></div></form>`,node=>{
      const form=node.querySelector("form")
      form.elements.file.onchange=()=>form.elements.apply.disabled=true
      form.onsubmit=e=>{
        e.preventDefault()
        act(async()=>{
          const applying=e.submitter.name==="apply"
          if(applying) await save()
          const result=await api(root+"/import"+urlInfo({apply:applying?1:0}),{method:"POST",body:form.elements.file.files[0]})
          if(applying){ node.close();toast("Данные из Excel добавлены.");refresh();return }
          form.querySelector("[data-feedback]").innerHTML=`<p>Готово к загрузке: ${result.ready}</p>${result.issues.map(x=>`<div class="note">${esc(x)}</div>`).join("")}`
          form.elements.apply.disabled=Boolean(result.issues.length||!result.ready)
        },e.submitter)
      }
    })
  })
}
