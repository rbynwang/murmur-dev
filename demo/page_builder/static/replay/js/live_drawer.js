
  /* ---- the surprises drawer, over the map's upper right corner: a kind, who it is for, its fields at their defaults, and Send.
     Two presses make a surprise: Surprise, then Send. A form outside its limits posts nothing. */
  const WORDS = { note: "Owner's note", car_now: 'Car needed now', weather: 'Weather change', building_closed: 'Building closes',
    building_need: 'Building needs power', emergency: 'Grid emergency', battery_fault: 'Battery fault', battery_low: 'Battery low' };
  const WHO = { note: 'homes', car_now: 'homes', building_closed: 'buildings', building_need: 'buildings', battery_fault: 'battery', battery_low: 'battery', emergency: 'buyers' };
  /* field: label, least, most, default, step */
  const FIELDS = { weather: [['pv', 'Sun, share', 0, 1, 0.2, 0.05], ['load', 'Load, times', 0.5, 2, 1.3, 0.1], ['dT', 'Warmer by, °C', -10, 10, 6, 1], ['hours', 'For, hours', 0.5, 24, 3, 0.5]],
    building_need: [['share', 'Zone back, share', 0.05, 1, 0.25, 0.05], ['hours', 'For, hours', 0.5, 6, 3.5, 0.5]],
    emergency: [['kw', 'kW', 1, 2000, 20, 1], ['minutes', 'Minutes', 15, 240, 60, 15]], battery_low: [['pct', 'Charge, %', 5, 100, 10, 5]] };
  const DR = { kind: 'note' };
  function drawerBuild() {
    const d = el('div', 'lv-drawer');
    d.id = 'lv-drawer';
    d.hidden = true;
    d.setAttribute('role', 'dialog');
    d.setAttribute('aria-label', 'Trigger a surprise');
    const kinds = el('div', 'lv-kinds');
    KINDS.forEach((k) => {
      const b = btn('lv-kind', WORDS[k]);
      b.dataset.kind = k;
      b.addEventListener('click', () => { DR.kind = k; drawerFill(); });
      kinds.appendChild(b);
    });
    DR.form = el('div', 'lv-form');
    DR.send = btn('lv-b lv-send', 'Send');
    DR.send.addEventListener('click', drawerSend);
    const close = btn('lv-x', '×', 'Close');
    close.addEventListener('click', () => drawerToggle(false));
    [kinds, DR.form, DR.send, close].forEach((x) => d.appendChild(x));
    $('split').appendChild(d);
    DR.box = d;
  }
  function drawerToggle(on) {
    if (!DR.box) return;
    const open = on === undefined ? DR.box.hidden : on;
    DR.box.hidden = !open;
    B.sur.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) { drawerFill(); DR.send.focus(); }
  }
  function choices(kind) {
    const r = (L.console && L.console.state && L.console.state.roster) || {};
    const pick = WHO[kind];
    if (pick === 'buyers') return (r.buyers || []).map((b) => [b, b === 'utility' ? 'The utility' : b === 'grid-operator' ? 'The grid operator' : b]);
    if (pick === 'buildings') return (r.buildings || []).map((b) => [b.id, b.name]);
    if (pick === 'battery') return (r.homes || []).filter((h) => h.battery).map((h) => [h.id, h.name]);
    return pick ? (r.homes || []).map((h) => [h.id, h.name]) : [];
  }
  function drawerFill() {
    const f = DR.form, k = DR.kind;
    f.textContent = '';
    DR.box.querySelectorAll('.lv-kind').forEach((b) => b.setAttribute('aria-pressed', b.dataset.kind === k ? 'true' : 'false'));
    const who = choices(k);
    if (WHO[k]) {
      const s = el('select', 'lv-who');
      s.id = 'lv-who';
      s.setAttribute('aria-label', 'For');
      who.forEach((x) => { const o = el('option', '', x[1]); o.value = x[0]; s.appendChild(o); });
      f.appendChild(s);
    }
    if (k === 'note') {
      const t = el('input', 'lv-text');
      t.type = 'text';
      t.maxLength = 200;
      t.value = 'Please keep the battery full tonight.';
      t.setAttribute('aria-label', 'The note');
      f.appendChild(t);
    }
    (FIELDS[k] || []).forEach((x) => {
      const lab = el('label', 'lv-num', x[1]);
      const i = el('input');
      i.type = 'number';
      i.min = x[2];
      i.max = x[3];
      i.step = x[5];
      i.value = x[4];
      i.dataset.f = x[0];
      lab.appendChild(i);
      f.appendChild(lab);
    });
    DR.send.disabled = !!WHO[k] && !who.length;
  }
  function drawerSend() {
    const k = DR.kind, body = { do: 'surprise', kind: k }, f = DR.form;
    const who = f.querySelector('.lv-who');
    if (who) body[WHO[k] === 'buyers' ? 'buyer' : 'who'] = who.value;
    const t = f.querySelector('.lv-text');
    if (t) { const v = t.value.trim(); if (!v || v.length > 200) return; body.text = v; }
    let ok = true;
    (FIELDS[k] || []).forEach((x) => {
      const i = f.querySelector('[data-f="' + x[0] + '"]'), v = Number(i.value);
      if (!isFinite(v) || v < x[2] || v > x[3]) { ok = false; i.setAttribute('aria-invalid', 'true'); } else { body[x[0]] = v; i.removeAttribute('aria-invalid'); }
    });
    if (!ok) return;
    L.send(body);
    drawerToggle(false);
  }
