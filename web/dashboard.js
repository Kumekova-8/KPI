import { act, api, dialog, empty, esc, filteredTable, filters, heading, monthLabel, navigate,
  number, pill, query, select, signedNumber, state, statusNames, table, toast } from "./app.js"

const blocks = ["Фискальный блок","Администрирование","Контрольный блок","Сервисный блок","Управленческий блок"]
const percent=value=>value==null?"—":`${number(value,1)}%`
const gradeLabel=row=>row.grade?`${row.grade.code} · ${row.grade.label}`:null
const link=(format,more={},text)=>`<a class="btn ${format==="xlsx"?"primary":""}" href="/api/export.${format}${esc(query(more))}">↓ ${esc(text||format.toUpperCase())}</a>`
const tile=(caption,value,detail,icon,tone="")=>`<article class="panel tile"><div class="tile-caption">${esc(caption)}<span class="tile-icon ${tone}" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`

function drawChart(canvas, points) {
  function draw() {
    const width=canvas.clientWidth
    if(width<50) return
    const height=canvas.clientHeight
    const ratio=window.devicePixelRatio||1
    canvas.width=width*ratio
    canvas.height=height*ratio
    const ctx=canvas.getContext("2d")
    ctx.scale(ratio,ratio)
    ctx.font='11px "Segoe UI", sans-serif'
    const left=36,right=width-20,top=16,bottom=height-27
    const actual=points.filter(x=>x.value!=null)
    const min=actual.length?Math.max(0,Math.floor((Math.min(...actual.map(x=>x.value))-5)/10)*10):0
    const y=v=>bottom-(v-min)/(100-min)*(bottom-top)
    ctx.strokeStyle="#e5edf7"
    ctx.fillStyle="#657b96"
    ctx.textBaseline="middle"
    ctx.textAlign="right"
    for(let i=0;i<=4;i++){
      const value=min+(100-min)*i/4
      const yy=y(value)
      ctx.beginPath()
      ctx.moveTo(left,yy)
      ctx.lineTo(right,yy)
      ctx.stroke()
      ctx.fillText(Math.round(value)+"%",left-7,yy)
    }
    const coords=points.map((p,i)=>({ ...p,x:left+(i+.12)*(right-left)/Math.max(1,points.length-.76) }))
    ctx.textAlign="center"
    coords.forEach(p=>ctx.fillText(monthLabel(p.period).split(" ")[0],p.x,bottom+16))
    const visible=coords.filter(p=>p.value!=null)
    if(!visible.length) return
    const segments=[]
    let current=[]
    for(const p of coords){
      if(p.value==null){ if(current.length) segments.push(current); current=[] }
      else current.push(p)
    }
    if(current.length) segments.push(current)
    const fill=ctx.createLinearGradient(0,top,0,bottom)
    fill.addColorStop(0,"#e1edff")
    fill.addColorStop(1,"#f6faff")
    ctx.lineWidth=2.2
    ctx.strokeStyle="#3376de"
    for(const segment of segments){
      ctx.beginPath()
      ctx.moveTo(segment[0].x,bottom)
      segment.forEach(p=>ctx.lineTo(p.x,y(p.value)))
      ctx.lineTo(segment.at(-1).x,bottom)
      ctx.closePath()
      ctx.fillStyle=fill
      ctx.fill()
      ctx.beginPath()
      segment.forEach((p,i)=>i?ctx.lineTo(p.x,y(p.value)):ctx.moveTo(p.x,y(p.value)))
      ctx.stroke()
    }
    for(const p of visible){
      ctx.beginPath()
      ctx.arc(p.x,y(p.value),3.8,0,2*Math.PI)
      ctx.fillStyle="white"
      ctx.fill()
      ctx.stroke()
    }
    canvas.title=visible.map(p=>`${monthLabel(p.period)} · ${percent(p.value)}`).join("\n")
  }
  draw()
  const observer=new ResizeObserver(draw)
  observer.observe(canvas)
}

function rankRow(row) {
  const delta=row.delta>0?"positive":row.delta<0?"negative":""
  return `<tr><td class="num">${row.rank??"—"}</td><td class="row-name"><button type="button" class="btn link" data-region="${esc(row.id)}">${esc(row.name)}</button></td>
    <td class="num"><strong>${percent(row.total)}</strong></td><td class="num ${delta}">${signedNumber(row.delta)}</td>
    <td>${row.received} из ${row.expected}</td><td>${pill(row.status,gradeLabel(row))}</td></tr>`
}

const rankHeaders=["Место","Департамент","Итоговый KPI","Изменение, п. п.","Пакеты подписаны","Статус"]
function withRanks(rows) {
  let prior=null,rank=0
  return rows.map((row,i)=>{
    if(row.total==null) return row
    if(prior!==row.total){rank=i+1;prior=row.total}
    return {...row,rank}
  })
}

export async function renderDashboard(container, view) {
  const data=await api("/dashboard"+query())
  if(view==="deputies") return showDeputies(container,data)
  if(view==="problems") return showProblems(container,data)
  const ranks=withRanks(data.records.filter(r=>r.subject==="dgd"))
  const ctl=data.records.find(r=>r.subject==="ctl")
  const completed=ranks.filter(r=>r.total!=null).length
  const today=new Date(data.date+"T12:00:00").toLocaleDateString("ru-RU",{day:"numeric",month:"long",year:"numeric"})
  const pdf=link("pdf")
  container.innerHTML=heading("Панель мониторинга KPI",
    "Управление стратегического развития · отчётность и результаты по регионам",
    `<div class="actions">${pdf}${link("xlsx",{},"Экспорт Excel")}</div>`)
    + filters(`<small>Состояние на ${esc(today)}</small>`)
    + `<div class="tiles">
      ${tile("Территориальные ДГД",data.dgd_count,`${completed} с рассчитанным итогом`,"▥")}
      ${tile("Средний KPI ДГД",percent(data.average),"По завершённым расчётам","↗","green")}
      ${tile("Неподтверждённые пакеты",data.counts.submitted+data.counts.checked+data.counts.returned,`${data.counts.signed} пакетов подписано`,"▤","purple")}
      ${tile("Просроченные проверки",data.late,`${data.counts.missing+data.counts.draft} пакетов ожидают подачи`,"◷","amber")}
    </div>
    <div class="report-grid section">
      <section class="panel panel-inner"><div class="panel-title"><div><h2>Динамика среднего KPI</h2><p>Территориальные ДГД с рассчитанным итогом</p></div>
      <span class="chart-summary"><i></i>Средний KPI</span></div>
      ${data.series.some(p=>p.value!=null)?'<canvas class="chart" aria-label="Динамика среднего KPI по периодам"></canvas>':empty("Нет завершённых расчётов для графика.")}</section>
      <section class="panel panel-inner"><div class="panel-title"><div><h2>Функциональные блоки</h2><p>Средняя доля набранных баллов</p></div></div>
      <div class="bars">${blocks.map(b=>`<div><div class="bar-name"><span>${esc(b)}</span><b>${percent(data.blocks[b])}</b></div><div class="rail"><i style="width:${Math.max(0,Math.min(100,data.blocks[b]??0))}%"></i></div></div>`).join("")}</div></section>
    </div>
    <section class="panel section" id="rank"><div class="panel-inner panel-title"><div><h2>Рейтинг территориальных ДГД</h2><p>${esc(data.method)}</p></div>
      <input class="search" data-search placeholder="Найти департамент" aria-label="Найти департамент"></div><div data-table></div></section>
    ${ctl?`<section class="panel section"><div class="panel-inner panel-title"><div><h2>Центральная таможенная лаборатория</h2><p>Отдельный расчёт по пункту 25</p></div></div>${table(rankHeaders,[rankRow(ctl)])}</section>`:""}`
  const canvas=container.querySelector("canvas")
  if(canvas) drawChart(canvas,data.series)
  filteredTable(container.querySelector("#rank"),ranks,rankRow,rankHeaders,{text:r=>r.name})
  container.addEventListener("click",e=>{
    const button=e.target.closest("[data-region]")
    if(button) navigate("card",button.dataset.region)
  })
}

function showDeputies(container,data) {
  const rows=withRanks(data.deputies)
  container.innerHTML=heading("Рейтинг заместителей","Результаты по закреплённым направлениям деятельности")+filters()
    + `<section class="panel"><div class="panel-inner panel-title"><div><h2>Индивидуальные результаты</h2><p>Оценка по пункту 26 методики</p></div>
        <input data-search class="search" placeholder="Поиск по ДГД или должности" aria-label="Поиск заместителей"></div><div data-table></div></section>`
  filteredTable(container,rows,r=>`<tr><td>${r.rank??"—"}</td><td class="row-name">${esc(r.name)}<br><small>${esc(r.title)}</small></td><td>${esc(r.region)}</td>
   <td>${esc(r.blocks.join(", ")||"—")}</td><td class="num">${percent(r.total)}</td><td class="num">${signedNumber(r.delta)}</td>
   <td>${pill(r.status,gradeLabel(r))}</td><td><div class="actions"><button class="btn small" data-deputy="${esc(r.id)}">История</button>${link("pdf",{region:r.region_id,deputy:r.id},"Карточка")}</div></td></tr>`,
   ["Место","Заместитель","ДГД / ЦТЛ","Курирование","KPI","Изменение","Статус","Отчёт"],{text:r=>[r.name,r.title,r.region].join(" ")})
  container.addEventListener("click",event=>{
    const button=event.target.closest("[data-deputy]")
    if(!button) return
    act(async()=>{
      const d=await api("/deputies/"+button.dataset.deputy+"/results"+query())
      const history=d.results.length ? table(["Период","KPI","Версия","Курирование"],d.results.map(x=>
        `<tr><td>${esc(monthLabel(x.period))}</td><td>${percent(x.total)}</td><td>${x.revision}</td><td>${esc(x.blocks.join(", "))}</td></tr>`))
        : empty("Подписанных результатов за выбранные периоды пока нет.")
      dialog(d.name,`<p>${esc(d.title)}</p>${history}`)
    },button)
  })
}

function showProblems(container,data) {
  container.innerHTML=heading("Проблемные показатели","Недостигнутые цели и случаи, требующие методологического решения")+filters()
    + `<section class="panel"><div class="panel-inner panel-title"><div><h2>Отклонения по субкомпонентам</h2></div><div class="filters">
    <input data-search class="search" placeholder="Код, регион или наименование" aria-label="Поиск отклонения">
    ${select([["","Все отклонения"],["ok","Недостигнутые цели"],["blocked","Требуется уточнение"]],"","status",'data-status aria-label="Тип отклонения"')}</div></div><div data-table></div></section>`
  filteredTable(container,data.problems,r=>`<tr><td>${esc(r.code)}</td><td class="row-name">${esc(r.name)}</td><td>${esc(r.region)}</td>
  <td>${number(r.actual)}</td><td>${number(r.points)} / ${number(r.base)}</td><td>${pill(r.status)}</td></tr>`,
  ["Код","Субкомпонент","Организация","Факт","Баллы","Статус"],{text:r=>[r.code,r.region,r.name].join(" ")})
}

export async function renderCard(container,region) {
  const data=await api("/report"+query({region}))
  const result=data.official||data.working
  const rows=result.rows
  const actions=state.user.role==="analyst"?`<div class="actions">${link("pdf",{region})}${link("xlsx",{region})}</div>`:""
  container.innerHTML=heading(result.region_name,result.method_name,actions)
    + filters(state.user.role==="analyst"?'<button data-back class="btn">← К обзору</button>':"")
    + `<div class="tiles">${tile("Итоговый KPI",percent(result.total),statusNames[result.status],"▥")}
    ${tile("Баллы рассчитаны",`${result.reported} из ${result.required}`,"Применимые субкомпоненты","▤","green")}
    ${tile("Версия результата",data.official?.revision??"—",data.official?"Подтверждённые сведения":"Рабочий расчёт","◇","purple")}</div>
    ${result.blockers?.length?`<p class="note">Требуется уточнение методики · ${esc(result.blockers.join(", "))}</p>`:""}
    <section class="panel section"><div class="panel-inner panel-title"><div><h2>Расчётная форма KPI</h2><p>Индикаторы, показатели и субкомпоненты</p></div>
       <input class="search" data-search placeholder="Найти субкомпонент" aria-label="Найти субкомпонент"></div><div data-table></div></section>
    <section class="panel panel-inner section"><h2>История результатов</h2>${data.history.length?data.history.map(r=>
       `<p><button class="btn small" data-result="${r.revision}">Версия ${r.revision}</button> · ${esc(new Date(r.created).toLocaleString("ru-RU"))}</p>`).join(""):empty("Завершённых версий пока нет.")}</section>`
  filteredTable(container,rows,r=>`<tr><td>${esc(r.code)}</td><td class="row-name">${esc(r.name)}<br><small>${esc(r.indicator_name)} · ${esc(r.metric)}</small></td><td>${esc(r.department)}</td>
    <td>${number(r.actual)}</td><td>${number(r.base)}</td><td>${number(r.points)}</td><td>${pill(r.status)}</td></tr>`,
    ["Код","Субкомпонент","Подразделение","Факт","Базовый балл","Баллы","Статус"],{text:r=>[r.code,r.name,r.metric,r.indicator_name].join(" ")})
  container.querySelector("[data-back]")?.addEventListener("click",()=>navigate("dashboard"))
  container.querySelectorAll("[data-result]").forEach(button=>button.onclick=()=>act(async()=>{
    const data=await api("/report"+query({region,revision:button.dataset.result}))
    const r=data.official
    dialog("Результат · редакция "+r.revision,`<p>${esc(r.region_name)} · ${esc(r.method_name)} · <strong>${percent(r.total)}</strong></p>
      ${table(["Код","Субкомпонент","Факт","Баллы"],r.rows.filter(x=>x.status!=="na").map(x=>
      `<tr><td>${esc(x.code)}</td><td>${esc(x.name)}</td><td>${number(x.actual)}</td><td>${number(x.points)}</td></tr>`))}`)
  },button))
}

export async function renderDiscrepancies(container) {
  const issues=await api("/discrepancies")
  container.innerHTML=heading("Реестр расхождений","Приказ, приложения 1–3 и расчётные листы Excel")
    + `<section class="panel"><div class="panel-inner panel-title"><div><h2>Замечания к исходным материалам</h2><p>${issues.filter(x=>x.blocking).length} требуют методологического решения</p></div>
    <input class="search" data-search placeholder="Код или содержание" aria-label="Поиск по реестру"></div><div data-table></div></section>`
  filteredTable(container,issues,r=>`<tr><td class="num">${esc(r.id)}</td><td>${esc(r.code)}</td><td>${esc(r.detail)}</td><td>${esc(r.source)}</td><td>${r.blocking?pill("blocked"):pill("na","Справочное")}</td></tr>`,
    ["Код записи","Объект","Расхождение","Источник","Статус"],{text:r=>Object.values(r).join(" ")})
}

export async function renderCalendar(container) {
  const dates=await api("/calendar"+query())
  let counts={}
  if(state.user.role==="analyst") counts=(await api("/dashboard"+query())).counts
  else if(["reporter","reviewer","signer"].includes(state.user.role)){
    const packages=(await api("/packages"+query())).packages
    for(const p of packages) counts[p.status]=(counts[p.status]||0)+1
  }
  const labels=[["submission","Представление сведений","ДГД и ЦТЛ"],["review","Проверка и расчёт","Ответственные подразделения КГД"],["export","Сводная выгрузка","Департамент цифровизации"]]
  const fmt=date=>new Date(date+"T12:00:00").toLocaleDateString("ru-RU",{day:"numeric",month:"long",year:"numeric"})
  container.innerHTML=heading("Календарь отчётности","Сроки исполнения по отчётным периодам")+filters()
    + `<section class="panel panel-inner section"><div class="panel-title"><div><h2>${esc(monthLabel(state.period))}</h2><p>${esc(dates.reason)}</p></div>
    ${state.user.role==="method"?'<button class="btn" data-edit>Указать перенос</button>':""}</div>
    <div class="calendar-grid">${labels.map(([id,name,owner])=>`<div class="date-box"><small>${name}</small><b>${esc(fmt(dates[id]))}</b><small>${owner}</small></div>`).join("")}</div></section>
    ${Object.keys(counts).length?`<section class="panel panel-inner"><h2>Прохождение отчётности</h2><div class="meta-grid">
      ${[["Представлены",(counts.submitted||0)+(counts.checked||0)+(counts.signed||0)+(counts.returned||0)],["Проверены",(counts.checked||0)+(counts.signed||0)],
          ["Возвращены",counts.returned],["Подписаны",counts.signed],["Ожидаются",(counts.missing||0)+(counts.draft||0)]].map(([name,n])=>`<div><small>${name}</small><strong>${n||0}</strong></div>`).join("")}</div></section>`:""}`
  container.querySelector("[data-edit]")?.addEventListener("click",()=>{
    dialog("Сроки с учётом переноса",`<form class="form">${labels.map(([id,name])=>
     `<label class="field"><span>${name}</span><input type="date" name="${id}" required value="${esc(dates[id])}"></label>`).join("")}
     <label class="field"><span>Основание переноса</span><textarea name="reason" required></textarea></label><button class="btn primary">Сохранить</button></form>`,node=>{
       node.querySelector("form").onsubmit=e=>{
         e.preventDefault()
         act(async()=>{
           await api("/calendar"+query(),{method:"PUT",json:Object.fromEntries(new FormData(e.target))})
           node.close();toast("Сроки обновлены.");navigate("calendar")
         },e.submitter)
       }
    })
  })
}
