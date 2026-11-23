// @state
() => {
  const seen = (e) => !!e && !e.hidden && e.getClientRects().length > 0;
  const q = (s) => document.querySelector(s);
  const text = (s) => (seen(q(s)) ? q(s).innerText.replace(/\s+/g, ' ').trim() : '');
  const pills = [...document.querySelectorAll('.lv-ev')];
  const press = [...document.querySelectorAll('.lv-ev, .lv-qrb, .lv-links a, .lv-card .lv-x')].filter(seen).map((e) => Math.round(e.getBoundingClientRect().height));
  const cut = [...document.querySelectorAll('.lv-bar *, .lv-card *, .lv-flash')].filter((e) => seen(e) && (e.getBoundingClientRect().right > innerWidth + 1 || e.getBoundingClientRect().left < -1))
    .map((e) => e.className);
  const day = q('.lv-day');
  return { live: q('#app').classList.contains('lv'), audience: q('#app').classList.contains('lv-aud'), controls: seen(q('.lv-ctl')), strip: seen(q('#lv-crowd')),
    pills: pills.length, open: pills.filter((b) => !b.disabled).length, votes: pills.map((b) => b.lastChild.textContent).join(','), words: text('.lv-crowd-s'),
    count: text('.lv-crowd-n'), mark: text('.lv-live'), day: text('.lv-day'), dayCut: seen(day) && day.scrollWidth > day.clientWidth + 1, state: text('.lv-state'),
    flash: text('.lv-flash'), card: seen(q('.lv-card')), press: press.length ? Math.min(...press) : 0, cut, sideways: document.documentElement.scrollWidth > innerWidth + 1 };
}

// @says
(words) => document.body.innerText.includes(words)

// @card
() => {
  const q = (s) => document.querySelector(s);
  const svg = q('.lv-qr svg');
  return { head: q('.lv-card h2').textContent, links: [...document.querySelectorAll('.lv-links a')].map((a) => [a.textContent, a.href]),
    lines: [...document.querySelectorAll('.lv-facts li')].map((li) => li.textContent), address: q('.lv-addr').textContent,
    code: svg ? { box: svg.getAttribute('viewBox'), ink: svg.querySelector('path').getAttribute('fill'), paper: svg.querySelector('rect').getAttribute('fill'),
      modules: (svg.querySelector('path').getAttribute('d').match(/M/g) || []).length, images: document.querySelectorAll('.lv-card img').length } : null };
}
