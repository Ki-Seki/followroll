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
  github: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>',
};

const narrow = matchMedia('(max-width: 880px)');
const data = JSON.parse(document.getElementById('data').textContent);
const app = document.getElementById('app');
const state = { view: 'following', who: null, shown: PAGE, everyone: false };

// The address keeps the view and the person: #discover, #by=login, #discover&by=login
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  state.view = q.has('discover') && data.discover ? 'discover' : 'following';
  state.who = q.get('by');
}
function writeHash() {
  const parts = [state.view === 'discover' ? 'discover' : '', state.who ? `by=${encodeURIComponent(state.who)}` : ''].filter(Boolean);
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : location.pathname + location.search);
}

const list = () => (state.view === 'discover' ? data.discover : data);

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
  const { blogs, posts: everything } = list();
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

function render() {
  const tab = (view, label, count) => `<button type="button" role="tab" data-view="${view}" aria-selected="${state.view === view}"${state.view === view ? ' class="on"' : ''}>${label}<span>${count}</span></button>`;
  app.innerHTML = `
<header class="top"><div class="wrap"><div class="head">
<a class="owner" href="${link(data.owner.url)}" target="_blank" rel="noopener" title="@${esc(data.owner.login)} on GitHub"><img src="${link(data.owner.avatar)}" alt="" width="40" height="40"></a>
<h1><a href="${link(data.owner.url)}?tab=following" target="_blank" rel="noopener" title="Who @${esc(data.owner.login)} follows on GitHub">${esc(data.title)}</a></h1>
</div></div></header>
<nav class="bar"><div class="wrap">
<div class="tabs" role="tablist">${tab('following', 'Following', data.blogs.length)}${data.discover ? tab('discover', 'Discover', data.discover.blogs.length) : ''}</div>
</div></nav>
<div class="wrap cols">
<main class="feed">${feedHTML()}</main>
<aside class="side">${peopleHTML()}</aside>
</div>
<footer class="foot"><div class="wrap">
<span>Updated ${time(data.updated)}. Found automatically from GitHub.</span>
<span><a href="following.json">JSON</a><a href="https://github.com/Ki-Seki/followroll" target="_blank" rel="noopener">Make your own</a></span>
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
  const top = window.scrollY, along = app.querySelector('.people').scrollLeft;
  writeHash();
  render();
  app.querySelector('.people').scrollLeft = along;   // the row of faces stays where it was
  // Keep the reader's place for "more"; a new filter or tab starts at the top of the list.
  if (act === 'more' || act === 'everyone') window.scrollTo(0, top);
  else if (app.querySelector('.cols').getBoundingClientRect().top < 0) app.querySelector('.cols').scrollIntoView({ block: 'start' });
});

narrow.addEventListener('change', render);
window.addEventListener('hashchange', () => { readHash(); state.shown = PAGE; render(); });

readHash();
render();
