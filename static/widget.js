/* MelodyCare chat widget. Partner usage:
   <script src="https://YOUR-SERVICE.onrender.com/widget.js" data-key="mc_..." data-title="Parent support"></script> */
(function () {
  var me = document.currentScript, key = me.getAttribute('data-key'), base = new URL(me.src).origin;
  var title = me.getAttribute('data-title') || 'Ask us', color = me.getAttribute('data-color') || '#16a34a';
  var host = document.createElement('div'); document.body.appendChild(host);
  var r = host.attachShadow({mode: 'open'}), hist = [], busy = false;
  r.innerHTML = '<style>' +
    '*{box-sizing:border-box;font-family:Segoe UI,system-ui,sans-serif}' +
    '#b{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;background:' + color + ';color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:99999}' +
    '#p{position:fixed;right:20px;bottom:88px;width:360px;max-width:calc(100vw - 24px);height:480px;max-height:calc(100vh - 110px);background:#fff;border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;z-index:99999}' +
    '#h{background:' + color + ';color:#fff;padding:14px 16px;font-weight:700}' +
    '#m{flex:1;overflow-y:auto;padding:12px;font-size:14px;line-height:1.55;color:#1b2f29}' +
    '.u{background:#eaf5ef;padding:8px 12px;border-radius:14px;margin:8px 0 8px auto;width:fit-content;max-width:85%;white-space:pre-wrap}' +
    '.a{margin:8px 0;white-space:pre-wrap}.s{font-size:11px;color:#66796f}' +
    '.c{border:1px solid #f3c969;border-left:5px solid #f3c969;background:#fffbea;border-radius:8px;padding:10px;margin:8px 0;font-size:13px}' +
    '#f{display:flex;gap:6px;padding:8px;border-top:1px solid #e3ede8}#i{flex:1;border:1px solid #d5e3dc;border-radius:18px;padding:8px 12px;font-size:14px;outline:0}' +
    '#s{border:0;background:' + color + ';color:#fff;border-radius:18px;padding:0 14px;cursor:pointer}#s:disabled{opacity:.4}' +
    '#d{font-size:11px;color:#66796f;text-align:center;padding:0 8px 8px}</style>' +
    '<button id="b" aria-label="Open chat">💬</button><div id="p"><div id="h">' + title.replace(/</g, '&lt;') + '</div><div id="m"></div>' +
    '<div id="f"><input id="i" maxlength="600" placeholder="Type your question…"><button id="s">Send</button></div>' +
    '<div id="d">Information only, not medical advice. Powered by MelodyCare.</div></div>';
  var $ = function (id) { return r.getElementById(id); };
  function esc(t) { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function add(cls, html) { var d = document.createElement('div'); d.className = cls; d.innerHTML = html; $('m').appendChild(d); $('m').scrollTop = 1e9; return d; }
  $('b').onclick = function () { var p = $('p'); p.style.display = p.style.display === 'flex' ? 'none' : 'flex'; if (!hist.length && !$('m').children.length) add('a', 'Hello! Ask me about child wellbeing and parenting, or about this organisation.'); };
  async function send() {
    var msg = $('i').value.trim(); if (!msg || busy) return;
    add('u', esc(msg)); $('i').value = ''; busy = true; $('s').disabled = true;
    var w = add('a', '…');
    try {
      var res = await fetch(base + '/api/v1/chat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-API-Key': key}, body: JSON.stringify({message: msg, history: hist})});
      var d = await res.json(); w.remove();
      if (!res.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request failed');
      add('a', esc(d.answer) + (d.sources.length ? '<div class="s">Source: ' + esc(d.sources.join(', ')) + '</div>' : ''));
      if (d.crisis) add('c', 'You are not alone. <b>Helpline HEAL: 15555</b><br>If you are in immediate danger, call your local emergency number.');
      hist.push({role: 'user', content: msg}, {role: 'assistant', content: d.answer}); hist = hist.slice(-6);
    } catch (e) { w.remove(); add('a', esc(e.message)); }
    busy = false; $('s').disabled = false; $('i').focus();
  }
  $('s').onclick = send; $('i').onkeydown = function (e) { if (e.key === 'Enter') send(); };
})();
