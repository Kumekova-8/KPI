import { renderDashboard, renderCard, renderDiscrepancies, renderCalendar } from "./dashboard.js"
import { renderPackages, renderPackage } from "./packages.js"
import { renderMethods, renderVersion, renderDeputies, renderTechnical } from "./method.js"

export const state = { user: null, view: "", track: "demo", period: "2026-10", kind: "month", id: null }
const root = document.querySelector("#root")
export const statusNames = {
  ok:"Рассчитано", preview:"Предварительный расчёт", na:"Не применяется",
  missing:"Данные не представлены", unconfirmed:"Данные не подтверждены",
  impossible:"Расчёт невозможен", blocked:"Требуется уточнение методики",
  draft:"Черновик", submitted:"На проверке", checked:"К подписанию", returned:"На доработке",
  signed:"Подписан", review:"На утверждении", approved:"Утверждена", published:"Опубликована"
}
const roleNames = {analyst:"Аналитика УСР",reporter:"Отчётность",reviewer:"Проверка данных",
  signer:"Подписание пакетов",method:"Администратор методики",approver:"Утверждение методики",technical:"Технический администратор"}
const pages = {
  dashboard:["Обзор KPI","▥"], packages:["Пакеты отчётности","▤"], deputies:["Рейтинг заместителей","♙"],
  problems:["Проблемные показатели","◇"], calendar:["Календарь","▦"], discrepancies:["Реестр расхождений","⚑"],
  report:["Результаты","▥"], methods:["Версии методики","▤"], assignments:["Курирование","♙"], technical:["Управление доступом","⚙"]
}
const views = {
  analyst:["dashboard","packages","deputies","problems","calendar","discrepancies"],
  reporter:["packages","report","calendar"], reviewer:["packages","calendar"], signer:["packages","calendar"],
  method:["methods","assignments","discrepancies","calendar"], approver:["methods","assignments","discrepancies"],
  technical:["technical"]
}
const months = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
export const monthLabel = period => `${months[Number(period.slice(-2))-1]} ${period.slice(0,4)}`
export const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]))
export const number = (value, max=2) => value == null ? "—" : new Intl.NumberFormat("ru-RU",{maximumFractionDigits:max}).format(value)
export const signedNumber = value => value == null ? "—" : `${value > 0 ? "+" : ""}${number(value)}`
export const pill = (key, label) => `<span class="pill ${esc(key)}">${esc(label || statusNames[key] || key)}</span>`
export const select = (values, chosen, name, extra="") => `<select name="${esc(name)}" ${extra}>${values.map(([key,l])=>
  `<option value="${esc(key)}" ${key===chosen?"selected":""}>${esc(l)}</option>`).join("")}</select>`
export const query = more => "?" + new URLSearchParams({track:state.track,period:state.period,kind:state.kind,...more})
export const empty = (label="Данных за выбранный период пока нет.") => `<div class="empty">${esc(label)}</div>`

let toastTimer
export function toast(message,error=false) {
  const box = document.querySelector("#toast")
  box.textContent = message
  box.className = "show" + (error ? " error" : "")
  clearTimeout(toastTimer)
  toastTimer=setTimeout(()=>box.className="",4500)
}

export async function api(path, opts={}) {
  const config = {...opts,headers:{...opts.headers}}
  if (opts.json) {
    delete config.json
    config.headers["Content-Type"]="application/json"
    config.body=JSON.stringify(opts.json)
  }
  const response = await fetch("/api"+path,config)
  const data = await response.json()
  if (!response.ok) {
    const error = new Error(data.error || "Не удалось выполнить запрос.")
    error.status=response.status
    throw error
  }
  return data
}

export async function act(fn, button) {
  if (button) button.disabled = true
  try { await fn() }
  catch (err) { toast(err.message,true) }
  finally { if (button) button.disabled = false }
}

function brand() {
  return '<div class="brand"><span class="brand-icon" aria-hidden="true"><i></i><i></i><i></i></span><div><strong>KPI КГД</strong><small>Комитет государственных<br>доходов МФ РК</small></div></div>'
}
export function heading(title, subtitle="", action="") {
  return `<div class="page-head"><div><div class="eyebrow">${esc(state.track==="demo"?"Демонстрационный контур":"Контур исходной методики")}</div>
    <h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:""}</div>${action}</div>`
}
export function filters(extra="") {
  return `<div class="tool-row"><div class="filters" id="filters">${select([["month","Месяц"],["quarter","Квартал"],["year","Год"]],state.kind,"kind",'aria-label="Вид периода"')}
  <input name="period" aria-label="Отчётный период" type="month" min="2026-01" value="${esc(state.period)}">
  ${select([["demo","Демонстрационная методика"],["source","Исходные документы"]],state.track,"track",'aria-label="Контур методики"')}
  </div>${extra}</div>`
}
export function bindFilters(container) {
  container.querySelector("#filters")?.addEventListener("change",event=>{
    const {name,value} = event.target
    if (!name || !value) return
    state[name]=value
    let m=Number(state.period.slice(-2))
    if(state.kind==="quarter") m=Math.ceil(m/3)*3
    if(state.kind==="year") m=12
    state.period=state.period.slice(0,5)+String(m).padStart(2,"0")
    navigate(state.view,state.id,false)
  })
}
export function table(headers,rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map(v=>`<th scope="col">${esc(v)}</th>`).join("")}</tr></thead>
   <tbody>${rows.join("")}</tbody></table></div>`
}
export function filteredTable(container, rows, make, headers, options={}) {
  const search = container.querySelector("[data-search]")
  const status = container.querySelector("[data-status]")
  const holder = container.querySelector("[data-table]")
  function draw() {
    const term=(search?.value || "").toLocaleLowerCase("ru").trim()
    const list=rows.filter(row=>(!term || options.text(row).toLocaleLowerCase("ru").includes(term)) &&
      (!status?.value || row.status===status.value))
    holder.innerHTML=list.length?table(headers,list.map(make)):empty(options.empty)
  }
  search?.addEventListener("input",draw)
  status?.addEventListener("change",draw)
  draw()
}
export function dialog(title,html,binder) {
  const node=document.createElement("dialog")
  node.innerHTML=`<div class="dialog-head"><h2>${esc(title)}</h2><button type="button" class="btn icon" aria-label="Закрыть" data-close>×</button></div>${html}`
  document.body.append(node)
  node.querySelector("[data-close]").onclick=()=>node.close()
  node.addEventListener("close",()=>node.remove(),{once:true})
  node.showModal()
  binder?.(node)
  return node
}

function renderLogin() {
  state.user=null
  const choices=[["analyst","УСР"],["dgd","ДГД"],["reviewer-dasur","Проверяющий"],["signer-dasur","Подписант"],["method","Методика"],["approval","Утверждение"],["ctl","ЦТЛ"],["tech","Администратор"]]
  root.innerHTML=`<main class="signin"><section class="signin-aside">${brand()}<div class="signin-shape"></div>
    <h1>Отчётность и аналитика KPI</h1><p>Мониторинг территориальных департаментов, Центральной таможенной лаборатории и заместителей руководителей.</p>
    </section><section class="signin-body"><div class="login-card"><div class="eyebrow">Локальная демонстрация</div><h1>Вход в систему</h1>
    <p>Выберите демонстрационный кабинет или введите учётные данные.</p>
    <form class="form" id="login"><label class="field"><span>Логин</span><input name="username" autocomplete="username" required></label>
    <label class="field"><span>Пароль</span><input name="password" type="password" autocomplete="current-password" required></label>
    <button class="btn primary" type="submit">Войти</button></form>
    <div class="demo-accounts"><strong>Демонстрационные кабинеты</strong><div class="actions">
    ${choices.map(([key,label])=>`<button class="btn small" type="button" data-account="${key}">${label}</button>`).join("")}
    </div></div></div></section></main>`
  const form=root.querySelector("#login")
  form.addEventListener("submit",e=>{
    e.preventDefault()
    act(async()=>{
      state.user=await api("/login",{method:"POST",json:Object.fromEntries(new FormData(form))})
      navigate(views[state.user.role][0])
    },form.querySelector("button"))
  })
  root.querySelectorAll("[data-account]").forEach(button=>button.onclick=()=>{
    form.elements.username.value=button.dataset.account
    form.elements.password.value="Kpi-demo-26!"
    form.requestSubmit()
  })
}

function shell() {
  const user=state.user
  const title=state.view==="package" ? "Пакет отчётности" : state.view==="card" ? "Карточка KPI" :
    state.view==="version" ? "Конструктор методики" : pages[state.view]?.[0]
  const selected={package:"packages",card:"dashboard",version:"methods"}[state.view]||state.view
  root.innerHTML=`<div class="shell"><aside class="sidebar">${brand()}<nav aria-label="Главное меню"><div class="navlabel">Рабочее пространство</div>
  ${views[user.role].map(id=>`<button class="navbtn ${selected===id?"active":""}" data-view="${id}" ${selected===id?'aria-current="page"':""}>
    <span aria-hidden="true" class="navicon">${pages[id][1]}</span>${pages[id][0]}</button>`).join("")}</nav>
  <div class="sidefoot"><strong><span class="status-dot"></span>Демонстрационная среда</strong><small>Синтетические данные</small></div></aside>
  <main class="main"><header class="topbar"><div class="crumb">Кабинет <span>›</span> <b>${esc(title)}</b></div>
    <div class="account"><div class="avatar" aria-hidden="true">${esc((user.scope || roleNames[user.role]).slice(0,3).toUpperCase())}</div>
    <div class="account-label"><b>${esc(user.name)}</b><small>${esc(roleNames[user.role])}</small></div>
    <button id="logout" class="btn icon">Выйти</button></div></header><div id="content" class="content" aria-live="polite"></div></main></div>`
  root.querySelector("#logout").onclick=e=>act(async()=>{
    await api("/logout",{method:"POST",json:{}})
    renderLogin()
  },e.target)
  root.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>navigate(button.dataset.view))
  return root.querySelector("#content")
}

export async function navigate(view,id=null,scroll=true) {
  state.view=view
  state.id=id
  const current=shell()
  if(scroll) window.scrollTo(0,0)
  current.innerHTML=empty("Загрузка…")
  try {
    if (["dashboard","deputies","problems"].includes(view)) await renderDashboard(current,view)
    if (view==="packages") await renderPackages(current)
    if (view==="package") await renderPackage(current,id)
    if (view==="report"||view==="card") await renderCard(current,id||state.user.scope)
    if (view==="methods") await renderMethods(current)
    if (view==="version") await renderVersion(current,id)
    if (view==="assignments") await renderDeputies(current)
    if (view==="technical") await renderTechnical(current)
    if (view==="calendar") await renderCalendar(current)
    if (view==="discrepancies") await renderDiscrepancies(current)
    bindFilters(current)
  } catch(error) {
    if (!current.isConnected) return
    if (error.status===401) renderLogin()
    else current.innerHTML=`<div class="panel">${empty(error.message)}</div>`
  }
}

api("/me").then(user=>{
  state.user=user
  navigate(views[user.role][0])
}).catch(()=>renderLogin())
