/* Shows the logged-in parent's child(ren) above the chat, with quick questions. Needs /api/me/children. */
(async function () {
  var token = localStorage.getItem('melodycare_token'), msgs = document.getElementById('messages');
  if (!token || !msgs) return;
  var kids;
  try {
    var r = await fetch('/api/me/children', {headers: {Authorization: 'Bearer ' + token}});
    if (!r.ok) return;
    kids = await r.json();
  } catch (e) { return; }
  if (!kids.length) return;

  var css = document.createElement('style');
  css.textContent =
    '.kc{background:var(--primary-light,#e8f6ee);border-bottom:1px solid var(--border,#d8e8e0);padding:12px 20px;font-size:14px}' +
    '.kc-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}' +
    '.kc-av{width:34px;height:34px;border-radius:50%;background:var(--primary,#16a34a);color:#fff;display:grid;place-items:center;font-weight:700}' +
    '.kc-name{font-weight:700;font-size:15px}.kc-meta{color:var(--muted,#5b6f68)}' +
    '.kc select,.kc-tog{margin-left:auto;border:1px solid var(--border,#cfe3d8);background:#fff;border-radius:8px;padding:4px 10px;font:inherit;font-size:13px;cursor:pointer}' +
    '.kc-pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}' +
    '.kc-pill{background:#fff;border:1px solid var(--border,#cfe3d8);border-radius:999px;padding:3px 12px;font-size:13px}' +
    '.kc-det{display:none;margin-top:8px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:6px 16px}' +
    '.kc-det.open{display:grid}.kc-det b{color:var(--muted,#5b6f68);font-weight:600}' +
    '.kc-chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}' +
    '.kc-chip{background:#fff;border:1px solid var(--primary,#16a34a);color:var(--primary-dark,#15803d);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}' +
    '.kc-chip:hover{background:var(--primary,#16a34a);color:#fff}';
  document.head.appendChild(css);

  var card = document.createElement('div');
  card.className = 'kc';
  card.setAttribute('aria-label', 'About your child');
  msgs.parentNode.insertBefore(card, msgs);

  function fmt(iso) { return iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'}) : '–'; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  function render(k) {
    card.textContent = '';
    var top = el('div', 'kc-top');
    top.appendChild(el('div', 'kc-av', (k.name || '?').charAt(0).toUpperCase()));
    top.appendChild(el('span', 'kc-name', k.name));
    top.appendChild(el('span', 'kc-meta', [k.age != null ? k.age + ' yrs' : null, k.gender].filter(Boolean).join(' · ')));
    if (kids.length > 1) {
      var sel = el('select');
      kids.forEach(function (c, i) { var o = el('option', null, c.name); o.value = i; if (c.id === k.id) o.selected = true; sel.appendChild(o); });
      sel.onchange = function () { render(kids[sel.value]); };
      top.appendChild(sel);
    }
    var tog = el('button', 'kc-tog', 'Details ▾'); tog.type = 'button';
    top.appendChild(tog);
    card.appendChild(top);

    var pills = el('div', 'kc-pills');
    if (k.treatment_days != null) pills.appendChild(el('span', 'kc-pill', 'Day ' + k.treatment_days + ' of treatment'));
    pills.appendChild(el('span', 'kc-pill', k.sessions + (k.sessions === 1 ? ' session' : ' sessions') + ' recorded'));
    if (k.next_appointment) pills.appendChild(el('span', 'kc-pill', 'Next: ' + fmt(k.next_appointment.date) + ', ' + k.next_appointment.time));
    card.appendChild(pills);

    var det = el('div', 'kc-det');
    [['Diagnosis', k.diagnosis || '–'], ['Therapist', k.therapist || '–'], ['Treatment started', fmt(k.treatment_start)], ['Last session', fmt(k.last_session)],
     ['Next appointment', k.next_appointment ? k.next_appointment.type + ' with ' + k.next_appointment.therapist : 'None booked']].forEach(function (p) {
      var row = el('div'); row.appendChild(el('b', null, p[0] + ': ')); row.appendChild(document.createTextNode(p[1])); det.appendChild(row);
    });
    card.appendChild(det);
    tog.onclick = function () { var o = det.classList.toggle('open'); tog.textContent = o ? 'Details ▴' : 'Details ▾'; };

    var first = (k.name || 'my child').split(' ')[0];
    var chips = el('div', 'kc-chips');
    ['How is ' + first + ' progressing?', 'What can I try at home with ' + first + '?',
     'What should I ask ' + (k.therapist || 'the therapist') + ' at the next session?'].forEach(function (q) {
      var b = el('button', 'kc-chip', q); b.type = 'button';
      b.onclick = function () { var i = document.getElementById('msgInput'); if (i) { i.value = q; i.focus(); } };
      chips.appendChild(b);
    });
    card.appendChild(chips);
  }
  render(kids[0]);
})();
