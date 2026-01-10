(function(){
  const root = document.getElementById('show-root');
  // Initial view is main
  root.classList.add('view-main');

  // Swipe handling
  let startX = 0; let startY = 0; let currentX = 0; let currentY = 0; let isTouching = false; let activeView = 'main';
  const isMobile = matchMedia('(max-width: 1000px)').matches;

  function setView(view){
    // If leaving dashboard while settings tab is active, persist as a safety
    if (activeView === 'dashboard'){
      const settingsActive = document.getElementById('tab-settings')?.classList.contains('active');
      if (settingsActive) {
        try { persistSettings(); } catch {}
      }
    }
    activeView = view;
    root.classList.remove('view-dashboard','view-main','view-quick');
    root.classList.add('view-' + view);
  }

  function onTouchStart(e){
    isTouching = true;
    startX = (e.touches ? e.touches[0].clientX : e.clientX);
    startY = (e.touches ? e.touches[0].clientY : e.clientY);
    currentX = startX; currentY = startY;
    document.body.classList.add('dragging');
  }
  function onTouchMove(e){
    if(!isTouching) return;
    currentX = (e.touches ? e.touches[0].clientX : e.clientX);
    currentY = (e.touches ? e.touches[0].clientY : e.clientY);
    const dx = Math.abs(currentX - startX);
    const dy = Math.abs(currentY - startY);
    // If horizontal gesture dominates, prevent default to capture swipe
    if (dx > dy && dx > 10) {
      if (e.cancelable) e.preventDefault();
    }
  }
  function onTouchEnd(){
    if(!isTouching) return; isTouching = false; document.body.classList.remove('dragging');
    const dx = currentX - startX;
    const threshold = 60; // pixels
    if(Math.abs(dx) < threshold) return;
    if(dx < 0){ // swipe left
      if(activeView === 'main') setView('quick');
      else if(activeView === 'dashboard') setView('main');
    } else { // swipe right
      if(activeView === 'main') setView('dashboard');
      else if(activeView === 'quick') setView('main');
    }
  }

  root.addEventListener('touchstart', onTouchStart, {passive:true});
  root.addEventListener('touchmove', onTouchMove, {passive:true});
  root.addEventListener('touchend', onTouchEnd);
  root.addEventListener('mousedown', onTouchStart);
  root.addEventListener('mousemove', onTouchMove);
  root.addEventListener('mouseup', onTouchEnd);

  // Settings (local first, upgrade from server when available)
  const SETTINGS_KEY = 'neubot_show_settings_v1';
  function loadSettings(){ try { return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch { return {}; } }
  function saveSettings(s){ localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); }
  let settings = Object.assign({ hourFormat: '12', defaultRoom: '', followRoomBg: false }, loadSettings());

  // Populate dashboard settings UI (new: dropdown/text/checkbox) and autosave
  function applySettingsToUI(){
    const hourSel = document.getElementById('show-hour-format');
    const room = document.getElementById('show-default-room');
    const follow = document.getElementById('show-bg-follow-room');
    if (hourSel) hourSel.value = settings.hourFormat;
    if (room) room.value = settings.defaultRoom || '';
    if (follow) follow.checked = !!settings.followRoomBg;
  }
  applySettingsToUI();

  function persistSettings(){
    saveSettings(settings);
    fetch('/api/show-settings', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hour_format: settings.hourFormat, default_room: settings.defaultRoom, follow_room_bg: settings.followRoomBg}) }).catch(()=>{});
    updateClock(true);
    toast('Settings saved');
  }
  function wireAutosave(){
    const hourSel = document.getElementById('show-hour-format');
    const room = document.getElementById('show-default-room');
    const follow = document.getElementById('show-bg-follow-room');
    hourSel?.addEventListener('change', (e)=>{ settings.hourFormat = e.target.value; persistSettings(); });
    room?.addEventListener('change', (e)=>{ settings.defaultRoom = e.target.value.trim(); persistSettings(); });
    room?.addEventListener('blur', (e)=>{ if (settings.defaultRoom !== e.target.value.trim()){ settings.defaultRoom = e.target.value.trim(); persistSettings(); }});
    follow?.addEventListener('change', (e)=>{ settings.followRoomBg = !!e.target.checked; persistSettings(); });
  }
  wireAutosave();
  // Try to pull server-side settings (if authenticated)
  fetch('/api/show-settings').then(r=>r.json()).then(s=>{
    if (!s) return;
    if (s.hour_format) settings.hourFormat = String(s.hour_format);
    if (typeof s.default_room === 'string') settings.defaultRoom = s.default_room;
  if (typeof s.follow_room_bg !== 'undefined') settings.followRoomBg = !!s.follow_room_bg;
    saveSettings(settings); applySettingsToUI(); updateClock(true);
  }).catch(()=>{});

  // Clock
  const timeEl = document.getElementById('clock-time');
  const dateEl = document.getElementById('clock-date');
  function pad(n){ return n.toString().padStart(2,'0'); }
  function updateClock(force){
    const now = new Date();
    let h = now.getHours();
    const m = pad(now.getMinutes());
    if (settings.hourFormat === '12') { h = h % 12; if (h === 0) h = 12; timeEl.textContent = `${h}:${m}`; }
    else { timeEl.textContent = `${pad(h)}:${m}`; }
    dateEl.textContent = now.toLocaleDateString(undefined, { weekday: 'long', year:'numeric', month:'long', day:'numeric' });
  }
  updateClock(true);
  setInterval(updateClock, 1000 * 15);

  // Query send
  const qInput = document.getElementById('show-query-input');
  const qSend = document.getElementById('show-send');
  const qResp = document.getElementById('show-response');
  let hideTimer = null;
  function hideOverlay(){
  if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
  const clock = document.querySelector('.main-clock');
  qResp.classList.remove('visible');
  // reveal clock immediately; let overlay fade out gracefully
  clock?.classList.remove('hidden');
  // reset background when returning to clock
  try { resetBackground(); } catch {}
  const cleanup = () => { qResp.innerHTML = ''; qResp.removeEventListener('transitionend', cleanup); };
  qResp.addEventListener('transitionend', cleanup);
  }
  function showOverlayAnimated(text){
    if (!text) text = '';
    // hide clock while showing overlay
    document.querySelector('.main-clock')?.classList.add('hidden');
    qResp.classList.add('visible');
    qResp.innerHTML = '<div class="resp-inner"><div class="big-text"></div></div>';
    const holder = qResp.querySelector('.big-text');
    // Summarize structured responses (search_results)
    try {
      if (typeof text === 'string' && text.trim().startsWith('{')){
        const obj = JSON.parse(text);
        if (obj && obj.type === 'search_results' && Array.isArray(obj.results) && obj.results.length){
          const top = obj.results[0];
          const host = (()=>{ try { return new URL(top.url).host; } catch { return 'the web'; } })();
          const clean = String(top.description || '').replace(/<[^>]+>/g,'').trim();
          text = clean ? `According to ${host}, ${clean}` : `According to ${host}.`;
        }
      }
    } catch {}
    const words = String(text).split(/\s+/).filter(Boolean);
  const spans = words.map((w)=>{ const s=document.createElement('span'); s.className='word'; s.textContent = w; holder.appendChild(s); return s; });
    spans.forEach((s,i)=> setTimeout(()=> s.classList.add('show'), i*90));
    // Fit text: progressively reduce font-size until it fits in available height
    const respInner = qResp.querySelector('.resp-inner');
    function fit(){
      let size = parseFloat(getComputedStyle(holder).fontSize);
      const maxHeight = qResp.clientHeight - 40; // padding buffer
      let guard = 0;
      while (holder.scrollHeight > maxHeight && size > 20 && guard < 20){
        size -= 4; guard += 1; holder.style.fontSize = size + 'px';
      }
    }
    // Initial fit after words inserted, then refit on window resize
    setTimeout(fit, 50);
    const ro = new ResizeObserver(()=> fit());
    ro.observe(respInner);
    // Stop observing on hide
    qResp.addEventListener('transitionend', function cleanup(){ if(!qResp.classList.contains('visible')){ try{ ro.disconnect(); }catch{} qResp.removeEventListener('transitionend', cleanup);} });
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(hideOverlay, 10000);
  }
  qResp.addEventListener('click', hideOverlay);

  function sendQuery(text){
    if(!text.trim()) return;
    showOverlayAnimated('Thinking…');
    fetch('/api/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: text, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }),
    }).then(r => r.json()).then(d => {
      let displayText = d.response || 'Sorry, something went wrong.';
      const widgets = d.widgets || [];
      
      // Analyze widgets for side effects (background color, etc)
      if (widgets.length) {
        widgets.forEach(w => {
           if (w.type === 'home_assistant' || w.type === 'ha_result') {
                // Check applied colors
                const data = w.data || w;
                const color = data.applied?.color_name || (data.applied?.colors && data.applied.colors[0]);
                if (settings.followRoomBg && color) setTempBackgroundFromColors([color]); 
                else if (settings.followRoomBg) resetBackground();
           } else if (w.type === 'search_results') {
                setTempBackgroundBlue();
           }
        });
      }
      
      showOverlayAnimated(displayText);
    }).catch(() => {
      showOverlayAnimated('Sorry, something went wrong.');
    });
  }
  qSend.addEventListener('click', () => sendQuery(qInput.value));
  qInput.addEventListener('keypress', (e) => { if(e.key === 'Enter'){ sendQuery(qInput.value); qInput.value=''; }});

  // User info + limits
  const dashAvatar = document.getElementById('dash-user-avatar');
  const dashName = document.getElementById('dash-user-name');
  const dashEmail = document.getElementById('dash-user-email');
  const showAvatar = document.getElementById('show-user-avatar');
  const signInBtn = document.getElementById('dash-signin');

  function updateUser(){
    fetch('/api/user').then(r=>r.json()).then(u => {
      if(u && u.authenticated && u.user){
        dashName.textContent = u.user.name || 'Account';
        dashEmail.textContent = u.user.email || '';
        const avatar = u.user.profile_pic || 'user-icon.svg';
        dashAvatar.src = avatar; showAvatar.src = avatar;
        // Hide sign-in button if already signed in
        if (signInBtn) signInBtn.style.display = 'none';
      } else {
        dashName.textContent = 'Account';
        dashEmail.textContent = 'Sign in for increased limits';
        dashAvatar.src = 'user-icon.svg'; showAvatar.src = 'user-icon.svg';
        if (signInBtn) signInBtn.style.display = '';
      }
    }).catch(()=>{});
  }
  function updateLimits(){
    fetch('/api/limits').then(r=>r.json()).then(l => {
      const set = (used, limit, barId, usedId, limitId) => {
        const pct = limit ? Math.min(100, (used/limit)*100) : 0;
        document.getElementById(barId).style.width = pct + '%';
        document.getElementById(usedId).textContent = used;
        document.getElementById(limitId).textContent = limit;
      };
      set(l.search.used, l.search.limit, 'dash-search-bar', 'dash-search-used', 'dash-search-limit');
      set(l.weather.used, l.weather.limit, 'dash-weather-bar', 'dash-weather-used', 'dash-weather-limit');
      document.getElementById('dash-reset-days').textContent = l.reset.days_remaining;
    }).catch(()=>{});
  }
  updateUser(); updateLimits();
  setInterval(() => { updateLimits(); }, 60000);

  // Exit
  document.getElementById('exit-show-mode').addEventListener('click', () => { window.location.href = '/'; });

  // Tabs: Account/Settings, auto-save on switch away from Settings
  (function(){
    const tabs = Array.from(document.querySelectorAll('.tab-btn'));
    const panels = { account: document.getElementById('tab-account'), settings: document.getElementById('tab-settings') };
    function activate(name){
      tabs.forEach(t=> t.classList.toggle('active', t.dataset.tab === name));
      Object.entries(panels).forEach(([key, el])=> el.classList.toggle('active', key === name));
    }
    tabs.forEach(t => t.addEventListener('click', ()=>{
      // if leaving settings and inputs changed, persist (inputs already autosave on change; this is a safety)
      if (t.dataset.tab === 'account') { persistSettings(); }
      activate(t.dataset.tab);
    }));
    activate('account');
  })();

  // Sign in flow: confirm leaving Show Mode
  signInBtn?.addEventListener('click', async ()=>{
    const ok = await confirmModal('Leave Show Mode to sign in?', { title: 'Caution', okText: 'OK', cancelText: 'Cancel' });
    if (ok) window.location.href = '/login';
  });

  // Quick actions store
  const STORE_KEY = 'neubot_quick_actions_v1';
  /** action: { id:string, name:string, icon:string, commands:string[], pinned:boolean } */
  function loadActions(){
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { return []; }
  }
  function saveActions(list){ localStorage.setItem(STORE_KEY, JSON.stringify(list)); }
  function uid(){ return Math.random().toString(36).slice(2, 9); }

  let actions = loadActions();

  const pinnedEl = document.getElementById('pinned-actions');
  const allEl = document.getElementById('all-actions');

  function render(){
    // Pinned
    pinnedEl.innerHTML = '';
    const pinned = actions.filter(a => a.pinned).slice(0,8);
    pinned.forEach(a => {
      const tile = document.createElement('button');
      tile.className = 'action-tile';
      tile.innerHTML = `<div class="action-emoji">${a.icon || '⭐'}</div><div class="action-name">${a.name}</div>`;
      tile.addEventListener('click', () => runAction(a));
      pinnedEl.appendChild(tile);
    });

    // All
    allEl.innerHTML = '';
    actions.forEach(a => {
      const row = document.createElement('div'); row.className = 'action-item';
      row.innerHTML = `
        <div class="act-emoji">${a.icon || '⭐'}</div>
        <div class="act-name">${a.name}</div>
        <div class="act-controls">
          <button data-act="run">Run</button>
          <button data-act="pin">${a.pinned ? 'Unpin' : 'Pin'}</button>
          <button data-act="edit">Edit</button>
        </div>`;
      row.querySelector('[data-act="run"]').addEventListener('click', () => runAction(a));
      row.querySelector('[data-act="pin"]').addEventListener('click', () => togglePin(a.id));
      row.querySelector('[data-act="edit"]').addEventListener('click', () => openModal(a));
      allEl.appendChild(row);
    });
  }

  function togglePin(id){
    const pinnedCount = actions.filter(a=>a.pinned).length;
    actions = actions.map(a => a.id === id ? { ...a, pinned: a.pinned ? false : (pinnedCount < 8) } : a);
    saveActions(actions); render();
  }

  function runAction(action){
    if(!action || !Array.isArray(action.commands)) return;
    // Execute commands sequentially by sending queries
    const cmds = action.commands.filter(Boolean);
    if(cmds.length === 0) return;
    // Show feedback
    setView('main'); // return to main screen
    showOverlayAnimated(`Running: ${action.name}`);
    (async () => {
      for(const c of cmds){
        await fetch('/api/query', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: c, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })
        }).then(r => r.json()).then(() => {}).catch(()=>{});
      }
      showOverlayAnimated(`Finished: ${action.name}`);
    })();
  }

  // Modal
  const modal = document.getElementById('action-modal');
  const modalClose = document.getElementById('action-modal-close');
  const qaName = document.getElementById('qa-name');
  const qaIcon = document.getElementById('qa-icon');
  const qaCommands = document.getElementById('qa-commands');
  const qaPinned = document.getElementById('qa-pinned');
  const qaSave = document.getElementById('qa-save');
  const qaDelete = document.getElementById('qa-delete');
  let editingId = null;

  function openModal(action){
    editingId = action ? action.id : null;
    qaName.value = action ? action.name : '';
    qaIcon.value = action ? (action.icon || '') : '';
    qaCommands.value = action && Array.isArray(action.commands) ? action.commands.join('\n') : '';
    qaPinned.checked = !!(action && action.pinned);
    qaDelete.style.display = editingId ? '' : 'none';
    modal.classList.add('open');
  }
  function closeModal(){ modal.classList.remove('open'); }
  modalClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if(e.target === modal) closeModal(); });

  document.getElementById('add-action').addEventListener('click', () => openModal(null));
  qaSave.addEventListener('click', () => {
    const name = qaName.value.trim();
    const icon = qaIcon.value.trim() || '⭐';
    const commands = qaCommands.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    let pinned = qaPinned.checked;

    if(!name || commands.length === 0){
      toast('Please provide a name and at least one command.', 'warn');
      return;
    }

    if(editingId){
      actions = actions.map(a => a.id === editingId ? { ...a, name, icon, commands, pinned } : a);
    } else {
      if(pinned && actions.filter(a=>a.pinned).length >= 8) pinned = false; // enforce
      actions.push({ id: uid(), name, icon, commands, pinned });
    }
    saveActions(actions); render(); closeModal(); toast('Action saved');
  });
  qaDelete.addEventListener('click', async () => {
    if(!editingId) return;
    const ok = await confirmModal('Delete this action?');
    if (!ok) return;
    actions = actions.filter(a => a.id !== editingId);
    saveActions(actions); render(); closeModal(); toast('Action deleted');
  });

  // Initial render
  render();

  // Temporary background helpers
  const initialShowBg = getComputedStyle(document.documentElement).getPropertyValue('--show-bg');
  function colorToRgba(color, alpha){
    // rudimentary map for common names; fallback to white with alpha
    const map = { red:[255,59,48], green:[52,199,89], blue:[0,122,255], yellow:[255,204,0], orange:[255,149,0], purple:[175,82,222], pink:[255,45,85], cyan:[50,173,230], white:[255,255,255] };
    const key = String(color||'').toLowerCase();
    const rgb = map[key];
    if (rgb) return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
    return `rgba(255,255,255, ${alpha})`;
  }
  function setTempBackgroundFromColors(colors){
    if (!Array.isArray(colors) || colors.length === 0) return;
    const rootStyle = document.documentElement.style;
    const c1 = colors[0];
    const c2 = colors[1] || colors[0];
    const c3 = 'rgba(0,0,0,0.65)';
    const bg = `radial-gradient(1200px 800px at 70% 20%, ${colorToRgba(c1,0.25)}, ${colorToRgba(c2,0.25)} 45%, ${c3} 60%), linear-gradient(180deg, #0b0b10, #0a0a0d)`;
    rootStyle.setProperty('--show-bg', bg);
  }
  function setTempBackgroundBlue(){
    const rootStyle = document.documentElement.style;
    const c1 = colorToRgba('blue', 0.25);
    const c3 = 'rgba(0,0,0,0.65)';
    const bg = `radial-gradient(1200px 800px at 70% 20%, ${c1}, ${c1} 45%, ${c3} 60%), linear-gradient(180deg, #0b0b10, #0a0a0d)`;
    rootStyle.setProperty('--show-bg', bg);
  }
  function resetBackground(){
    const rootStyle = document.documentElement.style;
    if (initialShowBg) rootStyle.setProperty('--show-bg', initialShowBg.trim());
  }

  // Toasts
  function toast(msg, type){
    const cont = document.getElementById('toast-container');
    if (!cont) return;
    const t = document.createElement('div');
    t.className = 'toast';
    const icon = type==='warn' ? 'fa-triangle-exclamation' : (type==='ok' ? 'fa-circle-check' : 'fa-circle-info');
    t.innerHTML = `<i class="fa-solid ${icon}"></i><span>${msg}</span>`;
    cont.appendChild(t);
    setTimeout(()=>{ t.style.opacity = '0'; t.style.transform = 'translateY(6px)'; setTimeout(()=> cont.removeChild(t), 250); }, 2200);
  }

  // Confirm modal
  function confirmModal(message, opts){
    return new Promise(resolve => {
      const m = document.getElementById('confirm-modal');
      m.querySelector('#confirm-message').textContent = message;
      const titleEl = m.querySelector('#confirm-title');
      const okBtn = m.querySelector('#confirm-ok');
      const cancelBtn = m.querySelector('#confirm-cancel');
      const xBtn = m.querySelector('#confirm-close');
      const options = Object.assign({ title: 'Confirm', okText: 'OK', cancelText: 'Cancel' }, opts || {});
      if (titleEl) titleEl.textContent = options.title;
      if (okBtn) okBtn.textContent = options.okText;
      if (cancelBtn) cancelBtn.textContent = options.cancelText;
      const close = ()=> m.classList.remove('open');
      const onOk = ()=>{ cleanup(); close(); resolve(true); };
      const onCancel = ()=>{ cleanup(); close(); resolve(false); };
      function cleanup(){ okBtn.removeEventListener('click', onOk); cancelBtn.removeEventListener('click', onCancel); xBtn.removeEventListener('click', onCancel); m.removeEventListener('click', outside); }
      function outside(e){ if(e.target === m){ onCancel(); } }
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
      xBtn.addEventListener('click', onCancel);
      m.addEventListener('click', outside);
      m.classList.add('open');
    });
  }

  // Icon picker (Font Awesome)
  (function(){
    const modal = document.getElementById('icon-picker-modal');
    const grid = document.getElementById('icon-grid');
    const close = document.getElementById('icon-picker-close');
    const trigger = document.getElementById('qa-pick-fa');
    const preview = document.getElementById('qa-icon-preview');
    const input = document.getElementById('qa-icon');

    const icons = [
      'fa-bolt','fa-lightbulb','fa-plug','fa-power-off','fa-fan','fa-sun','fa-moon','fa-temperature-half','fa-tv','fa-display','fa-volume-high','fa-microphone','fa-bell','fa-door-open','fa-lock','fa-mug-hot','fa-music','fa-stopwatch','fa-cloud','fa-cloud-sun','fa-snowflake','fa-droplet','fa-shower','fa-broom','fa-bath','fa-bed','fa-chair','fa-robot','fa-wand-magic-sparkles','fa-star','fa-heart'
    ];
    function build(){
      grid.innerHTML = '';
      icons.forEach(ic => {
        const b = document.createElement('button');
        b.className = 'button';
        b.innerHTML = `<i class="fa-solid ${ic}"></i>`;
        b.addEventListener('click', ()=>{ input.value = `<i class=\"fa-solid ${ic}\"></i>`; preview.innerHTML = `<i class=\"fa-solid ${ic}\"></i>`; modal.classList.remove('open'); });
        grid.appendChild(b);
      });
    }
    build();
    close.addEventListener('click', ()=> modal.classList.remove('open'));
    modal.addEventListener('click', (e)=>{ if(e.target === modal) modal.classList.remove('open'); });
    trigger.addEventListener('click', ()=> modal.classList.add('open'));
    input.addEventListener('input', ()=>{ preview.textContent = input.value; preview.innerHTML = input.value; });
  })();

})();
