
(async function () {
  'use strict';
  /* One state, two views. The split view walks a story moment by moment. The whole picture shows the same story in one tree.
     Nothing here ever scrolls the page or a panel: the only motion is one message on the map, and text and highlights in fixed places.
     Every scenario sits in the page gzip-compressed and base64-encoded, and is inflated the first time it is opened, so all of them fit in one file that needs no server. */
  const $ = (id) => document.getElementById(id);
  const SC = JSON.parse($('fg-sc').textContent);
  const packs = {};
  async function packOf(id) {
    if (!packs[id]) {
      const bin = atob($('fg-sc-' + id).textContent);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
      packs[id] = JSON.parse(text);
    }
    return packs[id];
  }
  let B = await packOf(SC.first);
  let D = B.d;
  $('wz').innerHTML = B.world;
  const qa = (s, r) => Array.from((r || document).querySelectorAll(s));
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem('fg-' + k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem('fg-' + k, v); } catch (e) { /* the page works without it */ } },
  };
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const calm = () => motion.matches;
  const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const BI = D.blocks.map((b) => b.id);
  const BN = {};
  D.blocks.forEach((b) => { BN[b.id] = b; });
  const SPEEDS = [0.5, 1, 1.5, 2];
  const GLYPH = { in: '←', out: '→', think: '◆', calc: '=', sign: '#', tool: '▸', guard: '■', write: '⇒', note: '·' };
  const TWO_WAY = { town: 1, 'co-market': 1, 'h-person': 1, 'b-person': 1 };
  const EXTRA = (BN.mkt ? [['input', 'mkt', 'v']] : [['input', 'buy-u', 'v'], ['input', 'buy-g', 'v']]).concat([['co-market', 'trade', 'v']]);
  const ZOOMS = [0, 0.3, 0.45, 0.6, 0.8, 1, 1.3];
  /* what a kind of arrow means, on hover: the dashed agent-to-tools line is the fallback, not code deciding */
  const EDGE_TIP = { lim: "The utility's limit at the community's connection. Not in these recorded days", skip: "Fallback: the rule's plan, only if the model fails, and counted", person: 'The person writes in, and is told why when the node gives less', sensor: 'What the device reports back', quiet: 'A person only notices the device itself' };

  const CODE_TIP = { skip: 'Code makes the plan and calls the tools. No model is on this path', model: "Only a person's note and the wording of a report go to the model" };
  const isModel = (b) => /-model$/.test(b);
  const tipOf = (kind, a, b) => (D.kind === 'code' && kind === 'skip' ? CODE_TIP.skip : D.kind === 'code' && (isModel(a) || isModel(b)) ? CODE_TIP.model : EDGE_TIP[kind] || '');
  const absent = (b) => !!D.absent && D.absent.indexOf(b) >= 0;
  const NOT_HERE = 'Not in these recorded days';

  const S = { tab: 'split', sc: SC.first, story: 'main', m: -1, view: 'key', read: null, auto: false, speed: 1, zi: 0, token: 0, part: false };
  const FG = { S, D, scale: 1 };
  window.FG = FG;
  let timers = [];
  let raf = 0;

  const story = () => D.stories[S.story];
  const moment = () => { const st = story(); return S.m >= 0 && S.m < st.moments.length ? st.moments[S.m] : null; };
  const ended = () => S.m >= story().moments.length;
  const after = (ms, f) => { const t = setTimeout(f, ms * FG.scale); timers.push(t); return t; };
  const lineBlocks = (l) => (Array.isArray(l[3]) ? l[3] : [l[3]]);
  const hasBlock = (l, i) => lineBlocks(l).indexOf(i) >= 0;
  function stopAll() {
    timers.forEach(clearTimeout);
    timers = [];
    cancelAnimationFrame(raf);
    S.token++;
    $('pill').hidden = true;
  }

