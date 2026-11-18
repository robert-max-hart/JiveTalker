/* The voice picker: a searchable, grouped list in place of a plain <select> of voices. Used by the toolkit
   page and the mixer (served at /voicepicker.js; plain JS, no build step).

   It sits on top of a real <select data-voicepick> and keeps it as the source of truth: picking a voice sets
   select.value and fires 'change', so forms and handlers work as before. Setting select.value from code, or
   refilling its options, updates the button.

   Groups: Recent (the last picks, kept in this browser), In this script (VoicePicker.inScript() returns
   [{source, name}]), Your voices (by subfolder: "villagers/bob" goes under "villagers"), then Kokoro's stock
   voices by language and gender. Typing filters by name, id, group or speaker. */
(function () {
  'use strict';
  const LANG = {a: 'American English', b: 'British English', e: 'Spanish', f: 'French', h: 'Hindi', i: 'Italian',
                j: 'Japanese', p: 'Brazilian Portuguese', z: 'Mandarin Chinese'};
  const LANG_ORDER = 'abefhijpz';
  const STOCK_RE = /^([a-z])([fm])_([a-z]+)$/;
  const RECENT_KEY = 'jt.recentVoices', RECENT_MAX = 6;
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  function recent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch (e) { return []; } }
  function remember(id) {
    try { localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...recent().filter(x => x !== id)].slice(0, RECENT_MAX))); } catch (e) {}
  }

  // what an id looks like in the list: {label, sub (shown small), group, order}
  function describe(id) {
    const m = STOCK_RE.exec(id);
    if (m && LANG[m[1]]) {
      const g = m[2] === 'f' ? 'female' : 'male';
      return {label: cap(m[3]), sub: id, group: `${LANG[m[1]]} · ${g}`, order: 3000 + LANG_ORDER.indexOf(m[1]) * 2 + (m[2] === 'm')};
    }
    const i = id.lastIndexOf('/');
    return i < 0 ? {label: id, sub: '', group: 'Your voices', order: 1000}
                 : {label: id.slice(i + 1), sub: id, group: `Your voices · ${id.slice(0, i)}`, order: 1001};
  }

  let open = null;      // the picker whose list is showing

  const css = `
.vp-btn { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; text-align: left; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; cursor: pointer; font: inherit; color: inherit; min-height: 32px }
.vp-btn:hover { border-color: var(--accent) }
.vp-btn .vp-l { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.vp-btn .vp-s { font: 11px var(--mono); color: var(--muted); white-space: nowrap }
.vp-btn .vp-ph { color: var(--muted) }
.vp-pop { position: fixed; z-index: 50; width: 320px; max-width: calc(100vw - 16px); background: var(--panel); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,.22); display: flex; flex-direction: column; overflow: hidden }
.vp-pop input { margin: 8px; padding: 6px 9px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: inherit; font: inherit }
.vp-list { overflow: auto; max-height: 340px; padding: 0 4px 6px }
.vp-g { font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); padding: 8px 8px 3px; position: sticky; top: 0; background: var(--panel) }
.vp-i { display: flex; align-items: baseline; gap: 8px; padding: 4px 8px; border-radius: 6px; cursor: pointer }
.vp-i .vp-l { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.vp-i .vp-s { font: 11px var(--mono); color: var(--muted); white-space: nowrap }
.vp-i.on { background: var(--accent-soft) }
.vp-i.cur .vp-l { font-weight: 700 }
.vp-none { padding: 10px; color: var(--muted); font-size: 12.5px }`;

  function enhance(sel) {
    if (sel.dataset.vpDone) return;
    sel.dataset.vpDone = '1';
    if (!document.getElementById('vp-css')) {
      const st = document.createElement('style'); st.id = 'vp-css'; st.textContent = css; document.head.append(st);
    }
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = ('vp-btn ' + sel.className).trim();      // keeps layout classes (grow)
    btn.setAttribute('aria-haspopup', 'listbox');
    if (sel.getAttribute('aria-label')) btn.setAttribute('aria-label', sel.getAttribute('aria-label'));
    if (sel.id) { const lab = document.querySelector(`label[for="${CSS.escape(sel.id)}"]`); if (lab) lab.htmlFor = ''; }
    sel.hidden = true; sel.tabIndex = -1;
    sel.after(btn);

    const refresh = () => {
      const o = sel.selectedOptions[0];
      if (!o || !o.value) { btn.innerHTML = `<span class="vp-l vp-ph">${esc(o ? o.text : 'Pick a voice…')}</span><span class="vp-s">▾</span>`; return; }
      const d = describe(o.value), label = o.text !== o.value ? o.text : d.label, sub = o.text !== o.value ? '' : d.sub;
      btn.innerHTML = `<span class="vp-l">${esc(label)}</span><span class="vp-s">${esc(sub)} ▾</span>`;
      btn.title = o.value;
    };
    // setting .value from code, or refilling the options, updates the button
    const desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
    Object.defineProperty(sel, 'value', {configurable: true, get() { return desc.get.call(sel); },
                                         set(v) { desc.set.call(sel, v); refresh(); }});
    new MutationObserver(refresh).observe(sel, {childList: true, subtree: true});
    sel.addEventListener('change', refresh);
    refresh();
    btn.addEventListener('click', () => (open && open.sel === sel) ? close() : show(sel, btn));
    btn.addEventListener('keydown', e => { if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(sel, btn); } });
  }

  function items(sel) {
    const opts = [...sel.options].filter(o => o.value);
    const ids = new Set(opts.map(o => o.value));
    const out = [];
    const used = (window.VoicePicker.inScript && window.VoicePicker.inScript()) || [];
    for (const id of recent()) if (ids.has(id)) out.push({id, group: 'Recent', order: 0});
    const byVoice = {};
    for (const c of used) if (c.source && ids.has(c.source)) (byVoice[c.source] = byVoice[c.source] || []).push(c.name);
    for (const [id, who] of Object.entries(byVoice)) out.push({id, group: 'In this script', order: 500, who: who.join(', ')});
    for (const o of opts) {
      const d = describe(o.value);
      out.push({id: o.value, group: d.group, order: d.order, text: o.value !== o.text ? o.text : null});
    }
    return out.map(x => Object.assign({}, describe(x.id), x, x.text ? {label: x.text, sub: ''} : {}))
              .sort((a, b) => a.order - b.order || a.group.localeCompare(b.group) || (a.order >= 1000 ? a.label.localeCompare(b.label) : 0));
  }

  function show(sel, btn) {
    close();
    const pop = document.createElement('div');
    pop.className = 'vp-pop'; pop.setAttribute('role', 'dialog');
    pop.innerHTML = `<input type="search" placeholder="Search voices: name, language, male…" aria-label="Search voices"><div class="vp-list" role="listbox"></div>`;
    document.body.append(pop);
    const r = btn.getBoundingClientRect(), w = Math.max(r.width, 320);
    pop.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px';
    pop.style.width = w + 'px';
    const below = innerHeight - r.bottom;
    if (below < 260 && r.top > below) pop.style.bottom = (innerHeight - r.top + 4) + 'px'; else pop.style.top = (r.bottom + 4) + 'px';
    const input = pop.querySelector('input'), list = pop.querySelector('.vp-list');
    const all = items(sel);
    let shown = [], hi = 0;
    const draw = () => {
      const q = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      shown = all.filter(x => q.every(t => `${x.label} ${x.id} ${x.group} ${x.who || ''}`.toLowerCase().includes(t)));
      if (q.length) {          // when searching: each voice once, and Recent left out
        const seen = new Set(); shown = shown.filter(x => x.group !== 'Recent' && !seen.has(x.id) && seen.add(x.id));
      }
      hi = Math.max(0, Math.min(hi, shown.length - 1));
      let html = '', g = null;
      shown.forEach((x, i) => {
        if (x.group !== g) { g = x.group; html += `<div class="vp-g">${esc(g)}</div>`; }
        html += `<div class="vp-i${i === hi ? ' on' : ''}${x.id === sel.value ? ' cur' : ''}" role="option" data-i="${i}" aria-selected="${x.id === sel.value}">
          <span class="vp-l">${esc(x.label)}</span><span class="vp-s">${esc(x.who ? x.who : x.sub)}</span></div>`;
      });
      list.innerHTML = html || '<div class="vp-none">No voice matches.</div>';
      const on = list.querySelector('.vp-i.on'); if (on) on.scrollIntoView({block: 'nearest'});
    };
    const pick = i => {
      const x = shown[i]; if (!x) return;
      remember(x.id); close(); btn.focus();
      sel.value = x.id;          // 'input' too: some forms listen for that
      sel.dispatchEvent(new Event('input', {bubbles: true})); sel.dispatchEvent(new Event('change', {bubbles: true}));
    };
    input.addEventListener('input', () => { hi = 0; draw(); });
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); hi = Math.min(hi + 1, shown.length - 1); draw(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); hi = Math.max(hi - 1, 0); draw(); }
      else if (e.key === 'Enter') { e.preventDefault(); pick(hi); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); }
    });
    list.addEventListener('mousemove', e => { const it = e.target.closest('.vp-i'); if (it && +it.dataset.i !== hi) { hi = +it.dataset.i; draw(); } });
    list.addEventListener('click', e => { const it = e.target.closest('.vp-i'); if (it) pick(+it.dataset.i); });
    draw();
    const at = shown.findIndex(x => x.id === sel.value && x.order >= 500);
    if (at >= 0) { hi = at; draw(); }
    open = {sel, pop};
    input.focus();
  }

  function close() { if (open) { open.pop.remove(); open = null; } }
  document.addEventListener('pointerdown', e => { if (open && !open.pop.contains(e.target) && !e.target.closest('.vp-btn')) close(); }, true);
  addEventListener('resize', close);
  document.addEventListener('scroll', e => { if (open && !open.pop.contains(e.target)) close(); }, true);

  window.VoicePicker = {
    enhance,
    enhanceAll(root) { (root || document).querySelectorAll('select[data-voicepick]').forEach(enhance); },
    inScript: null,
    describe,
  };
})();
