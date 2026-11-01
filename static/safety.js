/* Shared by user.html and guest.html: first-visit disclaimer + crisis card. */
(function () {
  var css = document.createElement('style');
  css.textContent =
    '#mcDisc{position:fixed;inset:0;background:rgba(15,40,30,.55);display:none;align-items:center;justify-content:center;z-index:999;padding:20px}' +
    '#mcDisc .mc-box{background:#fff;max-width:440px;border-radius:14px;padding:28px;font-family:inherit;line-height:1.6;color:#1b2f29}' +
    '#mcDisc h3{margin:0 0 10px;font-size:20px}#mcDisc p{margin:0 0 10px;font-size:14.5px}' +
    '#mcDisc button{width:100%;margin-top:8px;padding:12px;border:0;border-radius:10px;background:#16a34a;color:#fff;font-weight:700;font-size:15px;cursor:pointer}' +
    '.mc-crisis{border:1px solid #f3c969;border-left:6px solid #f3c969;background:#fffbea;border-radius:10px;padding:14px 16px;margin:10px 0;font-size:14.5px;line-height:1.6;color:#1b2f29}' +
    '.mc-crisis b{font-size:18px;display:block;margin:2px 0}';
  document.head.appendChild(css);

  var d = document.createElement('div');
  d.id = 'mcDisc';
  d.setAttribute('role', 'dialog');
  d.setAttribute('aria-modal', 'true');
  d.innerHTML = '<div class="mc-box"><h3>Before you start</h3>' +
    '<p>This assistant gives information and emotional support only. It does <b>not</b> diagnose or replace a psychologist or doctor.</p>' +
    '<p>Your messages are processed by an AI service. Please do not share your IC number, address or other identifying details.</p>' +
    '<p>If you or someone else is in danger, call Helpline HEAL <b>15555</b> or your local emergency number.</p>' +
    '<button id="mcDiscBtn">I understand</button></div>';
  document.body.appendChild(d);

  function seen() { try { return localStorage.getItem('mc_disc') === '1'; } catch (e) { return false; } }
  if (!seen()) d.style.display = 'flex';
  document.getElementById('mcDiscBtn').onclick = function () {
    try { localStorage.setItem('mc_disc', '1'); } catch (e) {}
    d.style.display = 'none';
  };

  window.showCrisisCard = window.showCrisisCard || function () {
    var box = document.getElementById('messages');
    if (!box) return;
    var c = document.createElement('div');
    c.className = 'mc-crisis';
    c.innerHTML = 'You are not alone, and help is available right now.<b>Helpline HEAL: 15555</b>' +
      'If you are in immediate danger, call your local emergency number.';
    box.appendChild(c);
    box.scrollTop = box.scrollHeight;
  };
})();
