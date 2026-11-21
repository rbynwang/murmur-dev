/* Small steps the page checks take inside a page. Each snippet is one function expression, called with the argument a check
   passes. The page's own script object is window.FG: FG.go(i, play) shows moment i (-1 is the opening card), FG.setTab(name)
   opens a view ('split', 'whole', 'long' for the Full record, 'res' for a year's results), FG.D holds the evening shown. */

// @fonts
() => (document.fonts && document.fonts.ready) ? document.fonts.ready.then(() => 1) : 1;

// @tabs
/* the ids of the bar's tabs a visitor can see */
() => [...document.querySelectorAll('#bar .tab')].filter((e) => { const c = getComputedStyle(e); return c.display !== 'none' && c.visibility !== 'hidden'; }).map((e) => e.id);

// @fit_state
/* the state the page's measured fit put the diagram in: [data-fit, data-fitw] */
() => { const m = document.getElementById('map'); return m ? [m.getAttribute('data-fit'), m.getAttribute('data-fitw')] : [null, null]; };

// @live_on
() => !!document.querySelector('#app.lv');

// @data_on
/* whether the Data view is on, as on a page that opens on it */
() => !!document.querySelector('#app.dv');

// @evenings
/* the ids of the evenings a page holds (a year's page holds several) */
() => { try { return JSON.parse(document.getElementById('fg-sc').textContent).list.map((s) => s.id); } catch (e) { return []; } };

// @choose_evening
/* a click on the chip of evening `id` */
(id) => { const e = [...document.querySelectorAll('[data-sc], #strip button, .strip button, .chip[data-s]')].find((x) => x.getAttribute('data-sc') === id || x.dataset.id === id || x.getAttribute('data-s') === id); if (e) e.click(); };

// @moment_count
() => (window.FG && FG.D && FG.D.stories && FG.D.stories.main) ? FG.D.stories.main.moments.length : 0;

// @go
(i) => FG.go(i, false);

// @set_tab
(t) => FG.setTab(t);

// @pos
/* the replay's position as the bar shows it, such as "5 of 38" */
() => document.getElementById('pos').textContent;
