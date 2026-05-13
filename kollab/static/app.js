'use strict';

// ------------------------------------------------------------------ tab state

// Tab: { id, sessionId, goal, state, turnsEl, scrollTop }
// state: 'active' | 'done' | 'halted' | 'readonly'
const tabs = [];
let activeTabId = null;
let waitingMsgEl = null;
let pendingCloseTabId = null;   // for confirm-close modal

// ------------------------------------------------------------------ DOM refs
const dialogue      = document.getElementById('dialogue');
const emptyState    = document.getElementById('empty-state');
const statusStrip   = document.getElementById('status-strip');
const userInput     = document.getElementById('user-input');
const btnSend       = document.getElementById('btn-send');
const btnStop       = document.getElementById('btn-stop');
const btnResume     = document.getElementById('btn-resume');
const inputTarget   = document.getElementById('input-target');
const tabBar        = document.getElementById('tab-bar');
const btnNewSession = document.getElementById('btn-new-session');
const historyPane   = document.getElementById('history-pane');
const historyList   = document.getElementById('history-list');

// ------------------------------------------------------------------ theme

const THEME_KEY = 'kollab_theme';

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('btn-theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '\uD83C\uDF19' : '\u2600';

  const isLight = theme === 'light';
  const styles = isLight ? {
    bg:        '#f4f4f6',
    panel:     '#ffffff',
    userPanel: '#ebebee',
    text:      '#1a1a1e',
    muted:     '#606060',
    border:    'rgba(0,0,0,0.10)',
    claudeTint:'#fff3e8',
    codexTint: '#e8f0fb',
  } : {
    bg:        '#0e0e10',
    panel:     '#17171a',
    userPanel: '#202024',
    text:      '#e5e5e5',
    muted:     '#888888',
    border:    'rgba(255,255,255,0.10)',
    claudeTint:'#3a2310',
    codexTint: '#162536',
  };

  document.body.style.backgroundColor = styles.bg;
  document.body.style.color = styles.text;

  const overrides = [
    ['.bg-bg',        'backgroundColor', styles.bg],
    ['.bg-panel',     'backgroundColor', styles.panel],
    ['.bg-userPanel', 'backgroundColor', styles.userPanel],
    ['.bg-claudeTint','backgroundColor', styles.claudeTint],
    ['.bg-codexTint', 'backgroundColor', styles.codexTint],
    ['.text-user',    'color',           styles.text],
    ['.text-muted',   'color',           styles.muted],
  ];
  for (const [sel, prop, val] of overrides) {
    document.querySelectorAll(sel).forEach(el => { el.style[prop] = val; });
  }
  document.querySelectorAll('.border-white\\/10, .border-white\\/20').forEach(el => {
    el.style.borderColor = styles.border;
  });

  window.__kollabThemeStyles = styles;
}

function applyThemeToEl(el) {
  const styles = window.__kollabThemeStyles;
  if (!styles) return;
  const overrides = [
    ['.bg-bg',        'backgroundColor', styles.bg],
    ['.bg-panel',     'backgroundColor', styles.panel],
    ['.bg-userPanel', 'backgroundColor', styles.userPanel],
    ['.bg-claudeTint','backgroundColor', styles.claudeTint],
    ['.bg-codexTint', 'backgroundColor', styles.codexTint],
    ['.text-user',    'color',           styles.text],
    ['.text-muted',   'color',           styles.muted],
  ];
  for (const [sel, prop, val] of overrides) {
    el.querySelectorAll(sel).forEach(e => { e.style[prop] = val; });
    if (el.matches && el.matches(sel)) el.style[prop] = val;
  }
  el.querySelectorAll('.border-white\\/10, .border-white\\/20').forEach(e => {
    e.style.borderColor = styles.border;
  });
  if (el.matches && (el.matches('.border-white\\/10') || el.matches('.border-white\\/20'))) {
    el.style.borderColor = styles.border;
  }
}

document.getElementById('btn-about').addEventListener('click', () => {
  window.open('/about', 'kollab-about');
});

document.getElementById('btn-theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  localStorage.setItem(THEME_KEY, next);
  fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ theme: next }) });
});

(async () => {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored) {
    applyTheme(stored);
  } else {
    try {
      const r = await fetch('/api/config');
      if (r.ok) { const c = await r.json(); applyTheme(c.theme || 'dark'); }
    } catch (_) { applyTheme('dark'); }
  }
})();

// ------------------------------------------------------------------ history pane collapse

const HISTORY_KEY = 'kollab_history_collapsed';

function applyHistoryCollapse(collapsed) {
  historyPane.style.width = collapsed ? '0px' : '240px';
  historyPane.style.overflow = 'hidden';
}

document.getElementById('btn-history-toggle').addEventListener('click', () => {
  const collapsed = historyPane.style.width === '0px';
  applyHistoryCollapse(!collapsed);
  localStorage.setItem(HISTORY_KEY, (!collapsed).toString());
});

const _historySaved = localStorage.getItem(HISTORY_KEY);
applyHistoryCollapse(_historySaved === null ? true : _historySaved === 'true');

// ------------------------------------------------------------------ tab persistence

const TABS_KEY = 'kollab_open_tabs';

function saveOpenTabs() {
  const persistable = tabs
    .filter(t => t.sessionId && t.state !== 'active')
    .map(t => ({ sessionId: t.sessionId, goal: t.goal, state: t.state }));
  localStorage.setItem(TABS_KEY, JSON.stringify(persistable));
}

async function restoreOpenTabs() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(TABS_KEY) || '[]'); } catch (_) { return; }
  if (!saved.length) return;
  for (const entry of saved) {
    try {
      const res = await fetch(`/api/sessions/${entry.sessionId}`);
      if (!res.ok) continue;
      const data = await res.json();
      const tab = createTab(entry.goal || entry.sessionId, entry.sessionId, 'readonly');
      // Write directly into tab._nodes — do NOT touch the live dialogue DOM.
      // appendToActiveTab() would clobber whatever is currently displayed.
      reconstructSessionIntoTab(tab, data.events);
      tab.scrollTop = 0;
    } catch (_) { /* skip broken entries */ }
  }
  if (tabs.length > 0 && !activeTabId) {
    switchTab(tabs[tabs.length - 1].id);
  }
  renderTabBar();
}

function makeTabId() {
  return 'tab_' + Math.random().toString(36).slice(2, 10);
}

function getTab(tabId) {
  return tabs.find(t => t.id === tabId) || null;
}

function getTabBySessionId(sessionId) {
  return tabs.find(t => t.sessionId === sessionId) || null;
}

function createTab(goal, sessionId, state) {
  const tab = {
    id: makeTabId(),
    sessionId: sessionId || null,
    goal: goal || '',
    state: state || 'active',
    turnsEl: document.createDocumentFragment(),
    scrollTop: 0,
    _nodes: [],
  };
  tabs.push(tab);
  renderTabBar();
  return tab;
}

function closeTab(tabId) {
  const idx = tabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;
  tabs.splice(idx, 1);
  if (activeTabId === tabId) {
    activeTabId = null;
    const next = tabs[Math.min(idx, tabs.length - 1)];
    if (next) switchTab(next.id);
    else showEmptyState();
  }
  renderTabBar();
  saveOpenTabs();
}

function switchTab(tabId) {
  if (activeTabId) {
    const outgoing = getTab(activeTabId);
    if (outgoing) outgoing.scrollTop = dialogue.scrollTop;
  }

  activeTabId = tabId;
  const tab = getTab(tabId);
  if (!tab) return;

  dialogue.innerHTML = '';
  for (const node of tab._nodes) {
    dialogue.appendChild(node);
  }
  dialogue.scrollTop = tab.scrollTop;
  stickyBottom = true;

  renderTabBar();
  updateInputStrip(tab);
}

function showEmptyState() {
  activeTabId = null;
  dialogue.innerHTML = '';
  const p = document.createElement('p');
  p.id = 'empty-state';
  p.className = 'text-muted text-center mt-16';
  p.textContent = 'Start a new session to begin the dialogue.';
  dialogue.appendChild(p);
  statusStrip.textContent = 'idle';
  updateInputStrip(null);
  renderTabBar();
}

function activeTab() {
  return activeTabId ? getTab(activeTabId) : null;
}

// ------------------------------------------------------------------ tab bar rendering

function renderTabBar() {
  const oldTabs = tabBar.querySelectorAll('.kollab-tab');
  oldTabs.forEach(el => el.remove());

  const countEl = document.getElementById('tab-count');
  if (countEl) countEl.textContent = tabs.length > 0 ? `${tabs.length}` : '';

  for (const tab of tabs) {
    const label = (tab.state === 'readonly' ? '[readonly] ' : '')
      + (tab.goal ? tab.goal.slice(0, 40) + (tab.goal.length > 40 ? '\u2026' : '') : 'New session');

    const el = document.createElement('div');
    el.className = 'kollab-tab flex items-center gap-1 px-3 py-2 text-xs cursor-pointer border-r border-white/10 whitespace-nowrap shrink-0 transition '
      + (tab.id === activeTabId
        ? 'text-user border-b-2 border-b-claude bg-claudeTint/20'
        : 'text-muted hover:text-user');
    el.dataset.tabId = tab.id;

    const labelSpan = document.createElement('span');
    labelSpan.textContent = label;
    labelSpan.addEventListener('click', () => switchTab(tab.id));

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '\u00d7';
    closeBtn.className = 'ml-1 text-base leading-none opacity-50 hover:opacity-100 transition px-0.5';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      handleTabClose(tab.id);
    });

    el.appendChild(labelSpan);
    el.appendChild(closeBtn);
    tabBar.appendChild(el);
  }
}

function handleTabClose(tabId) {
  const tab = getTab(tabId);
  if (!tab) return;
  if (tab.state === 'active') {
    pendingCloseTabId = tabId;
    document.getElementById('modal-confirm-close').classList.remove('hidden');
  } else {
    closeTab(tabId);
  }
}

document.getElementById('btn-confirm-close-no').addEventListener('click', () => {
  pendingCloseTabId = null;
  document.getElementById('modal-confirm-close').classList.add('hidden');
});

document.getElementById('btn-confirm-close-yes').addEventListener('click', async () => {
  document.getElementById('modal-confirm-close').classList.add('hidden');
  if (pendingCloseTabId) {
    await fetch('/api/session/stop', { method: 'POST' });
    closeTab(pendingCloseTabId);
    pendingCloseTabId = null;
  }
});

// ------------------------------------------------------------------ input strip

function updateInputStrip(tab) {
  const isHalted   = tab && tab.state === 'halted';
  const isReadonly = !tab || tab.state === 'readonly' || tab.state === 'done';

  inputTarget.disabled = !isHalted;
  if (!isHalted) inputTarget.value = '';

  const targetSelected = isHalted && inputTarget.value !== '';
  userInput.disabled = !targetSelected;
  btnSend.disabled = !targetSelected;
  userInput.placeholder = isHalted
    ? (targetSelected ? 'Type your instruction\u2026' : 'Select a target first\u2026')
    : 'Session not halted';

  if (isReadonly) {
    btnStop.classList.add('hidden');
    btnResume.classList.add('hidden');
  }
}

inputTarget.addEventListener('change', () => {
  const tab = activeTab();
  updateInputStrip(tab);
  if (inputTarget.value) userInput.focus();
});

// ------------------------------------------------------------------ append helpers

function appendToActiveTab(node) {
  const tab = activeTab();
  if (!tab) return;
  applyThemeToEl(node);
  tab._nodes.push(node);
  dialogue.appendChild(node);
  scrollIfSticky();
}

// Append directly into tab._nodes without touching live DOM.
// Used when reconstructing a non-active tab (e.g. restoreOpenTabs).
function appendNodeToTab(tab, node) {
  applyThemeToEl(node);
  tab._nodes.push(node);
}

// ------------------------------------------------------------------ WebSocket

let ws = null;
let stickyBottom = true;
let wsReconnectAttempts = 0;

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = e => handleEvent(JSON.parse(e.data));
  ws.onopen = () => onServerOnline();
  ws.onclose = () => {
    if (wsReconnectAttempts === 0) onServerGone();
    wsReconnectAttempts++;
  };
}

function onServerOnline() {
  wsReconnectAttempts = 0;
  document.getElementById('btn-shutdown').disabled = false;
  document.getElementById('btn-shutdown').classList.remove('opacity-40');
}

function onServerGone() {
  document.getElementById('btn-shutdown').disabled = true;
  document.getElementById('btn-shutdown').classList.add('opacity-40');
  document.getElementById('modal-shutdown').classList.add('hidden');
  const msg = document.getElementById('shutdown-msg');
  msg.textContent = 'koll\u2660b has shut down.';
  const noBtn = document.getElementById('btn-shutdown-no');
  noBtn.classList.add('hidden');
  const yesBtn = document.getElementById('btn-shutdown-yes');
  yesBtn.textContent = 'Close tab';
  yesBtn.disabled = false;
  yesBtn.onclick = () => window.close();
  document.getElementById('modal-shutdown').classList.remove('hidden');
}

// ------------------------------------------------------------------ event dispatch

function handleEvent(msg) {
  switch (msg.type) {
    case 'turn_start':   onTurnStart(msg);   break;
    case 'turn_chunk':   onTurnChunk(msg);   break;
    case 'turn_end':     onTurnEnd(msg);     break;
    case 'turn_cancel':  onTurnCancel(msg);  break;
    case 'state':        onState(msg);       break;
    case 'session_done': onSessionDone(msg); break;
    case 'error':        onError(msg);       break;
  }
}

// ------------------------------------------------------------------ turn card

let currentTurnId = null;
let isStreaming = false;

function buildCollapseToggle() {
  let allCollapsed = false;
  const bar = document.createElement('div');
  bar.className = 'flex justify-start';
  const btn = document.createElement('button');
  btn.className = 'text-xs text-muted opacity-40 hover:opacity-80 transition';
  btn.textContent = '− collapse all';
  btn.addEventListener('click', () => {
    allCollapsed = !allCollapsed;
    btn.textContent = allCollapsed ? '+ expand all' : '− collapse all';
    // toggle all collapsible bodies in the active dialogue
    dialogue.querySelectorAll('[id^="collapsible-body-"]').forEach(body => {
      body.style.display = allCollapsed ? 'none' : '';
    });
    // sync chevrons
    dialogue.querySelectorAll('[id^="collapse-"]').forEach(chevron => {
      if (!chevron.disabled) {
        chevron.style.transform = allCollapsed ? 'rotate(90deg)' : '';
        chevron.title = allCollapsed ? 'Expand' : 'Collapse';
      }
    });
  });
  bar.appendChild(btn);
  return bar;
}

function buildTurnCard(msg) {
  const isClaude     = msg.actor === 'claude';
  const accentBg     = isClaude ? 'bg-claudeTint' : 'bg-codexTint';
  const accentBorder = isClaude ? 'border-claude'  : 'border-codex';
  const accentText   = isClaude ? 'text-claude'    : 'text-codex';
  const roleLabel    = msg.role;

  const card = document.createElement('div');
  card.id = `turn-${msg.turn_id}`;
  card.className = `rounded-lg border ${accentBorder} ${accentBg} p-3 flex flex-col gap-2`;
  card.innerHTML = `
    <div class="flex items-center gap-2 text-xs">
      <button id="collapse-${msg.turn_id}" class="text-muted text-base opacity-30 cursor-not-allowed transition-transform select-none" title="Collapse" disabled>&#8250;</button>
      <span class="font-bold ${accentText} uppercase">${msg.actor}</span>
      <span class="text-muted">${roleLabel}</span>
      <span id="badge-${msg.turn_id}" class="ml-auto font-mono text-muted">${msg.turn_id}</span>
      <span id="verdict-${msg.turn_id}" ${msg.turn_id === 'C-1' ? 'class="text-xs px-1.5 py-0.5 rounded font-bold text-muted bg-white/10"' : ''}>${msg.turn_id === 'C-1' ? 'PROPOSAL' : ''}</span>
    </div>
    <div id="collapsible-body-${msg.turn_id}" class="flex flex-col gap-2">
      <details id="reasoning-${msg.turn_id}" class="text-muted text-xs hidden">
        <summary class="cursor-pointer hover:text-user select-none">Reasoning</summary>
        <pre id="reasoning-body-${msg.turn_id}" class="whitespace-pre-wrap mt-1 pl-2"></pre>
      </details>
      <details id="result-${msg.turn_id}" open>
        <summary class="cursor-pointer hover:text-user text-xs text-muted select-none">Result</summary>
        <pre id="body-${msg.turn_id}" class="whitespace-pre-wrap text-user thinking mt-1">\u2026</pre>
      </details>
    </div>
  `;
  return card;
}

function applyVerdict(turnId, verdict, root) {
  if (turnId === 'C-1') return;  // C-1 is always PROPOSAL, never a verdict
  const el = root ? root.querySelector(`#verdict-${turnId}`) : document.getElementById(`verdict-${turnId}`);
  if (el && verdict) {
    const colors = {
      AGREE:    'text-verdictAgree bg-verdictAgree/20',
      DISAGREE: 'text-verdictDisagree bg-verdictDisagree/20',
      REVISED:  'text-verdictRevised bg-verdictRevised/20',
    };
    el.className = `text-xs px-1.5 py-0.5 rounded font-bold ${colors[verdict] || ''}`;
    el.textContent = verdict;
  }
}

function removeWaitingMsg() {
  if (waitingMsgEl) { waitingMsgEl.remove(); waitingMsgEl = null; }
}

function enableCollapseChevron(turnId, root) {
  const btn = root ? root.querySelector(`#collapse-${turnId}`) : document.getElementById(`collapse-${turnId}`);
  if (!btn || !btn.disabled) return;  // already enabled
  btn.disabled = false;
  btn.classList.remove('opacity-30', 'cursor-not-allowed');
  btn.classList.add('opacity-60', 'hover:opacity-100', 'cursor-pointer');
  btn.style.transition = 'transform 0.2s';
  let collapsed = false;
  btn.addEventListener('click', () => {
    collapsed = !collapsed;
    const body = document.getElementById(`collapsible-body-${turnId}`);
    if (body) body.style.display = collapsed ? 'none' : '';
    btn.style.transform = collapsed ? 'rotate(90deg)' : '';
    btn.title = collapsed ? 'Expand' : 'Collapse';
  });
}

function onTurnCancel(msg) {
  // Mid-stream halt: leave the card as a permanent observable artifact.
  // Per spec, the agent will NOT pick up where it left off — the next turn
  // (e.g. C-2 after an interrupted C-1) is a fresh response with the
  // directive applied. The partial reasoning/output here is for the
  // viewer's benefit only.
  const body = document.getElementById(`body-${msg.turn_id}`);
  if (body) body.classList.remove('thinking');
  const card = document.getElementById(`turn-${msg.turn_id}`);
  if (card) {
    const note = document.createElement('div');
    note.className = 'text-xs text-muted border-t border-white/10 pt-2 mt-1';
    note.textContent = '\u23f8 interrupted';
    card.appendChild(note);
  }
  isStreaming = false;
  currentTurnId = null;
}

function onTurnStart(msg) {
  removeWaitingMsg();
  currentTurnId = msg.turn_id;
  isStreaming = true;
  appendToActiveTab(buildTurnCard(msg));
}

function onTurnChunk(msg) {
  if (msg.turn_id !== currentTurnId) return;
  if (msg.kind === 'text') {
    const body = document.getElementById(`body-${msg.turn_id}`);
    if (body) {
      if (body.classList.contains('thinking')) {
        body.classList.remove('thinking');
        body.textContent = '';
      }
      body.textContent += msg.content;
    }
  } else if (msg.kind === 'reasoning') {
    const details = document.getElementById(`reasoning-${msg.turn_id}`);
    const pre = document.getElementById(`reasoning-body-${msg.turn_id}`);
    if (details && pre) {
      details.classList.remove('hidden');
      details.open = true;
      pre.textContent += msg.content;
    }
  }
  scrollIfSticky();
}

function onTurnEnd(msg) {
  applyVerdict(msg.turn_id, msg.verdict);
  if (msg.thread_id) {
    const badge = document.getElementById(`badge-${msg.turn_id}`);
    if (badge) {
      const short = msg.thread_id.length > 14 ? msg.thread_id.slice(0, 14) + '\u2026' : msg.thread_id;
      badge.textContent = `${msg.turn_id} \u00b7 ${short}`;
      badge.title = msg.thread_id;
    }
  }
  const body = document.getElementById(`body-${msg.turn_id}`);
  if (body) body.classList.remove('thinking');
  enableCollapseChevron(msg.turn_id);
  isStreaming = false;
  currentTurnId = null;
  scrollIfSticky();
}

// ------------------------------------------------------------------ state

function onState(msg) {
  const stateLabels = {
    idle:          'idle',
    fanning_out:   'sending goal to both agents\u2026',
    claude_turn:   `claude thinking\u2026 \u00b7 round ${msg.round}`,
    codex_turn:    `codex thinking\u2026 \u00b7 round ${msg.round}`,
    awaiting_user: 'awaiting input',
    halted:        'halted \u2014 click Resume to continue',
    done:          'session complete',
  };
  statusStrip.textContent = stateLabels[msg.state] || msg.state;

  const sessionRunning = ['claude_turn', 'codex_turn', 'fanning_out'].includes(msg.state);
  btnStop.classList.toggle('hidden', !sessionRunning);
  if (sessionRunning) {
    btnStop.disabled = false;
    btnStop.textContent = 'Stop';
    btnStop.classList.remove('opacity-50');
  }
  btnResume.classList.toggle('hidden', msg.state !== 'halted');

  const tab = activeTab();
  if (tab) {
    if (msg.state === 'halted') tab.state = 'halted';
    else if (msg.state === 'done') tab.state = 'done';
    else if (sessionRunning) tab.state = 'active';
    updateInputStrip(tab);
  }
}

function onSessionDone(msg) {
  const reasons = {
    convergence: '\u2713 Both agents reached agreement.',
    round_limit: '\u26a0 Round limit reached.',
    token_limit: '\u26a0 Token budget exhausted.',
    halted:      '\u23f9 Session halted.',
    expired:     '\u23f3 Stopped / expired.',
  };
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted';
  banner.textContent = reasons[msg.reason] || `Session ended: ${msg.reason}`;
  appendToActiveTab(banner);

  const tab = activeTab();
  if (tab) tab.state = 'done';

  btnStop.classList.add('hidden');
  statusStrip.textContent = `done \u2014 ${msg.reason}`;
  updateInputStrip(tab);
  renderTabBar();
  scrollIfSticky();
  saveOpenTabs();
  loadHistory();
}

function onError(msg) {
  removeWaitingMsg();
  const banner = document.createElement('div');
  banner.className = 'rounded-lg border border-verdictDisagree/50 bg-verdictDisagree/10 px-4 py-3 text-verdictDisagree';
  banner.textContent = `Error: ${msg.message}`;
  appendToActiveTab(banner);
  scrollIfSticky();
}

// ------------------------------------------------------------------ buttons

btnSend.addEventListener('click', sendInput);
userInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) sendInput(); });

btnStop.addEventListener('click', async () => {
  btnStop.disabled = true;
  btnStop.textContent = 'Stopping\u2026';
  btnStop.classList.add('opacity-50');
  const res = await fetch('/api/session/stop', { method: 'POST' });
  if (!res.ok) {
    btnStop.disabled = false;
    btnStop.textContent = 'Stop';
    btnStop.classList.remove('opacity-50');
  }
});

btnResume.addEventListener('click', () => {
  if (inputTarget.value && userInput.value.trim()) {
    showUnsentToast();
    return;
  }
  doResume();
});

function doResume() {
  fetch('/api/session/resume', { method: 'POST' });
  btnResume.classList.add('hidden');
  const tab = activeTab();
  if (tab) { tab.state = 'active'; updateInputStrip(tab); }
}

function showUnsentToast() {
  document.getElementById('unsent-toast')?.remove();
  const toast = document.createElement('div');
  toast.id = 'unsent-toast';
  toast.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 bg-panel border border-white/20 rounded px-4 py-2 text-xs text-muted z-50 flex items-center gap-3';
  toast.innerHTML = `
    <span>Instruction not sent.</span>
    <button id="toast-send-resume" class="text-verdictAgree hover:underline">Send &amp; Resume</button>
    <button id="toast-resume-anyway" class="text-muted hover:underline">Resume anyway</button>
  `;
  document.body.appendChild(toast);
  toast.querySelector('#toast-send-resume').addEventListener('click', async () => {
    toast.remove();
    await sendInput();
    doResume();
  });
  toast.querySelector('#toast-resume-anyway').addEventListener('click', () => {
    toast.remove();
    userInput.value = '';
    doResume();
  });
  setTimeout(() => toast?.remove(), 8000);
}

async function sendInput() {
  const text = userInput.value.trim();
  if (!text) return;
  const target = inputTarget.value || 'both';
  const ref = text.match(/\b([CX]-\d+)\b/);
  if (ref) highlightCard(ref[1]);

  const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
  const card = document.createElement('div');
  card.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
  card.innerHTML = `
    <div class="text-xs text-muted uppercase">DIRECTIVE \u2192 ${targetLabels[target] || target.toUpperCase()}</div>
    <pre class="whitespace-pre-wrap text-user">${escHtml(text)}</pre>
  `;
  appendToActiveTab(card);

  await fetch('/api/session/input', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, target }),
  });
  userInput.value = '';
}

function highlightCard(turnId) {
  const card = document.getElementById(`turn-${turnId}`);
  if (!card) return;
  card.style.transition = 'box-shadow 0.2s';
  card.style.boxShadow = '0 0 0 2px #cc6600';
  setTimeout(() => { card.style.boxShadow = ''; }, 1200);
}

// ------------------------------------------------------------------ Esc to close modals

const MODAL_ESC_MAP = [
  { modalId: 'modal-new-session',    cancelId: 'btn-modal-cancel' },
  { modalId: 'modal-configure',      cancelId: 'btn-config-cancel' },
  { modalId: 'modal-shutdown',       cancelId: 'btn-shutdown-no' },
  { modalId: 'modal-confirm-close',  cancelId: 'btn-confirm-close-no' },
  { modalId: 'modal-confirm-delete', cancelId: 'btn-confirm-delete-no' },
];

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  for (const { modalId, cancelId } of MODAL_ESC_MAP) {
    const modal = document.getElementById(modalId);
    if (modal && !modal.classList.contains('hidden')) {
      document.getElementById(cancelId)?.click();
      break;
    }
  }
});

// ------------------------------------------------------------------ new session modal

const MODEL_MATRIX = {
  claude: [
    { label: 'haiku',  model: 'claude-haiku-4-5-20251001', tier: 'fast'     },
    { label: 'sonnet', model: 'claude-sonnet-4-6',          tier: 'gp'       },
    { label: 'opus',   model: 'claude-opus-4-7',            tier: 'high-end' },
  ],
  codex: [
    { label: 'mini',    model: 'gpt-5.4-mini', tier: 'fast' },
    { label: 'gpt-5.4', model: 'gpt-5.4',      tier: 'gp'   },
  ],
};

function populateSelect(selectEl, agentKey, currentValue) {
  selectEl.innerHTML = '';
  for (const m of MODEL_MATRIX[agentKey]) {
    const opt = document.createElement('option');
    opt.value = m.model;
    opt.textContent = `${m.label} (${m.model})`;
    if (m.model === currentValue) opt.selected = true;
    selectEl.appendChild(opt);
  }
}

document.getElementById('btn-close-all-tabs').addEventListener('click', () => {
  const toClose = tabs.filter(t => t.state !== 'active').map(t => t.id);
  for (const id of toClose) closeTab(id);
});

btnNewSession.addEventListener('click', async () => {
  const runningTab = tabs.find(t => t.state === 'active');
  if (runningTab) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 bg-panel border border-white/20 rounded px-4 py-2 text-xs text-muted z-50';
    toast.textContent = 'A session is already running. Stop it or wait for it to finish.';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
    return;
  }

  let cfg = {};
  try {
    const res = await fetch('/api/config');
    if (res.ok) cfg = await res.json();
  } catch (_) {}

  populateSelect(document.getElementById('override-claude-model'), 'claude', cfg.claude_model || MODEL_MATRIX.claude[1].model);
  populateSelect(document.getElementById('override-codex-model'),  'codex',  cfg.codex_model  || MODEL_MATRIX.codex[1].model);

  const roundInput = document.getElementById('override-round-limit');
  roundInput.placeholder = `default (${cfg.round_limit ?? 8})`;
  roundInput.value = '';

  document.getElementById('override-tokens-turn').value = '';
  document.getElementById('override-tokens-session').value = '';

  document.getElementById('modal-new-session').classList.remove('hidden');
  document.getElementById('goal-input').focus();
});

document.getElementById('btn-modal-cancel').addEventListener('click', () => {
  document.getElementById('modal-new-session').classList.add('hidden');
});

document.getElementById('btn-modal-start').addEventListener('click', async () => {
  const goal = document.getElementById('goal-input').value.trim();
  if (!goal) return;

  let cfg = {};
  try { const r = await fetch('/api/config'); if (r.ok) cfg = await r.json(); } catch (_) {}

  const body = { goal };

  const claudeModel = document.getElementById('override-claude-model').value;
  if (claudeModel && claudeModel !== cfg.claude_model) body.claude_model = claudeModel;

  const codexModel = document.getElementById('override-codex-model').value;
  if (codexModel && codexModel !== cfg.codex_model) body.codex_model = codexModel;

  const roundVal = parseInt(document.getElementById('override-round-limit').value, 10);
  if (!isNaN(roundVal) && roundVal > 0 && roundVal !== cfg.round_limit) body.round_limit = roundVal;

  const tokensTurn = parseInt(document.getElementById('override-tokens-turn').value, 10);
  if (!isNaN(tokensTurn) && tokensTurn > 0) body.max_tokens_per_turn = tokensTurn;

  const tokensSession = parseInt(document.getElementById('override-tokens-session').value, 10);
  if (!isNaN(tokensSession) && tokensSession > 0) body.max_tokens_per_session = tokensSession;

  document.getElementById('modal-new-session').classList.add('hidden');
  document.getElementById('goal-input').value = '';

  const tab = createTab(goal, null, 'active');
  switchTab(tab.id);

  const goalCard = document.createElement('div');
  goalCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
  goalCard.innerHTML = `
    <div class="text-xs text-muted uppercase">goal</div>
    <pre class="whitespace-pre-wrap text-user">${escHtml(goal)}</pre>
  `;
  appendToActiveTab(goalCard);
  appendToActiveTab(buildCollapseToggle());

  waitingMsgEl = document.createElement('p');
  waitingMsgEl.className = 'text-muted text-center mt-16';
  waitingMsgEl.textContent = 'Waiting for Claude to respond\u2026';
  appendToActiveTab(waitingMsgEl);

  const res = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const data = await res.json();
    tab.sessionId = data.session_id;
  } else if (res.status === 409) {
    removeWaitingMsg();
    closeTab(tab.id);
  } else {
    removeWaitingMsg();
    onError({ message: `Failed to start session (${res.status})` });
  }
});

document.getElementById('btn-shutdown').addEventListener('click', () => {
  const running = tabs.find(t => t.state === 'active');
  const msg = document.getElementById('shutdown-msg');
  msg.textContent = running
    ? 'A session is in progress. Quit anyway? It will be stopped.'
    : 'Quit koll\u2660b?';
  document.getElementById('modal-shutdown').classList.remove('hidden');
});

document.getElementById('btn-shutdown-no').addEventListener('click', () => {
  document.getElementById('modal-shutdown').classList.add('hidden');
});

document.getElementById('btn-shutdown-yes').addEventListener('click', async () => {
  document.getElementById('btn-shutdown-yes').disabled = true;
  document.getElementById('btn-shutdown-yes').textContent = 'Quitting\u2026';
  await fetch('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<p style="color:#888;font-family:monospace;padding:2rem">koll\u2660b has shut down. You can close this tab.</p>';
});

// ------------------------------------------------------------------ configure modal

const configFields = [
  { key: 'claude_binary',          label: 'Claude binary path' },
  { key: 'claude_model',           label: 'Claude model',  type: 'select', agentKey: 'claude' },
  { key: 'claude_workdir',         label: 'Claude working dir' },
  { key: 'codex_binary',           label: 'Codex binary path' },
  { key: 'codex_model',            label: 'Codex model',   type: 'select', agentKey: 'codex' },
  { key: 'codex_workdir',          label: 'Codex working dir' },
  { key: 'round_limit',            label: 'Round limit',   type: 'number' },
  { key: 'halt_timeout_secs',      label: 'Halt timeout (seconds, 0 = never)', type: 'number' },
  { key: 'port',                   label: 'Port',          type: 'number' },
  { key: 'sessions_dir',           label: 'Sessions dir' },
  { key: '_mcp_sep',               label: 'MCP Tools',     type: 'section' },
  { key: 'mcp_filesystem_enabled', label: 'Filesystem MCP enabled', type: 'checkbox' },
  { key: 'mcp_filesystem_paths',   label: 'Filesystem allowed paths (one per line)', type: 'textarea' },
  { key: '_github_coming_soon',    label: 'GitHub MCP — coming soon', type: 'section' },
];

document.getElementById('btn-configure').addEventListener('click', async () => {
  const res = await fetch('/api/config');
  const cfg = await res.json();
  const form = document.getElementById('config-form');
  form.innerHTML = '';
  form.className = 'grid grid-cols-2 gap-x-4 gap-y-3';
  for (const f of configFields) {
    if (f.type === 'section') {
      const sep = document.createElement('div');
      sep.className = 'col-span-2 border-t border-white/10 pt-3 mt-1';
      sep.innerHTML = `<p class="text-xs text-muted uppercase tracking-wider">${f.label}</p>`;
      form.appendChild(sep);
      continue;
    }
    const label = document.createElement('label');
    label.className = 'flex flex-col gap-1 text-xs text-muted';
    label.textContent = f.label;
    let input;
    if (f.type === 'select') {
      input = document.createElement('select');
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      for (const m of MODEL_MATRIX[f.agentKey]) {
        const o = document.createElement('option');
        o.value = m.model;
        o.textContent = `${m.label} (${m.model})`;
        if (cfg[f.key] === m.model) o.selected = true;
        input.appendChild(o);
      }
    } else if (f.type === 'checkbox') {
      const wrapper = document.createElement('div');
      wrapper.className = 'flex items-center gap-2 mt-1';
      input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'w-4 h-4 accent-claude';
      input.checked = !!cfg[f.key];
      wrapper.appendChild(input);
      input.name = f.key;
      label.appendChild(wrapper);
      form.appendChild(label);
      continue;
    } else if (f.type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = 3;
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none font-mono text-xs';
      input.value = Array.isArray(cfg[f.key]) ? cfg[f.key].join('\n') : (cfg[f.key] || '');
      input.placeholder = 'Leave empty to use agent workdir';
      label.className += ' col-span-2';
    } else if (f.type === 'password') {
      input = document.createElement('input');
      input.type = 'password';
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      input.value = cfg[f.key] ?? '';
      input.placeholder = 'GitHub personal access token';
    } else {
      input = document.createElement('input');
      input.type = f.type || 'text';
      input.className = 'bg-userPanel border border-white/20 rounded px-2 py-1 text-user focus:outline-none';
      input.value = cfg[f.key] ?? '';
    }
    input.name = f.key;
    label.appendChild(input);
    form.appendChild(label);
  }
  document.getElementById('modal-configure').classList.remove('hidden');
});

document.getElementById('btn-config-cancel').addEventListener('click', () => {
  document.getElementById('modal-configure').classList.add('hidden');
});

document.getElementById('btn-config-save').addEventListener('click', async () => {
  const form = document.getElementById('config-form');
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') {
      data[el.name] = el.checked;
    } else if (el.tagName === 'TEXTAREA' && el.name === 'mcp_filesystem_paths') {
      data[el.name] = el.value.split('\n').map(s => s.trim()).filter(Boolean);
    } else if (el.type === 'number') {
      data[el.name] = Number(el.value);
    } else {
      data[el.name] = el.value;
    }
  }
  const res = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const result = await res.json();
  const errEl = document.getElementById('config-errors');
  if (result.ok) {
    document.getElementById('modal-configure').classList.add('hidden');
    errEl.classList.add('hidden');
  } else {
    errEl.textContent = result.errors.join(' \u00b7 ');
    errEl.classList.remove('hidden');
  }
});

// ------------------------------------------------------------------ history pane

let _historyFilter = null;
let _pendingDeleteId = null;
let _allSessions = [];

document.querySelectorAll('.history-filter').forEach(btn => {
  btn.addEventListener('click', () => {
    const f = btn.dataset.filter;
    _historyFilter = _historyFilter === f ? null : f;
    document.querySelectorAll('.history-filter').forEach(b => {
      const active = b.dataset.filter === _historyFilter;
      b.style.opacity = active ? '1' : '0.30';
      b.style.outline = active ? '1.5px solid rgba(255,255,255,0.4)' : 'none';
    });
    renderHistoryList(_allSessions);
  });
});

document.getElementById('btn-confirm-delete-no').addEventListener('click', () => {
  _pendingDeleteId = null;
  document.getElementById('modal-confirm-delete').classList.add('hidden');
});

document.getElementById('btn-confirm-delete-yes').addEventListener('click', async () => {
  document.getElementById('modal-confirm-delete').classList.add('hidden');
  if (!_pendingDeleteId) return;
  const sid = _pendingDeleteId;
  _pendingDeleteId = null;
  await fetch(`/api/sessions/${sid}`, { method: 'DELETE' });
  const openTab = getTabBySessionId(sid);
  if (openTab) closeTab(openTab.id);
  _allSessions = _allSessions.filter(s => s.session_id !== sid);
  renderHistoryList(_allSessions);
  const hCount = document.getElementById('history-count');
  if (hCount) hCount.textContent = _allSessions.length > 0 ? `${_allSessions.length}` : '';
});

function renderHistoryList(sessions) {
  const filtered = _historyFilter
    ? sessions.filter(s => s.end_reason === _historyFilter ||
        (_historyFilter === 'halted' && s.end_reason === 'expired'))
    : sessions;

  historyList.innerHTML = '';
  if (!filtered.length) {
    const msg = _historyFilter ? 'No matching sessions.' : 'No sessions yet.';
    historyList.innerHTML = `<p class="text-muted text-xs px-3 py-4">${msg}</p>`;
    return;
  }

  const pillStyles = { convergence: 'text-verdictAgree', round_limit: 'text-verdictRevised', halted: 'text-muted', expired: 'text-muted' };
  const pillLabels = { convergence: '\u2713 converged', round_limit: '\u26a0 round limit', halted: '\u23f9 halted', expired: '\u23f3 expired' };

  for (const s of filtered) {
    const row = document.createElement('div');
    row.className = 'relative group text-left w-full px-3 py-2 border-b border-white/5 hover:bg-white/5 transition flex flex-col gap-0.5 cursor-pointer';
    row.dataset.sessionId = s.session_id;

    const goalEl = document.createElement('span');
    goalEl.className = 'text-xs text-user truncate pr-5';
    goalEl.textContent = (s.goal || '').slice(0, 40) + ((s.goal || '').length > 40 ? '\u2026' : '');

    const metaEl = document.createElement('span');
    metaEl.className = 'text-xs text-muted flex items-center gap-1';
    const tsEl = document.createElement('span');
    tsEl.textContent = s.started_at ? relativeTime(s.started_at) : '';
    metaEl.appendChild(tsEl);
    if (s.end_reason) {
      const pillEl = document.createElement('span');
      pillEl.className = `text-xs ${pillStyles[s.end_reason] || 'text-muted'}`;
      pillEl.textContent = pillLabels[s.end_reason] || s.end_reason;
      metaEl.appendChild(document.createTextNode(' \u00b7 '));
      metaEl.appendChild(pillEl);
    }

    const delBtn = document.createElement('button');
    delBtn.className = 'absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-40 hover:!opacity-100 transition text-muted hover:text-verdictDisagree text-sm leading-none px-1';
    delBtn.textContent = '\u00d7';
    delBtn.title = 'Remove from history';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _pendingDeleteId = s.session_id;
      document.getElementById('modal-confirm-delete').classList.remove('hidden');
    });

    row.appendChild(goalEl);
    row.appendChild(metaEl);
    row.appendChild(delBtn);
    row.addEventListener('click', () => openHistorySession(s.session_id, s.goal));
    historyList.appendChild(row);
  }
}

async function loadHistory() {
  let sessions;
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) throw new Error(res.status);
    sessions = await res.json();
  } catch (_) {
    historyList.innerHTML = '<p class="text-muted text-xs px-3 py-4">Could not load history.</p>';
    return;
  }

  _allSessions = sessions;
  historyList.scrollTop = 0;

  const hCount = document.getElementById('history-count');
  if (hCount) hCount.textContent = sessions.length > 0 ? `${sessions.length}` : '';

  renderHistoryList(sessions);
}

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

async function openHistorySession(sessionId, goal) {
  const existing = getTabBySessionId(sessionId);
  if (existing) { switchTab(existing.id); return; }

  let data;
  try {
    const res = await fetch(`/api/sessions/${sessionId}`);
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch (_) {
    onError({ message: `Could not load session ${sessionId}` });
    return;
  }

  const tab = createTab(goal || sessionId, sessionId, 'readonly');
  switchTab(tab.id);
  stickyBottom = false;
  reconstructSession(tab, data.events);
  dialogue.scrollTop = 0;
  tab.scrollTop = 0;
  updateInputStrip(tab);
  saveOpenTabs();
}

// ------------------------------------------------------------------ session reconstruction

// Background restore: write into tab._nodes only, never touch live DOM.
function reconstructSessionIntoTab(tab, events) {
  const readonlyBanner = document.createElement('div');
  readonlyBanner.className = 'rounded border border-white/10 bg-userPanel px-4 py-2 text-center text-muted text-xs';
  readonlyBanner.textContent = 'This session is complete. Read-only view.';
  appendNodeToTab(tab, readonlyBanner);
  _reconstructEvents(events, node => appendNodeToTab(tab, node));
}

// Foreground open: write into active tab via appendToActiveTab (touches live DOM).
function reconstructSession(tab, events) {
  const readonlyBanner = document.createElement('div');
  readonlyBanner.className = 'rounded border border-white/10 bg-userPanel px-4 py-2 text-center text-muted text-xs';
  readonlyBanner.textContent = 'This session is complete. Read-only view.';
  appendToActiveTab(readonlyBanner);
  _reconstructEvents(events, node => appendToActiveTab(node));
}

// Core reconstruction logic. appendFn adds a node wherever appropriate.
// Maintains a local cardMap so turn_end/turn_interrupted can find their card
// without relying on document.getElementById (which fails for off-DOM nodes).
function _reconstructEvents(events, appendFn) {
  const cardMap = {}; // turn_id -> card DOM node

  for (const ev of events) {
    const kind = ev.kind;

    if (kind === 'session_start') {
      const goalCard = document.createElement('div');
      goalCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
      goalCard.innerHTML = `
        <div class="text-xs text-muted uppercase">goal</div>
        <pre class="whitespace-pre-wrap text-user">${escHtml(ev.payload?.goal || '')}</pre>
      `;
      appendFn(goalCard);
      appendFn(buildCollapseToggle());

    } else if (kind === 'turn_start') {
      const card = buildTurnCard({ turn_id: ev.turn_id, actor: ev.actor, role: ev.role });
      cardMap[ev.turn_id] = card;
      appendFn(card);

    } else if (kind === 'turn_end' || kind === 'turn_interrupted') {
      const card = cardMap[ev.turn_id];
      const interrupted = kind === 'turn_interrupted';

      // populate body
      const body = card ? card.querySelector(`#body-${ev.turn_id}`) : null;
      if (body) {
        body.classList.remove('thinking');
        body.textContent = ev.payload?.text || (interrupted ? '(no output before interrupt)' : '');
      }

      // populate reasoning
      if (ev.payload?.reasoning) {
        const details = card ? card.querySelector(`#reasoning-${ev.turn_id}`) : null;
        const pre = card ? card.querySelector(`#reasoning-body-${ev.turn_id}`) : null;
        if (details && pre) { details.classList.remove('hidden'); details.open = true; pre.textContent = ev.payload.reasoning; }
      }

      // badge
      const threadId = ev.payload?.thread_id || ev.thread_id || '';
      if (threadId && card) {
        const badge = card.querySelector(`#badge-${ev.turn_id}`);
        if (badge) {
          const short = threadId.length > 14 ? threadId.slice(0, 14) + '\u2026' : threadId;
          badge.textContent = `${ev.turn_id} \u00b7 ${short}`;
          badge.title = threadId;
        }
      }

      // verdict (turn_end only)
      if (!interrupted) applyVerdict(ev.turn_id, ev.payload?.verdict, card);

      // chevron
      enableCollapseChevron(ev.turn_id, card);

      // interrupted note
      if (interrupted && card) {
        const note = document.createElement('div');
        note.className = 'text-xs text-muted border-t border-white/10 pt-2 mt-1';
        note.textContent = '\u23f8 interrupted';
        card.appendChild(note);
      }

    } else if (kind === 'user_input') {
      const targetLabels = { claude: 'CLAUDE', codex: 'CODEX', both: 'CLAUDE, CODEX' };
      const target = ev.payload?.target || 'both';
      const userCard = document.createElement('div');
      userCard.className = 'rounded-lg border border-white/10 bg-userPanel p-3 flex flex-col gap-1';
      userCard.innerHTML = `
        <div class="text-xs text-muted uppercase">DIRECTIVE \u2192 ${targetLabels[target] || target.toUpperCase()}</div>
        <pre class="whitespace-pre-wrap text-user">${escHtml(ev.payload?.text || '')}</pre>
      `;
      appendFn(userCard);

    } else if (kind === 'session_end') {
      const reasons = {
        convergence: '\u2713 Both agents reached agreement.',
        round_limit: '\u26a0 Round limit reached.',
        token_limit: '\u26a0 Token budget exhausted.',
        halted:      '\u23f9 Session halted.',
        expired:     '\u23f3 Stopped / expired.',
      };
      const reason = ev.payload?.reason || '';
      const banner = document.createElement('div');
      banner.className = 'rounded-lg border border-white/20 bg-userPanel px-4 py-3 text-center text-muted';
      banner.textContent = reasons[reason] || `Session ended: ${reason}`;
      appendFn(banner);
    }
  }
}

function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ------------------------------------------------------------------ scroll

dialogue.addEventListener('scroll', () => {
  const atBottom = dialogue.scrollHeight - dialogue.scrollTop - dialogue.clientHeight < 40;
  stickyBottom = atBottom;
});

function scrollIfSticky() {
  if (stickyBottom) dialogue.scrollTop = dialogue.scrollHeight;
}

// ------------------------------------------------------------------ init

connectWS();
loadHistory();
restoreOpenTabs();
