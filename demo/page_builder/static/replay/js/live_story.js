
  /* ---- the live story with its start card, and the dots: which parts of the running network answer, each on its own boxes */
  const PART_BOXES = { aggregator: ['mkt'], town: ['town'], community: ['co-fc', 'co-cover', 'co-agent', 'co-market', 'co-desk', 'co-report'],
    homes: ['h-agent'], buildings: ['b-agent'], datacenter: ['site-dc'], buyer_utility: ['buy-u'], buyer_grid: ['buy-g'], model: ['h-model', 'b-model'] };
  const fig = (x, unit) => (x == null ? '' : x.toLocaleString('en-US', { maximumFractionDigits: 1 }) + (unit || ''));
  function startCard(v1) {
    const e = (v1 && v1.event) || {};
    const parts = v1 ? PART_KEYS.filter((k) => v1.parts[k]) : [];
    const up = parts.filter((k) => v1.parts[k].up).length;
    return { kind: 'start', cb: '', l: 0, who: [], in: [], out: [], did: '', rule: '', flow: [], brief: null, big: [], cols: '1fr 1fr',
      term: ['Terminal', 'the real lines of each live moment'],
      cd: [{ h: 'The network', rows: [['Parts answering', parts.length ? up + ' of ' + parts.length : ''], ['Homes', fig(v1 && v1.homes)], ['Buildings', fig(v1 && v1.buildings)]] },
        { h: 'The sale', rows: [['Window', e.window ? e.window[0] + ' to ' + e.window[1] : ''], ['Asked', fig(e.asked, ' kW')], ['Offers', fig(e.offers)],
          ['Accepted', fig(e.accepted)]] }] };
  }
  function makeStory(net) {
    return { id: 'live', live: true, own: true, name: 'Live', one: 'Live: the running network, moment by moment',
      about: 'The running network, moment by moment. It follows the newest moment; Back, a tick or a pin on the timeline shows an earlier one.',
      sent: { who: 'Live', text: '', full: '', plain: '', t: '' }, moments: [], steps: [], touched: (net.boxes || []).slice(), k0: startCard(L.last && L.last.v1) };
  }
  /* a new answer's steps and moments, adopted in order. A step goes to its own place by its number: a gap is held by empty steps
     and a step the story holds already is not taken again, so a moment's steps are always the ones it names */
  function grow(v) {
    const st = L.story;
    if (!st) return;
    const steps = [];
    let at = st.steps.length;
    v.steps.forEach((s) => {
      const i = obj(s) ? whole(s.i, 0, 3000) : null;
      if (i !== null && i < at) return;
      for (; i !== null && at < i; at++) steps.push(step(null, v.timeline.t0));
      steps.push(step(s, v.timeline.t0));
      at++;
    });
    const count = st.steps.length + steps.length;
    const moments = v.moments.map((m) => moment(m, count, v.timeline.t0)).filter(Boolean);
    FG.grow.add(steps, moments);
    if (moments.length) L.newAt = Date.now();
  }
  function dots(v1) {
    const blocks = FG.V.split.blocks;
    Object.keys(PART_BOXES).forEach((k) => {
      const r = v1 && v1.parts[k];
      PART_BOXES[k].forEach((b) => {
        const box = blocks[b];
        if (!box) return;
        if (!box.querySelector(':scope > i.lq')) box.appendChild(el('i', 'lq'));
        box.classList.toggle('lvu', !!r && r.up && r.current !== false);
        box.classList.toggle('lvo', !!r && r.up && r.current === false);
        box.classList.toggle('lvx', !!r && !r.up);
      });
    });
  }
  function clearDots() {
    Object.keys(FG.V.split.blocks).forEach((b) => {
      const box = FG.V.split.blocks[b];
      box.classList.remove('lvu', 'lvo', 'lvx');
      const i = box.querySelector(':scope > i.lq');
      if (i) i.remove();
    });
  }
