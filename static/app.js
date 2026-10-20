/* CasePilot frontend: dependency-free, semantic and keyboard-friendly. */
'use strict';
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const human = (value) => ({open:'Open', in_progress:'In progress', resolved:'Resolved', low:'Low', medium:'Medium', high:'High', critical:'Critical'}[value] || String(value));
const dateText = (str) => str ? new Date(str).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'}) : '—';
const initials = (str) => String(str || '—').split(/\s+/).slice(0, 2).map((s)=>s[0]||'').join('').toUpperCase();
const state = {user:null, csrf:'', users:[], view:'overview', tickets:[], selected:null, toastTimer:null, searchTimer:null, page:1, pages:1, sessionVersion:0, ticketRequest:0, overviewRequest:0, activityRequest:0, detailRequest:0, detailConflict:false, importPreview:null, importRevision:0, importRequest:0, importBusy:false};

// A response belongs to the sign-in that started it, even when another account
// has since signed in. Request counters also prevent older reads winning races.
const currentSession = version => Boolean(state.user) && version === state.sessionVersion;

function connectionStatus(connected) {
  const badge = $('#connection-status');
  badge.textContent = connected ? 'Workspace connected' : 'Connection unavailable';
  badge.parentElement.classList.toggle('offline', !connected);
}

function clearSession(message='') {
  state.sessionVersion++;
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  state.user=null;state.csrf='';state.selected=null;state.users=[];state.tickets=[];
  resetImport();
  $('#app-shell').classList.add('hidden');$('#login-screen').classList.remove('hidden');
  $('#password').value='';$('#login-error').textContent=message;$('#username').focus();
}

async function api(path, {method='GET', body=undefined}={}) {
  const sessionVersion = state.sessionVersion;
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  let res;
  try {
    res = await fetch(path, {method, headers, credentials:'same-origin', body:body===undefined?undefined:JSON.stringify(body)});
    if(sessionVersion===state.sessionVersion)connectionStatus(true);
  } catch(error) {if(sessionVersion===state.sessionVersion)connectionStatus(false);throw new Error('Cannot reach the workspace. Check that the local server is running.');}
  const data = await res.json().catch(()=>({error:'Unexpected server response'}));
  if (res.status===401 && currentSession(sessionVersion) && path!=='/api/login') clearSession('Your session ended. Sign in again.');
  if (!res.ok) {
    const error = new Error(data.error || `Request failed (${res.status})`);
    error.status=res.status;error.code=data.code;throw error;
  }
  return data;
}

function toast(message) {
  const box = $('#toast'); box.textContent = message; box.classList.add('show');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(()=>box.classList.remove('show'), 3800);
}

function setAuthenticated(data) {
  state.sessionVersion++;
  state.selected=null; state.users=[]; state.tickets=[]; state.page=1; state.pages=1;
  state.user = data.user; state.csrf = data.csrf;
  resetImport();
  $('#import-tickets').classList.toggle('hidden',state.user.role!=='admin');
  $('#login-screen').classList.add('hidden'); $('#app-shell').classList.remove('hidden');
  for (const id of ['sidebar-avatar','top-avatar']) $("#"+id).textContent = initials(state.user.name);
  $('#sidebar-name').textContent = state.user.name;
  $('#sidebar-role').textContent = state.user.role === 'admin' ? 'Administrator' : 'Support agent';
}

function updateNavigation() {
  const sidebar=$('#sidebar');
  sidebar.inert=window.matchMedia('(max-width:860px)').matches&&!sidebar.classList.contains('open');
  $('#mobile-menu').setAttribute('aria-expanded',String(sidebar.classList.contains('open')));
}

function setView(view) {
  state.view = view;
  document.querySelectorAll('.view').forEach(node => node.classList.toggle('hidden', node.id !== 'view-'+view));
  document.querySelectorAll('[data-view]').forEach(node => {
    const active=node.dataset.view===view;
    node.classList.toggle('active',active);
    if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');
  });
  $('#breadcrumb-current').textContent = {overview:'Overview',tickets:'All tickets',activity:'Activity log'}[view];
  $('#sidebar').classList.remove('open');
  updateNavigation();
  if (view === 'overview') loadOverview();
  if (view === 'tickets') loadTickets();
  if (view === 'activity') loadActivity();
}

const pill = (value) => `<span class="pill ${esc(value)}">${esc(human(value))}</span>`;
function rowMarkup(t, compact=false) {
  const selected = `<td class="ticket-cell"><strong>${esc(t.title)}</strong><small>${esc(t.code)}</small></td>`;
  const who = t.assignee ? `<span class="avatar-small">${esc(initials(t.assignee))}</span>${esc(t.assignee)}` : '<span class="unassigned">Unassigned</span>';
  const overdue=t.status!=='resolved'&&new Date(t.due_at)<new Date();
  return `<tr class="clickable-row" tabindex="0" data-ticket="${Number(t.id)}" aria-label="View ${esc(t.code)} details">${selected}` + (compact ? `<td>${esc(t.category)}</td><td>${pill(t.priority)}</td><td>${pill(t.status)}</td><td>${who}</td>` : `<td>${esc(t.requester)}</td><td>${pill(t.priority)}</td><td>${pill(t.status)}</td><td>${who}</td><td class="${overdue?'overdue-date':''}">${esc(dateText(t.due_at))}${overdue?'<small>Overdue</small>':''}</td>`) + '</tr>';
}

async function loadOverview() {
  const version=state.sessionVersion, request=++state.overviewRequest;
  try {
    const [stats, result, urgent] = await Promise.all([api('/api/stats'), api('/api/tickets?page_size=5'), api('/api/tickets?urgent=1&page_size=100')]);
    if(!currentSession(version)||request!==state.overviewRequest)return;
    $('#metric-total').textContent = stats.total;
    $('#metric-active').textContent = stats.active;
    $('#metric-overdue').textContent = stats.overdue;
    $('#metric-resolved').textContent = stats.total ? `${Math.round(stats.resolved / stats.total * 100)}%` : '0%';
    $('#nav-ticket-count').textContent = stats.total;
    const graph = $('#workflow-graph');
    graph.innerHTML = ['open', 'in_progress', 'resolved'].map((status) => {
      const n=stats.by_status[status] || 0, pct=stats.total ? Math.round(n/stats.total*100) : 0;
      const shade={open:'blue',in_progress:'purple',resolved:'green'}[status];
      return `<div class="workflow-line"><div class="workflow-copy"><span>${human(status)}</span><strong>${n} tickets / ${pct}%</strong></div><div class="track"><progress class="track-bar ${shade}" value="${n}" max="${Math.max(stats.total, 1)}" aria-label="${human(status)}: ${pct}%"></progress></div></div>`;
    }).join('');
    const important = urgent.tickets
      .sort((a,b)=>(a.priority==='critical'?-1:1) - (b.priority==='critical'?-1:1)).slice(0,3);
    $('#priority-tickets').innerHTML = important.length ? important.map(t=>`<div class="priority-item ${esc(t.priority)}" tabindex="0" data-ticket="${Number(t.id)}" role="button" aria-label="Open ${esc(t.code)}"><span class="priority-icon">${t.priority==='critical'?'!':'↑'}</span><div><strong>${esc(t.title)}</strong><span>${esc(t.code)} · ${esc(human(t.priority))} priority · ${esc(dateText(t.due_at))}</span></div></div>`).join('') : '<p class="priority-empty">All urgent requests are resolved.</p>';
    $('#overview-ticket-rows').innerHTML = result.tickets.map(t=>rowMarkup(t,true)).join('') || '<tr><td colspan="5">No requests yet. Create a ticket to start.</td></tr>';
  } catch(e) {if(currentSession(version)&&request===state.overviewRequest)toast('Could not refresh dashboard: '+e.message);}
}

async function loadTickets() {
  const version=state.sessionVersion, request=++state.ticketRequest;
  try {
    const q = $('#search-tickets').value.trim();
    const status=$('#filter-status').value, priority=$('#filter-priority').value;
    const query = new URLSearchParams();
    if (q) query.set('q',q); if (status) query.set('status',status); if (priority) query.set('priority',priority);
    const exportQuery=query.toString();
    query.set('page',state.page);query.set('page_size','25');
    const result=await api('/api/tickets?'+query.toString());
    if(request!==state.ticketRequest||!currentSession(version))return;
    if(state.page>result.pages){state.page=result.pages;return loadTickets();}
    state.pages=result.pages;
    state.tickets=result.tickets;
    $('#ticket-rows').innerHTML = state.tickets.length ? state.tickets.map(t=>rowMarkup(t)).join('') : '<tr><td colspan="6">No tickets match your filters.</td></tr>';
    $('#ticket-counter').textContent = `${result.total} request${result.total===1?'':'s'} · Page ${state.page} of ${state.pages}`;
    $('#previous-page').disabled=state.page<=1;$('#next-page').disabled=state.page>=state.pages;
    $('#export-button').href='/api/export.csv?'+exportQuery;
    const stats=await api('/api/stats');
    if(request===state.ticketRequest&&currentSession(version))$('#nav-ticket-count').textContent=String(stats.total);
  } catch(e) {if(currentSession(version)&&request===state.ticketRequest)toast('Could not load tickets: '+e.message);}
}

function activityMarkup(a) {
  const description = ({created:'created a new request',imported:'imported a request from CSV',updated_status:'updated a ticket status',updated_priority:'changed a priority',updated_assignee_id:'updated the assignee',commented:'added an internal note'})[a.action] || 'updated a request';
  return `<div class="activity-item"><span class="activity-bubble">${a.action==='created'?'＋':'↗'}</span><div><strong>${esc(a.actor)}</strong> <span>${esc(description)} on</span> <strong>${esc(a.code)}</strong><p>${esc(a.title)}</p><small>${esc(dateText(a.created_at))} · ${esc(a.detail)}</small></div></div>`;
}
async function loadActivity() {
  const version=state.sessionVersion, request=++state.activityRequest;
  try {
    const d=await api('/api/activity');
    if(!currentSession(version)||request!==state.activityRequest)return;
    $('#full-activity').innerHTML=d.items.map(activityMarkup).join('') || '<p>No activity yet.</p>';
  } catch(e) {if(currentSession(version)&&request===state.activityRequest)toast('Could not load audit history: '+e.message);}
}

function renderDiscussion(d) {
    $('#detail-comments').innerHTML=d.comments.length ? d.comments.map(c=>`<div class="comment"><strong>${esc(c.author)}</strong><small>${esc(dateText(c.created_at))}</small><p>${esc(c.body)}</p></div>`).join('') : '<p class="empty-comment">No notes yet. Add the first update.</p>';
    $('#detail-audit').innerHTML=d.audit.map(a=>`<div class="mini-event"><div><strong>${esc(a.actor)}</strong> · ${esc(a.detail)}<time>${esc(dateText(a.created_at))}</time></div></div>`).join('');
}

async function showTicket(id) {
  const version=state.sessionVersion, request=++state.detailRequest;
  try {
    const d=await api('/api/tickets/'+Number(id));
    if(!currentSession(version)||request!==state.detailRequest)return;
    state.selected=d.ticket;state.detailConflict=false;
    $('#reload-ticket').classList.add('hidden');$('#save-ticket').disabled=false;
    $('#comment-form button').disabled=false;
    $('#detail-code').textContent=d.ticket.code;
    $('#detail-title').textContent=d.ticket.title;
    $('#detail-description').textContent=d.ticket.description;
    $('#detail-chips').innerHTML=pill(d.ticket.priority)+' '+pill(d.ticket.status)+`<span class="pill medium">${esc(d.ticket.category)}</span>`;
    $('#detail-facts').innerHTML=`<div><strong>Requester</strong>${esc(d.ticket.requester)}</div><div><strong>Created</strong>${esc(dateText(d.ticket.created_at))}</div><div><strong>Due</strong>${esc(dateText(d.ticket.due_at))}</div>`;
    $('#detail-status').value=d.ticket.status;
    const allowed={open:['open','in_progress'],in_progress:['in_progress','open','resolved'],resolved:['resolved','open']}[d.ticket.status];
    Array.from($('#detail-status').options).forEach(option=>option.disabled=!allowed.includes(option.value));
    $('#workflow-hint').textContent={open:'Start investigation before resolving this request.',in_progress:'Resolve when verified, or return to the open queue.',resolved:'Reopen if the requester needs further help.'}[d.ticket.status];
    $('#detail-priority').value=d.ticket.priority;
    const sel=$('#detail-assignee');
    sel.innerHTML='<option value="">Unassigned</option>'+state.users.map(u=>`<option value="${u.id}">${esc(u.name)}</option>`).join('');
    sel.value=d.ticket.assignee_id == null ? '' : String(d.ticket.assignee_id);
    sel.disabled=state.user.role!=='admin';
    $('#detail-error').textContent='';
    $('#comment-text').value='';
    renderDiscussion(d);
    if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
  } catch(e) {if(currentSession(version)&&request===state.detailRequest)toast('Could not open ticket: '+e.message);}
}

async function saveTicket() {
  if(!state.selected||state.detailConflict)return;
  const t=state.selected, updated={}, version=state.sessionVersion, detailRequest=state.detailRequest;
  const stillEditing=()=>currentSession(version)&&state.selected?.id===t.id&&detailRequest===state.detailRequest;
  const status=$('#detail-status').value, priority=$('#detail-priority').value;
  const assign=$('#detail-assignee').value, newAssignee=assign?Number(assign):null;
  if(status!==t.status)updated.status=status;
  if(priority!==t.priority)updated.priority=priority;
  if(state.user.role==='admin'&&newAssignee!==t.assignee_id)updated.assignee_id=newAssignee;
  if(!Object.keys(updated).length){toast('No changes to save.');return;}
  const button=$('#save-ticket');button.disabled=true;
  try {
    await api(`/api/tickets/${t.id}`,{method:'PATCH',body:{...updated,expected_revision:t.revision}});
    if(!stillEditing())return;
    $('#detail-dialog').close();
    toast(`${t.code} updated.`);
    setView(state.view);
  } catch(e) {
    if(!stillEditing())return;
    $('#detail-error').textContent=e.message;
    if(e.code==='ticket_conflict'){
      state.detailConflict=true;
      $('#reload-ticket').classList.remove('hidden');
    }
  } finally {if(stillEditing())button.disabled=state.detailConflict;}
}

async function addComment(event) {
  event.preventDefault();
  if(!state.selected)return;
  const ticket=state.selected, version=state.sessionVersion, request=state.detailRequest;
  const stillEditing=()=>currentSession(version)&&state.selected?.id===ticket.id&&request===state.detailRequest;
  const body=$('#comment-text').value;
  const button=$('#comment-form button');button.disabled=true;
  try {
    await api(`/api/tickets/${ticket.id}/comments`,{method:'POST',body:{body}});
    if(!stillEditing())return;
    if($('#comment-text').value===body)$('#comment-text').value='';
    // Notes append independently. Refresh their history without replacing the
    // field draft, its revision, or an edit conflict discovered while posting.
    const discussion=await api(`/api/tickets/${ticket.id}`);
    if(!stillEditing())return;
    renderDiscussion(discussion);
    toast('Internal note added.');
    setView(state.view);
  } catch(e) {if(stillEditing())toast(e.message);}
  finally {if(stillEditing())button.disabled=false;}
}

async function createTicket(event) {
  event.preventDefault();
  const form=$('#create-form'), fields=Object.fromEntries(new FormData(form));
  const button=form.querySelector('button[type="submit"]');button.disabled=true;
  $('#create-error').textContent='';
  try {
    const d=await api('/api/tickets',{method:'POST',body:fields});
    $('#create-dialog').close();form.reset();toast(`${d.code} created successfully.`);
    state.page=1;setView('tickets');
  } catch(e) {$('#create-error').textContent=e.message;}
  finally {button.disabled=false;}
}

function invalidateImport() {
  state.importRevision++;
  state.importPreview=null;
  $('#import-commit').disabled=true;
  $('#import-preview').innerHTML='';
  $('#import-error').textContent='';
}

function resetImport() {
  invalidateImport();
  state.importBusy=false;
  $('#import-csv').value='';$('#import-file').value='';
  $('#import-csv').readOnly=false;$('#import-file').disabled=false;
  $('#import-preview-button').disabled=false;
}

function renderImportPreview(result) {
  const errors=result.errors.map(error=>`<li>Line ${Number(error.row)}, ${esc(error.field)}: ${esc(error.message)}</li>`).join('');
  const rows=result.rows.map(row=>`<tr><td>${Number(row.row)}</td><td>${esc(row.title||'')}</td><td>${esc(row.category)}</td><td>${esc(row.priority)}</td><td>${esc(row.requester||'')}</td></tr>`).join('');
  const summary=result.already_imported?'This batch was already imported. No additional tickets will be created.':result.errors.length?`${result.errors.length} validation error(s). Correct every error and preview again.`:`${result.row_count} ticket(s) ready. Importing creates all tickets together.`;
  $('#import-preview').innerHTML=`<p class="workflow-hint">${esc(summary)}</p>${errors?'<ul class="import-errors">'+errors+'</ul>':''}<div class="table-wrap"><table class="import-table"><caption>CSV preview</caption><thead><tr><th>LINE</th><th>TITLE</th><th>CATEGORY</th><th>PRIORITY</th><th>REQUESTER</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function loadImportFile(event) {
  invalidateImport();
  const file=event.target.files[0], version=state.sessionVersion, revision=state.importRevision;
  if(!file)return;
  if(file.size>24576){$('#import-error').textContent='Choose a UTF-8 CSV file of 24 KiB or less.';return;}
  try {
    const text=await file.text();
    if(!currentSession(version)||revision!==state.importRevision)return;
    $('#import-csv').value=text;
  } catch(_) {if(currentSession(version)&&revision===state.importRevision)$('#import-error').textContent='Could not read the file. Paste the CSV text instead.';}
}

async function previewImport(event) {
  event.preventDefault();
  if(state.user?.role!=='admin'||state.importBusy)return;
  invalidateImport();
  const version=state.sessionVersion, revision=state.importRevision, request=++state.importRequest;
  const text=$('#import-csv').value, button=$('#import-preview-button');button.disabled=true;
  try {
    const result=await api('/api/import/preview',{method:'POST',body:{csv_text:text}});
    if(!currentSession(version)||revision!==state.importRevision||request!==state.importRequest)return;
    state.importPreview=result.can_commit?{text,hash:result.content_hash}:null;
    renderImportPreview(result);
    $('#import-commit').disabled=!result.can_commit;
  } catch(error) {if(currentSession(version)&&revision===state.importRevision&&request===state.importRequest)$('#import-error').textContent=error.message;}
  finally {if(currentSession(version)&&request===state.importRequest)button.disabled=false;}
}

async function commitImport() {
  const preview=state.importPreview;
  if(state.user?.role!=='admin'||state.importBusy||!preview||preview.text!==$('#import-csv').value)return;
  const version=state.sessionVersion, revision=state.importRevision;
  state.importBusy=true;
  $('#import-commit').disabled=true;$('#import-preview-button').disabled=true;
  $('#import-csv').readOnly=true;$('#import-file').disabled=true;$('#import-error').textContent='';
  try {
    const result=await api('/api/import/commit',{method:'POST',body:{csv_text:preview.text,content_hash:preview.hash}});
    if(!currentSession(version)||revision!==state.importRevision)return;
    $('#import-dialog').close();resetImport();
    toast(result.duplicate?`Batch already imported. ${result.imported_count} existing ticket(s).`:`Imported ${result.imported_count} ticket(s).`);
    state.page=1;setView('tickets');
  } catch(error) {if(currentSession(version)&&revision===state.importRevision)$('#import-error').textContent=error.message+' You can retry this batch safely.';}
  finally {
    if(currentSession(version)&&revision===state.importRevision){
      state.importBusy=false;$('#import-csv').readOnly=false;$('#import-file').disabled=false;
      $('#import-preview-button').disabled=false;$('#import-commit').disabled=!state.importPreview;
    }
  }
}

async function login(event) {
  event.preventDefault();$('#login-error').textContent='';
  const button=$('#login-form button[type="submit"]');button.disabled=true;
  try {
    const data=await api('/api/login',{method:'POST',body:{username:$('#username').value,password:$('#password').value}});
    setAuthenticated(data);
    state.users=(await api('/api/users')).users;
    setView('overview');
  } catch(e) {$('#login-error').textContent=e.message;}
  finally {button.disabled=false;}
}

async function logout() {
  const version=state.sessionVersion;
  try {await api('/api/logout',{method:'POST',body:{}});if(currentSession(version))clearSession();}
  catch(error) {if(currentSession(version))toast('Sign out could not be confirmed. '+error.message);}
}

function ticketClick(event) {
  const node=event.target.closest('[data-ticket]');
  if(node&& (event.type==='click'||event.key==='Enter'||event.key===' ')){
    if(event.type==='keydown')event.preventDefault();
    showTicket(node.dataset.ticket);
  }
}

async function startup() {
  $('#login-form').addEventListener('submit', login);
  $('#logout-btn').addEventListener('click', logout);
  document.querySelectorAll('[data-view]').forEach(el=>el.addEventListener('click',()=>setView(el.dataset.view)));
  for(const [id,action] of [['banner-action','tickets'],['see-all-tickets','tickets']])$("#"+id).addEventListener('click',()=>setView(action));
  for(const id of ['new-ticket-overview','new-ticket-list'])$("#"+id).addEventListener('click',()=>$('#create-dialog').showModal());
  document.querySelectorAll('[data-close]').forEach(el=>el.addEventListener('click',()=>$('#'+el.dataset.close).close()));
  $('#create-form').addEventListener('submit',createTicket);
  $('#import-tickets').addEventListener('click',()=>{resetImport();$('#import-dialog').showModal();$('#import-csv').focus();});
  $('#import-form').addEventListener('submit',previewImport);
  $('#import-csv').addEventListener('input',invalidateImport);
  $('#import-file').addEventListener('change',loadImportFile);
  $('#import-commit').addEventListener('click',commitImport);
  $('#save-ticket').addEventListener('click',saveTicket);
  $('#reload-ticket').addEventListener('click',()=>{if(state.selected)showTicket(state.selected.id);});
  $('#comment-form').addEventListener('submit',addComment);
  $('#mobile-menu').addEventListener('click',()=>{
    const open=$('#sidebar').classList.toggle('open');updateNavigation();
    if(open)$('#sidebar [data-view]').focus();
  });
  window.matchMedia('(max-width:860px)').addEventListener('change',updateNavigation);
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&$('#sidebar').classList.contains('open')){
      $('#sidebar').classList.remove('open');updateNavigation();$('#mobile-menu').focus();
    }
  });
  updateNavigation();
  for(const id of ['overview-ticket-rows','ticket-rows','priority-tickets']){
    $("#"+id).addEventListener('click',ticketClick);$("#"+id).addEventListener('keydown',ticketClick);
  }
  $('#search-tickets').addEventListener('input',()=>{state.page=1;clearTimeout(state.searchTimer);state.searchTimer=setTimeout(loadTickets,220);});
  for(const id of ['filter-status','filter-priority'])$('#'+id).addEventListener('change',()=>{state.page=1;loadTickets();});
  $('#previous-page').addEventListener('click',()=>{if(state.page>1){state.page--;loadTickets();}});
  $('#next-page').addEventListener('click',()=>{if(state.page<state.pages){state.page++;loadTickets();}});
  try {
    const config=await api('/api/config');
    $('#demo-access').classList.toggle('hidden',!config.demo_access);
    if(config.demo_access){$('#username').value='admin';$('#password').value='demo1234';}
  } catch(error) {$('#login-error').textContent=error.message;}
  try {
    const data=await api('/api/session');
    setAuthenticated(data);
    state.users=(await api('/api/users')).users;
    setView('overview');
  } catch(_) {$('#login-screen').classList.remove('hidden');}
}

document.addEventListener('DOMContentLoaded',startup);

