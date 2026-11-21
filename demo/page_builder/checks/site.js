/* What the site check reads inside a page. Each snippet is one function expression. */

// @text
/* the words on screen */
() => document.body.innerText;

// @has_replay
() => !!(window.FG && FG.D && FG.D.stories);

// @section_buttons
/* the labels of the whole picture's own buttons that are on screen */
() => [...document.querySelectorAll('button.zb')].filter(b => b.getBoundingClientRect().width > 0).map(b => b.textContent.trim()).filter(x => x.length > 2);

// @town_chips
/* the status chips of the message network's panel */
() => [...document.querySelectorAll('#a-town .lstat .st')].map(e => e.textContent);

// @links
() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
