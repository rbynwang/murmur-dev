/* The recorded evening: eight moments of the replay, stepped with the buttons, the cards, or the left and right arrow keys while the section is on screen. */
(function () {
  var sec = document.getElementById('evening');
  if (!sec) return;
  var imgs = [].slice.call(sec.querySelectorAll('.stage img'));
  var steps = [].slice.call(sec.querySelectorAll('.steps li'));
  var now = document.getElementById('now'), rc = document.getElementById('rc');
  var i = 0;
  function txt(el, sel) { var x = el.querySelector(sel); return x ? x.textContent : ''; }
  function show(n) {
    i = (n + steps.length) % steps.length;
    imgs.forEach(function (im, k) { im.classList.toggle('on', k === i); });
    steps.forEach(function (s, k) { s.classList.toggle('on', k === i); });
    var s = steps[i];
    now.querySelector('.sn').textContent = txt(s, '.sn');
    now.querySelector('b').textContent = txt(s, 'b');
    now.querySelector('.st').textContent = txt(s, '.st');
    now.querySelector('p').textContent = txt(s, 'p');
    rc.textContent = (i + 1) + ' of ' + steps.length;
  }
  steps.forEach(function (s, k) {
    s.querySelector('button').addEventListener('click', function () { show(k); sec.querySelector('.rp').scrollIntoView({ block: 'start' }); });
  });
  document.getElementById('rb').addEventListener('click', function () { show(i - 1); });
  document.getElementById('rn').addEventListener('click', function () { show(i + 1); });
  document.addEventListener('keydown', function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    var r = sec.querySelector('.stage').getBoundingClientRect();
    if (r.top > innerHeight * 0.75 || r.bottom < innerHeight * 0.25) return;
    if (e.key === 'ArrowRight') { show(i + 1); e.preventDefault(); }
    if (e.key === 'ArrowLeft') { show(i - 1); e.preventDefault(); }
  });
  show(0);
})();
