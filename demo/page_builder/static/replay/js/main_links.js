  /* ---------- drawing the connectors, for any view that has block rectangles */
  function route(kind, a, b, A, B, G) {
    const home = a[0] === 'h';
    if (G.three && (a.slice(0, 5) === 'site-' || b.slice(0, 5) === 'site-')) {
      const s = a.slice(0, 5) === 'site-' ? A : B;
      const top = G.pt[a.slice(0, 5) === 'site-' ? a : b];
      const up = [[s.x + s.w / 2, G.t1 || top === undefined ? s.y : top], [s.x + s.w / 2, G.t1 ? G.townB : G.buyB]];
      return a.slice(0, 5) === 'site-' ? up : up.reverse();
    }
    if (G.three && kind === 'h' && Math.abs(A.y - B.y) > 6) {
      const my = (A.y + A.h + B.y) / 2;
      return [[A.x + A.w / 2, A.y + A.h], [A.x + A.w / 2, my], [B.x + B.w / 2, my], [B.x + B.w / 2, B.y]];
    }
    if (G.three && kind === 'lim') {
      const U = a === 'utl' ? A : B;
      const ux = U.x + 18;
      const x = Math.min(ux, G.coR - 14);
      const my = G.buyB + 14;
      const pts = x === ux ? [[ux, U.y + U.h], [ux, G.coTop]] : [[ux, U.y + U.h], [ux, my], [x, my], [x, G.coTop]];
      return a === 'utl' ? pts : pts.reverse();
    }
    if (kind === 'h') {
      const y = A.y + A.h / 2;
      return A.x < B.x ? [[A.x + A.w, y], [B.x, y]] : [[A.x, y], [B.x + B.w, y]];
    }
    if (kind === 'v' || kind === 'quiet') {
      const down = A.y < B.y;
      const T = down ? A : B;
      const U = down ? B : A;
      if (G.limX && (a === 'trade' || b === 'trade')) {
        /* in the tree in three levels the trade's line turns just above the coordinator's row, under the level the buyers' orders run along */
        const my = U.y - 26;
        const pts = [[T.x + T.w / 2, T.y + T.h], [T.x + T.w / 2, my], [U.x + U.w / 2, my], [U.x + U.w / 2, U.y]];
        return down ? pts : pts.reverse();
      }
      const lo = Math.max(T.x, U.x);
      const hi = Math.min(T.x + T.w, U.x + U.w);
      let pts;
      if (hi - lo > 8) {
        const n = T.w < U.w ? T : U;
        const x = clamp(n.x + n.w / 2, lo + 4, hi - 4);
        pts = [[x, T.y + T.h], [x, U.y]];
      } else {
        const my = (T.y + T.h + U.y) / 2;
        pts = [[T.x + T.w / 2, T.y + T.h], [T.x + T.w / 2, my], [U.x + U.w / 2, my], [U.x + U.w / 2, U.y]];
      }
      return down ? pts : pts.reverse();
    }
    if (kind === 'railL' || kind === 'railR') {
      /* on the map in three levels the utility stands on the right, so both buyers' orders run down the left rail */
      const left = kind === 'railL' || !!G.lv;
      const x = left ? G.railL : G.railR;
      if (G.railY) {
        const x0 = A.x + A.w * (left ? 0.3 : 0.7);
        return [[x0, A.y + A.h], [x0, G.railY], [x, G.railY], [x, B.y]];
      }
      return [[x, A.y + A.h], [x, B.y]];
    }
    if (kind === 'lim') {
      /* the utility's limit. On the map it comes straight down onto the community coordinator's band. In the tree it runs down a free lane, right of the trade, and in to its block */
      const U = a === 'utl' ? A : B;
      const T = a === 'utl' ? B : A;
      let pts;
      if (G.limX) {
        const tx = clamp(G.limX, T.x + 60, T.x + T.w - 60);
        pts = tx === G.limX ? [[tx, U.y + U.h], [tx, T.y]] : [[G.limX, U.y + U.h], [G.limX, T.y - 34], [tx, T.y - 34], [tx, T.y]];
      } else {
        const x = G.coR ? clamp(U.x + U.w - 13, G.coL + 12, G.coR - 10) : U.x + U.w - 13;
        pts = [[x, U.y + U.h], [x, G.coTop || T.y]];
      }
      return a === 'utl' ? pts : pts.reverse();
    }
    if (kind === 'skip') {
      const x = home ? G.skipH : G.skipB;
      const ax = home ? A.x + A.w : A.x;
      const bx = home ? B.x + B.w : B.x;
      const ay = A.y + A.h * 0.72;
      const by = B.y + B.h * 0.28;
      return [[ax, ay], [x, ay], [x, by], [bx, by]];
    }
    if (kind === 'sensor' || kind === 'person') {
      const x = kind === 'sensor' ? (home ? G.sensH : G.sensB) : (home ? G.persH : G.persB);
      const ax = home ? A.x : A.x + A.w;
      const bx = home ? B.x : B.x + B.w;
      const ay = A.y + A.h / 2;
      const by = B.y + B.h * (kind === 'sensor' ? 0.72 : 0.28);
      return [[ax, ay], [x, ay], [x, by], [bx, by]];
    }
    if (kind === 'ret') {
      const ax = home ? A.x + A.w : A.x;
      const ay = A.y + A.h / 2;
      const bx = B.x + B.w / 2;
      return [[ax, ay], [G.retX, ay], [G.retX, G.retY], [bx, G.retY], [bx, B.y]];
    }
    return [[A.x + A.w / 2, A.y + A.h / 2], [B.x + B.w / 2, B.y + B.h / 2]];
  }
  const dOf = (pts) => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  function arrow(p, q, s) {
    const dx = q[0] - p[0];
    const dy = q[1] - p[1];
    const n = Math.hypot(dx, dy) || 1;
    const ux = dx / n;
    const uy = dy / n;
    const a = [q[0] - ux * s * 1.5 - uy * s * 0.8, q[1] - uy * s * 1.5 + ux * s * 0.8];
    const b = [q[0] - ux * s * 1.5 + uy * s * 0.8, q[1] - uy * s * 1.5 - ux * s * 0.8];
    return 'M' + q[0].toFixed(1) + ' ' + q[1].toFixed(1) + 'L' + a[0].toFixed(1) + ' ' + a[1].toFixed(1) + 'L' + b[0].toFixed(1) + ' ' + b[1].toFixed(1) + 'Z';
  }
  function drawLinks(view) {
    const R = view.R;
    const G = view.G;
    const edges = D.edges.concat(view.extra ? EXTRA : []);
    const code = D.kind === 'code';
    let h = '';
    view.pts = {};
    edges.forEach((e) => {
      const a = e[0];
      const b = e[1];
      const kind = e[2];
      if (!R[a] || !R[b]) return;
      const pts = route(kind, a, b, R[a], R[b], G);
      view.pts[a + '>' + b] = pts;
      view.pts[b + '>' + a] = pts.slice().reverse();
      const s = view.arrow;
      let mk = '';
      if (kind !== 'quiet') {
        mk = arrow(pts[pts.length - 2], pts[pts.length - 1], s);
        if (TWO_WAY[a] || TWO_WAY[b]) mk += arrow(pts[1], pts[0], s);
      }
      const words = tipOf(kind, a, b);
      const tip = words ? '<title>' + esc(words) + '</title>' : '';
      h += '<path class="lk ' + kind + (code && (isModel(a) || isModel(b)) ? ' ml' : '') + '" data-e="' + a + '>' + b + '" d="' + dOf(pts) + '">' + tip + '</path>';
      if (mk) h += '<path class="mk" data-e="' + a + '>' + b + '" d="' + mk + '"/>';
    });
    view.svg.innerHTML = h;
    view.els = {};
    qa('[data-e]', view.svg).forEach((el) => { const k = el.getAttribute('data-e'); (view.els[k] = view.els[k] || []).push(el); });
  }
  function edgeEls(view, a, b) { return view.els[a + '>' + b] || view.els[b + '>' + a] || []; }
  function setEdges(view, hops, cls) {
    Object.keys(view.els).forEach((k) => view.els[k].forEach((el) => el.classList.remove(cls)));
    hops.forEach((p) => { for (let i = 0; i + 1 < p.length; i++) edgeEls(view, p[i], p[i + 1]).forEach((el) => el.classList.add(cls)); });
  }
  function domView(host, svg, extra) {
    const v = { host, svg, extra, arrow: 5, R: {}, G: {}, blocks: {}, pts: {}, els: {} };
    qa('.blk[data-b]', host).forEach((el) => { v.blocks[el.getAttribute('data-b')] = el; });
    return v;
  }
