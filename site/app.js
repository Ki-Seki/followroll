// Renders the list that following.py embeds in the page. Everything in it comes
// from other people's feeds, so every string is escaped and every link must be
// http(s).

const PAGE = 30;          // posts added per "show more"
const PEOPLE = 12;        // people listed before "show all"
const DAY = 86400;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const link = url => (/^https?:\/\//i.test(url || '') ? esc(url) : '#');
const github = login => `https://github.com/${encodeURIComponent(login)}`;
const age = iso => (Date.now() - Date.parse(iso)) / 1000;

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
function ago(iso) {
  const d = age(iso);
  if (d < 3600) return relative.format(-Math.max(1, Math.round(d / 60)), 'minute');
  if (d < DAY) return relative.format(-Math.round(d / 3600), 'hour');
  if (d < 30 * DAY) return relative.format(-Math.round(d / DAY), 'day');
  if (d < 365 * DAY) return relative.format(-Math.round(d / (30 * DAY)), 'month');
  return new Date(iso).toLocaleDateString('en', { year: 'numeric', month: 'short', day: 'numeric' });
}
const exact = iso => new Date(iso).toLocaleString('en', { dateStyle: 'medium', timeStyle: 'short' });
const time = iso => `<time datetime="${esc(iso)}" title="${esc(exact(iso))}">${esc(ago(iso))}</time>`;

// How recently someone posted, 0 (over a year ago) to 4 (this week)
function heat(iso) {
  const d = age(iso) / DAY;
  return d < 7 ? 4 : d < 30 ? 3 : d < 180 ? 2 : d < 365 ? 1 : 0;
}

function period(iso) {
  const d = age(iso) / DAY;
  if (d < 7) return 'This week';
  if (d < 30) return 'This month';
  if (d < 365) return 'This year';
  return String(new Date(iso).getFullYear());
}

// "Ke Fang", "Ke Fang and Arthur", "Ke Fang, Arthur and 2 more"
function names(via, count) {
  const shown = via.slice(0, 2).map(v => v.name), more = count - shown.length;
  if (more > 0) return `${shown.join(', ')} and ${more} more`;
  return shown.join(' and ');
}

const ICON = {
  talk: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M2.5 3.5h11V11H7l-3 2.5V11H2.5z"/></svg>',
  heart: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M8 13.5S2.5 10.3 2.5 6.2A2.9 2.9 0 0 1 8 5a2.9 2.9 0 0 1 5.5 1.2c0 4.1-5.5 7.3-5.5 7.3z"/></svg>',
  feed: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 8.2a4.8 4.8 0 0 1 4.8 4.8M3 3.5A9.5 9.5 0 0 1 12.5 13"/><circle cx="3.6" cy="12.4" r=".9" fill="currentColor" stroke="none"/></svg>',
  page: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M5.5 6h5M5.5 8.5h5M5.5 11h3"/></svg>',
  site: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5c1.8 1.6 1.8 9.4 0 11M8 2.5c-1.8 1.6-1.8 9.4 0 11"/></svg>',
  arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h10M9.5 4.5 13 8l-3.5 3.5"/></svg>',
  github: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>',
};

const narrow = matchMedia('(max-width: 880px)');
const data = JSON.parse(document.getElementById('data').textContent);
const app = document.getElementById('app');
const state = { view: 'following', who: null, shown: PAGE, everyone: false };

// The address keeps the view and the person: #discover, #by=login, #discover&by=login
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  state.view = q.has('about') ? 'about' : q.has('discover') && data.discover ? 'discover' : 'following';
  state.who = q.get('by');
}
function writeHash() {
  const parts = [state.view === 'following' ? '' : state.view, state.who ? `by=${encodeURIComponent(state.who)}` : ''].filter(Boolean);
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : location.pathname + location.search);
}

const list = () => (state.view === 'discover' ? data.discover : data);

// Every post of a list, newest first, each with its author. Worked out once.
function timeline(of) {
  of.timeline ??= of.blogs.flatMap(b => b.posts.map(p => ({ ...p, login: b.login, name: b.name, avatar: b.avatar })))
    .sort((a, b) => b.ts - a.ts);
  return of.timeline;
}

function personHTML(b) {
  const on = state.who === b.login;
  // In the narrow side column: "via Ke Fang +2" rather than a list of names
  const note = b.via ? `via ${b.via[0].name}${b.via_count > 1 ? ` +${b.via_count - 1}` : ''}` : b.host;
  return `<div class="person heat${heat(b.posts[0].date)}${on ? ' on' : ''}">
<button class="pick" type="button" data-login="${esc(b.login)}" aria-pressed="${on}" title="${esc(b.name)} · ${esc(b.host)} · last post ${esc(ago(b.posts[0].date))}">
<span class="face"><img src="${link(b.avatar)}" alt="" width="36" height="36" loading="lazy"></span>
<span class="id"><b>${esc(b.name)}</b><em>${esc(b.name.split(/\s+/)[0])}</em><small>${esc(note)}</small></span>
<span class="months" aria-hidden="true">${b.months.map(n => `<i class="m${Math.min(n, 4)}"></i>`).join('')}</span>
</button>
<a class="gh" href="${github(b.login)}" target="_blank" rel="noopener" title="@${esc(b.login)} on GitHub" aria-label="${esc(b.name)} on GitHub">${ICON.github}</a>
</div>`;
}

// Likes and comments wherever they could be counted, plus the Hacker News thread.
function statsHTML(p) {
  const t = p.thread, hn = p.hn, out = [];
  const where = t ? `on ${t.source === 'disqus' ? 'Disqus' : t.source === 'twikoo' ? 'the post' : 'GitHub'}` : '';
  if (t && t.likes) out.push(`<a class="stat" href="${link(t.url)}" target="_blank" rel="noopener" title="${t.likes} ${t.likes === 1 ? 'like' : 'likes'} ${where}">${ICON.heart}${t.likes}</a>`);
  if (t && t.comments) out.push(`<a class="stat" href="${link(t.url)}" target="_blank" rel="noopener" title="${t.comments} ${t.comments === 1 ? 'comment' : 'comments'} ${where}">${ICON.talk}${t.comments}</a>`);
  if (hn) out.push(`<a class="stat hn" href="${link(hn.url)}" target="_blank" rel="noopener" title="${hn.points} points and ${hn.comments} comments on Hacker News"><i>Y</i>${hn.points}</a>`);
  return out.join('');
}

function postHTML(p, blog) {
  const extras = statsHTML(p) + (blog && blog.via ? `<span class="via">Followed by ${esc(names(blog.via, blog.via_count))}</span>` : '');
  return `<article class="post">
<img src="${link(p.avatar)}" alt="" width="36" height="36" loading="lazy">
<div>
<div class="meta"><a href="${github(p.login)}" target="_blank" rel="noopener" title="@${esc(p.login)} on GitHub">${esc(p.name)}</a><span>${esc(new URL(p.url).host.replace(/^www\./, ''))}</span>${time(p.date)}</div>
<h3><a href="${link(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></h3>
${p.summary ? `<p>${esc(p.summary)}</p>` : ''}
${extras ? `<div class="extras">${extras}</div>` : ''}
</div></article>`;
}

function feedHTML() {
  const { blogs } = list(), everything = timeline(list());
  const byLogin = new Map(blogs.map(b => [b.login, b]));
  const who = byLogin.get(state.who);
  let posts = everything;
  if (who) posts = who.posts.map(p => ({ ...p, login: who.login, name: who.name, avatar: who.avatar }));
  // Discover is for meeting people: each shows their newest post only.
  else if (state.view === 'discover') posts = everything.filter((p, i) => everything.findIndex(q => q.login === p.login) === i);
  const shown = posts.slice(0, state.shown);
  let html = '', last = null;
  for (const p of shown) {
    const label = period(p.date);
    if (label !== last) { html += `<h2>${label}</h2>`; last = label; }
    html += postHTML(p, state.view === 'discover' ? byLogin.get(p.login) : null);
  }
  if (!posts.length) html += '<p class="empty">Nothing here yet.</p>';
  if (posts.length > shown.length)
    html += `<button class="more" type="button" data-do="more">Show ${Math.min(PAGE, posts.length - shown.length)} more</button>`;
  return html;
}

function peopleHTML() {
  const { blogs } = list();
  // The narrow layout shows people as one scrolling row, so it takes them all;
  // so does the wide one, unless the list is long.
  const all = state.everyone || narrow.matches || blogs.length <= 20;
  const shown = all ? blogs : blogs.slice(0, PEOPLE);
  return `<div class="side-head"><h2>${state.view === 'discover' ? 'People to discover' : 'People'}</h2><span>${blogs.length}</span>
<span class="key">Posts a month, past year</span></div>
<div class="people">${shown.map(personHTML).join('')}</div>
${blogs.length > shown.length ? `<button class="all" type="button" data-do="everyone">Show all ${blogs.length}</button>` : ''}`;
}

// Who follows whom, drawn from the list itself: the owner, a few of the people
// they follow, and the people those follow who rank highest on Discover.
function graphSVG() {
  if (!data.discover) return '';
  // As many of the top-ranked as can be shown with every one of their links:
  // at most four people in the middle, four at the end.
  const found = [], middle = [];
  for (const blog of data.discover.blogs) {
    const added = blog.via.filter(via => !middle.some(m => m.login === via.login));
    if (found.length === 4 || middle.length + added.length > 4) continue;
    found.push(blog);
    middle.push(...added);
  }
  if (!found.length) return '';
  // Narrow screens get their own, tighter drawing rather than a shrunken one.
  const small = narrow.matches;
  const width = small ? 350 : 680, height = small ? 250 : 232, columns = small ? [26, 100, 174] : [44, 270, 470];
  const spread = (count, i) => 32 + (height - 64) * (count === 1 ? 0.5 : i / (count - 1));
  const you = { x: columns[0], y: height / 2 }, clips = [], faces = [], lines = [];
  const face = (x, y, r, src, id) => {
    clips.push(`<clipPath id="face-${id}"><circle cx="${x}" cy="${y}" r="${r}"/></clipPath>`);
    faces.push(`<circle cx="${x}" cy="${y}" r="${r + 2.5}" class="rim"/><image href="${link(src)}" x="${x - r}" y="${y - r}" width="${r * 2}" height="${r * 2}" clip-path="url(#face-${id})" preserveAspectRatio="xMidYMid slice"/>`);
  };
  const curve = (a, b, strong) => lines.push(`<path d="M${a.x} ${a.y} C${(a.x + b.x) / 2} ${a.y} ${(a.x + b.x) / 2} ${b.y} ${b.x} ${b.y}"${strong ? ' class="strong"' : ''}/>`);
  const mids = middle.map((via, i) => ({ ...via, x: columns[1], y: spread(middle.length, i) }));
  const ends = found.map((blog, i) => ({ blog, x: columns[2], y: spread(found.length, i) }));
  for (const mid of mids) curve(you, mid, false);
  for (const end of ends) for (const mid of mids) if (end.blog.via.some(via => via.login === mid.login)) curve(mid, end, end.blog.via_count > 1);
  face(you.x, you.y, small ? 18 : 24, data.owner.avatar, 'you');
  mids.forEach((mid, i) => face(mid.x, mid.y, small ? 15 : 17, `https://github.com/${encodeURIComponent(mid.login)}.png?size=72`, `m${i}`));
  const names = ends.map((end, i) => {
    face(end.x, end.y, small ? 15 : 17, end.blog.avatar, `e${i}`);
    const by = end.blog.via_count;
    return `<text x="${end.x + 26}" y="${end.y - 2}">${esc(end.blog.name)}</text><text x="${end.x + 26}" y="${end.y + 14}" class="dim">followed by ${by === 1 ? 'one' : by} of them</text>`;
  });
  return `<figure class="graph"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Who follows whom: from ${esc(data.owner.name)}, through people they follow, to people those follow">
<defs>${clips.join('')}</defs>${lines.join('')}${faces.join('')}${names.join('')}</svg></figure>`;
}

function aboutHTML() {
  const owner = data.owner, first = owner.name.split(/\s+/)[0];
  const blogs = data.blogs.filter(b => !b.self).length;
  const posts = data.blogs.reduce((sum, b) => sum + b.posts.length, 0);
  const step = (icon, big, label) => `<div class="step">${icon}<b>${big}</b><small>${label}</small></div>`;
  return `<main class="wrap"><div class="about">
<h2>What this is</h2>
<p>${esc(owner.name)} follows ${data.following} people on GitHub, and ${blogs} of them write a blog. This page gathers what they post, newest first. Nobody signed up for it or added anything to their site: the blogs are found automatically.</p>

<h2>How it works</h2>
<div class="flow">
${step(ICON.github, data.following, 'people followed on GitHub')}<i>${ICON.arrow}</i>
${step(ICON.site, blogs, 'have a blog of their own')}<i>${ICON.arrow}</i>
${step(ICON.feed, posts.toLocaleString('en'), 'posts read from their feeds')}<i>${ICON.arrow}</i>
${step(ICON.page, 'This page', 'rebuilt every few hours')}
</div>
<ol class="notes">
<li>It reads the public list of who ${esc(first)} follows.</li>
<li>For each person it tries the website on their GitHub profile, then their GitHub Pages site, and keeps a site only if it is clearly theirs and has a feed.</li>
<li>Every few hours it reads those feeds again and rebuilds the page. It runs on GitHub Actions and is served by GitHub Pages, so there is no server.</li>
</ol>

${data.discover && data.discover.blogs.length ? `<h2>Discover</h2>
<p>The Discover tab looks one step further, at the people followed by the people ${esc(first)} follows. The more of them follow someone, the higher that person is listed. Below: ${esc(first)}, some of the people ${esc(first)} follows, and who those follow.</p>
${graphSVG()}` : ''}

<h2>The small figures</h2>
<dl class="legend">
<dt><span class="stat">${ICON.heart}18</span><span class="stat">${ICON.talk}6</span></dt>
<dd>Likes and comments on the post, read from the blog's own comments where they are public: GitHub Discussions and Issues, Disqus, Twikoo.</dd>
<dt><span class="stat hn"><i>Y</i>412</span></dt>
<dd>Points on Hacker News, when the post was discussed there.</dd>
<dt class="wide"><span class="months">${[0, 1, 0, 2, 1, 0, 3, 1, 0, 1, 2, 4].map(n => `<i class="m${n}"></i>`).join('')}</span></dt>
<dd class="wide">How many posts someone published in each of the last twelve months.</dd>
</dl>

<h2>Make your own</h2>
<p>You can have this page for the people you follow. It takes about two minutes and needs no configuration.</p>
<ol class="steps">
<li><b>Fork</b> the followroll repository.</li>
<li>In your fork, open <b>Actions</b> and enable workflows.</li>
<li>Open <b>Settings → Pages</b> and set the source to <b>GitHub Actions</b>.</li>
<li>In <b>Actions</b>, run the <b>Following</b> workflow.</li>
</ol>
<p><a class="button" href="https://github.com/Ki-Seki/followroll" target="_blank" rel="noopener">${ICON.github}followroll on GitHub</a><a class="quiet" href="following.json">This page's data as JSON</a></p>
</div></main>`;
}

function render() {
  const tab = (view, label, count) => `<button type="button" role="tab" data-view="${view}" aria-selected="${state.view === view}"${state.view === view ? ' class="on"' : ''}>${label}${count === undefined ? '' : `<span>${count}</span>`}</button>`;
  app.innerHTML = `
<header class="top"><div class="wrap"><div class="head">
<a class="owner" href="${link(data.owner.url)}" target="_blank" rel="noopener" title="@${esc(data.owner.login)} on GitHub"><img src="${link(data.owner.avatar)}" alt="" width="40" height="40"></a>
<h1><a href="${link(data.owner.url)}?tab=following" target="_blank" rel="noopener" title="Who @${esc(data.owner.login)} follows on GitHub">${esc(data.title)}</a></h1>
</div></div></header>
<nav class="bar"><div class="wrap">
<div class="tabs" role="tablist">${tab('following', 'Following', data.blogs.length)}${data.discover ? tab('discover', 'Discover', data.discover.blogs.length) : ''}${tab('about', 'About')}</div>
</div></nav>
${state.view === 'about' ? aboutHTML() : `<div class="wrap cols">
<main class="feed">${feedHTML()}</main>
<aside class="side">${peopleHTML()}</aside>
</div>`}
<footer class="foot"><div class="wrap">
<span>Updated ${time(data.updated)}</span>
</div></footer>`;
}

app.addEventListener('click', e => {
  const pick = e.target.closest('.pick'), tab = e.target.closest('.tabs button');
  const act = e.target.closest('[data-do]')?.dataset.do;
  if (tab) {
    // The tab you are on takes you back to everyone, at the top.
    if (tab.dataset.view === state.view && !state.who && window.scrollY === 0) return;
    Object.assign(state, { view: tab.dataset.view, who: null, shown: PAGE, everyone: tab.dataset.view === state.view && state.everyone });
  } else if (pick) {
    state.who = state.who === pick.dataset.login ? null : pick.dataset.login;
    state.shown = PAGE;
  } else if (act === 'more') { state.shown += PAGE;
  } else if (act === 'everyone') { state.everyone = true;
  } else return;
  const top = window.scrollY, along = app.querySelector('.people')?.scrollLeft || 0;
  writeHash();
  render();
  const people = app.querySelector('.people'), body = app.querySelector('.cols, .about');
  if (people) people.scrollLeft = along;   // the row of faces stays where it was
  // Keep the reader's place for "more"; a new filter or tab starts at the top.
  if (act === 'more' || act === 'everyone') window.scrollTo(0, top);
  else if (body.getBoundingClientRect().top < 0) body.scrollIntoView({ block: 'start' });
});

narrow.addEventListener('change', render);
window.addEventListener('hashchange', () => {
  const was = state.view;
  readHash();
  state.shown = PAGE;
  render();
  if (state.view !== was) window.scrollTo(0, 0);   // About and the lists are different pages
});

readHash();
render();
