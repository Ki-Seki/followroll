// Renders the list that following.py embeds in the page. Everything in it comes
// from other people's feeds, so every string is escaped and every link must be
// http(s).

const PAGE = 15;          // posts shown at first, and added per "show more"
const PEOPLE = 16;        // people listed before "show all", when there are many
const DAY = 86400;
const UPSTREAM = 'https://github.com/Ki-Seki/followroll';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const link = url => (/^https?:\/\//i.test(url || '') ? esc(url) : '#');
const hostOf = url => { try { return new URL(url).host.replace(/^www\./, ''); } catch { return ''; } };
const github = login => `https://github.com/${encodeURIComponent(login)}`;
const age = iso => (Date.now() - Date.parse(iso)) / 1000;
const same = (a, b) => String(a).toLowerCase() === String(b).toLowerCase();
// A post's address without the parts that vary between links to it
const key = url => String(url).replace(/^https?:\/\/(www\.)?/i, '').replace(/#.*$/, '').replace(/\/+$/, '');
// A summary as its author would have typed it: no space left before punctuation
const tidy = text => String(text).replace(/\s+([,.;:!?])/g, '$1');
// What this browser remembers, where it is allowed to
const keep = {
  get(name) { try { return localStorage.getItem(name) || ''; } catch { return ''; } },
  set(name, value) { try { value ? localStorage.setItem(name, value) : localStorage.removeItem(name); } catch { /* not kept, then */ } },
};

const data = JSON.parse(document.getElementById('data').textContent);
const app = document.getElementById('app');
const narrow = matchMedia('(max-width: 880px)');
const state = { view: 'following', who: null, at: '', shown: PAGE, everyone: false, step: 0, went: false };

// ------------------------------------------------------------- words
// Everything the page says, in English and in Chinese. A few entries carry
// markup; whatever is put into those is escaped by the caller first.
const WORDS = {
  en: {
    name: 'English',
    following: 'Following', discover: 'Discover',
    people: 'People', toDiscover: 'People to discover', monthsKey: 'Posts a month, past year',
    showAll: n => `Show all ${n}`, more: n => `Show ${n} more`,
    empty: 'Nothing here yet.',
    emptyFollowing: n => `None of the ${n} people followed here has a blog that could be found yet.`,
    week: 'This week', month: 'This month', year: 'This year', inYear: y => String(y),
    short: (n, unit) => `${n}${unit}`,
    and: (a, b) => `${a} and ${b}`, andMore: (list, more) => `${list} and ${more} more`, comma: ', ',
    reposted: who => `${who} reposted`, repostedSolo: 'Reposted',
    followedBy: who => `Followed by ${who}`,
    updated: when => `Updated ${when}`,
    onGitHub: login => `@${login} on GitHub`, onPage: name => `${name} on this page`,
    theirSite: name => `${name}'s site`, theirRoll: name => `${name}'s own followroll: who they follow and what they repost`,
    hasRoll: 'has a followroll', lastPost: when => `last post ${when}`,
    likes: (n, where) => `${n} ${n === 1 ? 'like' : 'likes'} ${where}`,
    comments: (n, where) => `${n} ${n === 1 ? 'comment' : 'comments'} ${where}`,
    where: { disqus: 'on Disqus', twikoo: 'on the post', github: 'on GitHub' },
    hn: (points, comments) => `${points} points and ${comments} comments on Hacker News`,
    fresh: 'New since your last visit',
    repost: 'Repost', repostToo: who => `Reposted by ${who}. Repost it too`,
    yours: 'You reposted this. Open it on GitHub: deleting the discussion takes it back',
    sent: 'Sent to GitHub. It shows here once you have pressed Start discussion there and this page has refreshed',
    notePh: 'Add a note (optional)', userPh: 'GitHub username', userTitle: 'Reposts are kept in your own followroll',
    repostTitle: 'Opens GitHub with everything filled in: press Start discussion there',
    closed: there => `Reposts are kept in your followroll's Discussions, and those are off. <a href="${there}/settings" target="_blank" rel="noopener">Open its settings</a>, tick <b>Discussions</b> under Features, then press Repost again.`,
    missing: login => `There is no github.com/${login}/followroll yet. <a href="#how-do-i-make-my-own">Make your own</a> first: it takes two minutes.`,
    about: 'About', aboutTitle: 'What this is, and how to make your own', home: 'Back to the start',
    keptHere: 'What you set here is kept in this browser only.',
    thisPage: 'What is this page?', whatDiscover: 'What is Discover?', make: 'How do I make my own?',
    linkHere: 'Link to this question',
    thisPageText: owner => `Posts from the blogs of the people ${owner} follows on GitHub, newest first. The blogs are found automatically: nobody signed up.`,
    flow: ['people followed on GitHub', 'have a blog of their own', 'posts read from their feeds', 'This page', 'rebuilt every few hours'],
    discoverText: first => `One step further: people followed by the people ${first} follows. The more of them follow someone, the higher they rank.`,
    graphBy: n => `followed by ${n === 1 ? 'one' : n} of them`,
    graphLabel: owner => `Who follows whom: from ${owner}, through people they follow, to people those follow`,
    settings: 'Settings', language: 'Language',
    theme: 'Appearance', themes: { '': 'Auto', light: 'Light', dark: 'Dark' },   // "Auto" serves the language too
    trShown: 'Translated by DeepSeek. Press for the original', trHidden: 'Show the translation',
    repostAs: 'Reposting as', forget: 'Forget',
    version: 'Version', update: v => `Update to ${v}`, whatsNew: v => `What's new in ${v}`, close: 'Close',
    howUpdate: 'Open your followroll on GitHub and press <b>Sync fork</b>, then <b>Update branch</b>. Your page rebuilds itself a minute or two later.',
    openRepo: 'Open my followroll', updateAlt: 'The Sync fork menu of a fork, open, with its Update branch button',
    setupLead: 'A page like this for the people you follow takes five steps on GitHub: about two minutes, nothing to install.',
    yourName: 'Your GitHub username', namePh: 'username', needName: 'Enter your GitHub username above first',
    stepOf: (n, all) => `Step ${n} of ${all}`, next: 'Next', done: 'Done', back: 'Back',
    allDone: all => `All ${all} steps done`, thatsIt: 'That is it',
    built: 'Your page is built in about a minute, and then refreshes on its own every few hours.',
    openMine: 'Open my page',
    alsoDiscussions: where => `To repost, also turn on <b>Discussions</b>${where}.`,
    inSettings: href => ` in <a href="${href}" target="_blank" rel="noopener">your followroll's settings</a>, under Features`,
    steps: [
      { title: 'Fork the repository', say: 'Press <b>Create fork</b>, and keep the name followroll.', label: 'Open the fork page', alt: 'The Fork button at the top of the repository' },
      { title: 'Enable workflows', say: 'Press the green button.', label: 'Open Actions', alt: 'The green button that enables workflows in a fork' },
      { title: 'Publish with GitHub Actions', say: 'Under <b>Source</b>, choose <b>GitHub Actions</b>.', label: 'Open Pages settings', alt: 'The Source menu with GitHub Actions' },
      { title: 'Turn the schedule on', say: 'Press <b>Enable workflow</b>.', label: 'Open the workflow', alt: 'The Enable workflow button in the notice about schedules in forks' },
      { title: 'Run it once', say: 'Press <b>Run workflow</b>, then the green button in the menu that opens.', label: 'Open the workflow', alt: 'The Run workflow button' },
    ],
  },
  zh: {
    name: '中文',
    following: '关注', discover: '发现',
    people: '博主', toDiscover: '值得认识的人', monthsKey: '近一年每月发文',
    showAll: n => `显示全部 ${n} 位`, more: n => `再显示 ${n} 篇`,
    empty: '这里还没有内容。',
    emptyFollowing: n => `在关注的 ${n} 个人里，还没找到有博客的。`,
    week: '本周', month: '本月', year: '今年', inYear: y => `${y} 年`,
    short: (n, unit) => `${n} ${{ m: '分钟', h: '小时', d: '天', mo: '个月' }[unit]}前`,
    and: (a, b) => `${a} 和 ${b}`, andMore: (list, more, all) => `${list} 等 ${all} 人`, comma: '、',
    reposted: who => `${who} 转发了`, repostedSolo: '转发了',
    followedBy: who => `被 ${who} 关注`,
    updated: when => `更新于 ${when}`,
    onGitHub: login => `GitHub 上的 @${login}`, onPage: name => `只看 ${name}`,
    theirSite: name => `${name} 的网站`, theirRoll: name => `${name} 自己的 followroll：关注了谁、转发了什么`,
    hasRoll: '有自己的 followroll', lastPost: when => `最近发文 ${when}`,
    likes: (n, where) => `${where} ${n} 个赞`,
    comments: (n, where) => `${where} ${n} 条评论`,
    where: { disqus: 'Disqus 上', twikoo: '原文下', github: 'GitHub 上' },
    hn: (points, comments) => `Hacker News 上 ${points} 分、${comments} 条评论`,
    fresh: '你上次来过之后的新内容',
    repost: '转发', repostToo: who => `${who} 转发过，我也转发`,
    yours: '你已转发。到 GitHub 上删除这条讨论即可撤销',
    sent: '已发到 GitHub。在那边点 Start discussion、等本页刷新后就会显示',
    notePh: '写点备注（可不写）', userPh: 'GitHub 用户名', userTitle: '转发保存在你自己的 followroll 里',
    repostTitle: '会打开 GitHub 并填好内容，在那边点 Start discussion 即可',
    closed: there => `转发保存在你的 followroll 的 Discussions 里，而它现在是关着的。<a href="${there}/settings" target="_blank" rel="noopener">打开仓库设置</a>，在 Features 里勾选 <b>Discussions</b>，然后再点一次转发。`,
    missing: login => `还没有 github.com/${login}/followroll。先<a href="#how-do-i-make-my-own">创建自己的页面</a>，两分钟就好。`,
    about: '关于', aboutTitle: '这是什么，以及怎样创建自己的页面', home: '回到开头',
    keptHere: '这里的设置只保存在这个浏览器里。',
    thisPage: '这个页面是什么？', whatDiscover: '「发现」是什么？', make: '怎样创建我自己的页面？',
    linkHere: '这个问题的链接',
    thisPageText: owner => `${owner} 在 GitHub 上关注的人所写的博客文章，按时间排列。博客是自动找到的，没有人需要注册。`,
    flow: ['在 GitHub 上关注的人', '有自己的博客', '从订阅源读到的文章', '这个页面', '每隔几小时重建一次'],
    discoverText: first => `再往外一步：${first} 关注的人所关注的人。其中关注的人越多，排得越靠前。`,
    graphBy: n => `其中 ${n} 人关注`,
    graphLabel: owner => `谁关注了谁：从 ${owner} 出发，经过其关注的人，到这些人关注的人`,
    settings: '设置', language: '语言',
    theme: '外观', themes: { '': '自动', light: '浅色', dark: '深色' },
    trShown: 'DeepSeek 翻译，点一下看原文', trHidden: '显示译文',
    repostAs: '转发身份', forget: '清除',
    version: '版本', update: v => `更新到 ${v}`, whatsNew: v => `${v} 有哪些变化`, close: '关闭',
    howUpdate: '在 GitHub 上打开你的 followroll，点 <b>Sync fork</b>，再点 <b>Update branch</b>。一两分钟后页面会自动重建。',
    openRepo: '打开我的 followroll', updateAlt: '一个 fork 上展开的 Sync fork 菜单，里面有 Update branch 按钮',
    setupLead: '给你关注的人做一个这样的页面，只要在 GitHub 上点五步：大约两分钟，不用安装任何东西。',
    yourName: '你的 GitHub 用户名', namePh: '用户名', needName: '请先在上面填写 GitHub 用户名',
    stepOf: (n, all) => `第 ${n} 步，共 ${all} 步`, next: '下一步', done: '完成', back: '上一步',
    allDone: all => `${all} 步都完成了`, thatsIt: '好了',
    built: '页面大约一分钟后生成，之后每隔几小时自动刷新。',
    openMine: '打开我的页面',
    alsoDiscussions: where => `想转发的话，还要${where}打开 <b>Discussions</b>。`,
    inSettings: href => `在<a href="${href}" target="_blank" rel="noopener">你的 followroll 的设置</a>里的 Features 下`,
    steps: [
      { title: 'Fork 这个仓库', say: '点 <b>Create fork</b>，仓库名保持 followroll。', label: '打开 Fork 页面', alt: '仓库顶部的 Fork 按钮' },
      { title: '启用工作流', say: '点那个绿色按钮。', label: '打开 Actions', alt: '在 fork 里启用工作流的绿色按钮' },
      { title: '用 GitHub Actions 发布', say: '在 <b>Source</b> 下选择 <b>GitHub Actions</b>。', label: '打开 Pages 设置', alt: 'Source 菜单里的 GitHub Actions' },
      { title: '开启定时运行', say: '点 <b>Enable workflow</b>。', label: '打开工作流', alt: '提示里的 Enable workflow 按钮' },
      { title: '先运行一次', say: '点 <b>Run workflow</b>，再点弹出菜单里的绿色按钮。', label: '打开工作流', alt: 'Run workflow 按钮' },
    ],
  },
};
const LANG = 'followroll:lang';
// The language chosen here, if one was; else the browser's own
const chosenLang = () => (WORDS[keep.get(LANG)] ? keep.get(LANG) : '');
const browserLang = () => (/^zh\b/i.test(navigator.language || '') ? 'zh' : 'en');
let lang = chosenLang() || browserLang();
const locale = () => (lang === 'zh' ? 'zh-CN' : 'en');
function t(name, ...args) {
  const word = WORDS[lang][name] ?? WORDS.en[name];
  return typeof word === 'function' ? word(...args) : word;
}

// Light or dark as chosen here; if nothing was chosen, as the reader's system has it
const THEME = 'followroll:theme';
const dusk = matchMedia('(prefers-color-scheme: dark)');
const theme = () => (['light', 'dark'].includes(keep.get(THEME)) ? keep.get(THEME) : '');
const isDark = () => theme() === 'dark' || (!theme() && dusk.matches);
function applyTheme() {
  if (theme()) document.documentElement.dataset.theme = theme();
  else delete document.documentElement.dataset.theme;
}

// A post can come with a translation, made when the page was built. A reader
// of that language sees it, and can turn any one back to the original.
const flipped = new Set();   // posts turned back to their original, for this visit
function wording(p) {
  const tr = p.tr && p.tr.lang === lang ? p.tr : null, on = !!tr && !flipped.has(key(p.url));
  return { title: on ? tr.title : p.title, summary: on ? tr.summary : p.summary, tr, on };
}

// "3h", "2d", "4mo", then the date: how long ago, as short as it can be said
function since(iso) {
  const d = age(iso);
  if (d < 3600) return t('short', Math.max(1, Math.round(d / 60)), 'm');
  if (d < DAY) return t('short', Math.round(d / 3600), 'h');
  if (d < 30 * DAY) return t('short', Math.round(d / DAY), 'd');
  if (d < 365 * DAY) return t('short', Math.round(d / (30 * DAY)), 'mo');
  return new Date(iso).toLocaleDateString(locale(), { year: 'numeric', month: 'short', day: 'numeric' });
}
// The same, spelled out: "3 hours ago"
function ago(iso) {
  const d = age(iso), relative = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
  if (d < 3600) return relative.format(-Math.max(1, Math.round(d / 60)), 'minute');
  if (d < DAY) return relative.format(-Math.round(d / 3600), 'hour');
  if (d < 30 * DAY) return relative.format(-Math.round(d / DAY), 'day');
  if (d < 365 * DAY) return relative.format(-Math.round(d / (30 * DAY)), 'month');
  return new Date(iso).toLocaleDateString(locale(), { year: 'numeric', month: 'short', day: 'numeric' });
}
const exact = iso => new Date(iso).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' });
const time = (iso, say = since) => `<time datetime="${esc(iso)}" title="${esc(exact(iso))}">${esc(say(iso))}</time>`;

// How recently someone posted, 0 (over a year ago) to 4 (this week)
function heat(iso) {
  const d = age(iso) / DAY;
  return d < 7 ? 4 : d < 30 ? 3 : d < 180 ? 2 : d < 365 ? 1 : 0;
}

function period(iso) {
  const d = age(iso) / DAY;
  return d < 7 ? t('week') : d < 30 ? t('month') : d < 365 ? t('year') : t('inYear', new Date(iso).getFullYear());
}

// "Ke Fang", "Ke Fang and Arthur", "Ke Fang, Arthur and 2 more"
function names(via, count, show = v => v.name) {
  const shown = via.slice(0, 2).map(show), more = count - shown.length;
  if (more > 0) return t('andMore', shown.join(t('comma')), more, count);
  return shown.length > 1 ? t('and', shown[0], shown[1]) : shown[0] || '';
}

const ICON = {
  talk: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M2.5 3.5h11V11H7l-3 2.5V11H2.5z"/></svg>',
  heart: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M8 13.5S2.5 10.3 2.5 6.2A2.9 2.9 0 0 1 8 5a2.9 2.9 0 0 1 5.5 1.2c0 4.1-5.5 7.3-5.5 7.3z"/></svg>',
  feed: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 8.2a4.8 4.8 0 0 1 4.8 4.8M3 3.5A9.5 9.5 0 0 1 12.5 13"/><circle cx="3.6" cy="12.4" r=".9" fill="currentColor" stroke="none"/></svg>',
  page: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M5.5 6h5M5.5 8.5h5M5.5 11h3"/></svg>',
  site: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5c1.8 1.6 1.8 9.4 0 11M8 2.5c-1.8 1.6-1.8 9.4 0 11"/></svg>',
  arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h10M9.5 4.5 13 8l-3.5 3.5"/></svg>',
  repost: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8V6.5a2 2 0 0 1 2-2h7M10.5 2.5l2 2-2 2M12.5 8v1.5a2 2 0 0 1-2 2h-7M5.5 13.5l-2-2 2-2"/></svg>',
  check: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>',
  out: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5h6v6M12.5 3.5l-8 8"/></svg>',
  x: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  chevron: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>',
  github: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>',
  translate: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4.5h6.5M5.2 2.8v1.7M7.3 4.5c-.6 2.6-2.4 4.5-5 5.5M3.8 6.6c.8 1.5 2.1 2.6 3.9 3.2M9 13.5l2.5-6.2 2.5 6.2M9.8 11.6h3.4"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>',
  // followroll's own mark: four months of someone's writing
  mark: '<svg class="logo" viewBox="0 0 16 16" aria-hidden="true"><rect x="1" y="1" width="6" height="6" rx="1.8" fill="var(--g1)"/><rect x="9" y="1" width="6" height="6" rx="1.8" fill="var(--g3)"/><rect x="1" y="9" width="6" height="6" rx="1.8" fill="var(--g2)"/><rect x="9" y="9" width="6" height="6" rx="1.8" fill="var(--g4)"/></svg>',
};

// ------------------------------------------------------------ what is known
// The address keeps the view and the person: #discover, #by=login, #discover&by=login;
// or one of the questions in About, which opens About at that question.
const QUESTIONS = ['what-is-this-page', 'what-is-discover', 'how-do-i-make-my-own'];
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1)), who = personOf(q.get('by'));
  state.at = QUESTIONS.find(place => q.has(place)) || (q.has('setup') ? QUESTIONS[2] : '');   // #setup is where making one used to be
  state.view = state.at ? 'about' : ['about', 'settings'].find(view => q.has(view)) || (q.has('discover') && data.discover ? 'discover' : 'following');
  const lists = state.view === 'following' || state.view === 'discover';
  state.who = who && lists ? who.login : null;
  if (who && lists) state.view = who.view;   // a person is shown on the list they are on
}
function writeHash() {
  const view = state.view === 'about' && state.at ? state.at : state.view;   // still at the question it opened at
  const parts = [view === 'following' ? '' : view, state.who ? `by=${encodeURIComponent(state.who)}` : ''].filter(Boolean);
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : location.pathname + location.search);
}

const list = () => (state.view === 'discover' ? data.discover : data);

// Reposts by the owner and the people they follow: address -> who reposted it,
// newest first, one entry a person.
const reposted = new Map();
for (const r of data.reposts || []) {
  const group = reposted.get(key(r.url)) || [];
  if (!group.some(q => same(q.by.login, r.by.login))) reposted.set(key(r.url), [...group, r]);
}
const asItem = group => ({ reposts: group, ts: group[0].ts, date: group[0].date });
// The posts on this page by address: they say more than a repost carries.
const known = new Map();
for (const of of [data.discover, data]) for (const b of of ? of.blogs : [])
  for (const p of b.posts) known.set(key(p.url), { ...p, login: b.login, name: b.name, avatar: b.avatar });
// People with a followroll page of their own: login -> its address. The
// owner has one by definition: this page.
const rolls = { ...data.rolls, [data.owner.login]: `https://${encodeURIComponent(data.owner.login.toLowerCase())}.github.io/followroll/` };
// Everyone this page can show on their own: the people with a blog on either
// list, and those who only repost.
const people = new Map();
for (const r of data.reposts || []) people.set(r.by.login.toLowerCase(), { ...r.by, view: 'following' });
for (const b of data.discover ? data.discover.blogs : []) people.set(b.login.toLowerCase(), { login: b.login, name: b.name, avatar: b.avatar, blog: b, view: 'discover' });
for (const b of data.blogs) people.set(b.login.toLowerCase(), { login: b.login, name: b.name, avatar: b.avatar, blog: b, view: 'following' });
const personOf = login => (login ? people.get(String(login).toLowerCase()) : undefined);

// A person always opens here, on this page, where their links out are; only
// someone the page does not know goes straight to GitHub.
function toPerson(login) {
  const known = personOf(login);
  if (known) return `href="#${known.view === 'discover' ? 'discover&' : ''}by=${encodeURIComponent(known.login)}" title="${esc(t('onPage', known.name))}"`;
  return login ? `href="${github(login)}" target="_blank" rel="noopener" title="${esc(t('onGitHub', login))}"` : '';
}

// What was already here on the reader's last visit, so that what has come
// since can be marked. The mark stays for the whole of this visit.
const SEEN = `followroll:seen:${data.owner.login.toLowerCase()}`;
const lastSeen = Number(keep.get(SEEN)) || 0;
const newest = [data, data.discover].flatMap(of => (of ? of.blogs : [])).flatMap(b => b.posts)
  .concat(data.reposts || []).reduce((latest, item) => Math.max(latest, item.ts), 0);
const leave = () => keep.set(SEEN, String(newest));
window.addEventListener('pagehide', leave);
document.addEventListener('visibilitychange', () => { if (document.hidden) leave(); });

// The latest release, if this copy is older than it
function newer() {
  const numbers = v => String(v).split('.').map(Number).concat(0, 0).slice(0, 3);
  const mine = numbers(data.version), latest = data.latest;
  return data.version && latest && numbers(latest.version).some((n, i, all) => n > mine[i] && all.slice(0, i).every((m, k) => m === mine[k])) ? latest : null;
}

// ------------------------------------------------------------ reposting
// Reposting writes to the reader's own followroll, so the page has to know
// which account that is. It is asked once and kept in this browser.
const ME = 'followroll:me';
const me = () => keep.get(ME);
const setMe = login => keep.set(ME, login);
const mine = () => `https://github.com/${encodeURIComponent(me())}/followroll`;
const acts = [];   // the posts behind the repost buttons now on screen

// Reposts go into the Discussions of the reader's own followroll, which a
// repository has switched off until its owner turns them on. GitHub says
// whether they are on; once they are, the answer is kept in this browser.
const READY = 'followroll:ready';
const isReady = login => keep.get(READY) === login.toLowerCase();
// "ok", "missing" (no such followroll), "closed" (Discussions are off) or "unknown"
async function readiness(login) {
  if (isReady(login)) return 'ok';
  try {
    const reply = await fetch(`https://api.github.com/repos/${encodeURIComponent(login)}/followroll`, { headers: { Accept: 'application/vnd.github+json' }, cache: 'no-store' });
    if (reply.status === 404) return 'missing';
    if (!reply.ok) return 'unknown';
    if (!(await reply.json()).has_discussions) return 'closed';
    keep.set(READY, login.toLowerCase());
    return 'ok';
  } catch { return 'unknown'; }
}

// A repost only shows once the page has been rebuilt, a minute or two after
// it is made. Until then this browser remembers having sent it, so the button
// can say so straight away.
const SENT = 'followroll:sent';
function sent() {
  let all = {};
  try { all = JSON.parse(keep.get(SENT) || '{}') || {}; } catch { /* start afresh */ }
  return Object.fromEntries(Object.entries(all).filter(([, when]) => Date.now() - when < 2 * 3600 * 1000));
}
const markSent = url => keep.set(SENT, JSON.stringify({ ...sent(), [key(url)]: Date.now() }));

// The new-discussion form of the reader's own followroll, filled in. The line
// that names the post is a comment, so it does not show in the discussion.
function repostURL(login, post, note) {
  const about = JSON.stringify({ url: post.url, author: post.author, login: post.login }).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
  const body = `${note || ''}\n\n<!-- Anything above this line is your note. Leave the next line as it is, then press Start discussion. -->\n<!-- followroll ${about} -->`;
  return `https://github.com/${encodeURIComponent(login)}/followroll/discussions/new?category=show-and-tell&title=${encodeURIComponent(post.title)}&body=${encodeURIComponent(body)}`;
}

// The repost button of a post, with how many of the people here reposted it.
function repostButton(p) {
  const group = reposted.get(key(p.url)) || [], made = me() && group.find(r => same(r.by.login, me()));
  const waiting = !made && me() && sent()[key(p.url)];
  const label = made ? t('yours') : waiting ? t('sent') : group.length ? t('repostToo', names(group.map(r => r.by), group.length)) : t('repost');
  const count = group.length + (waiting ? 1 : 0);
  acts.push({ url: p.url, title: p.title, author: p.name, login: p.login, source: made ? made.source : waiting ? `${mine()}/discussions` : '' });
  return `<button class="rp${made || waiting ? ' on' : ''}" type="button" data-act="${acts.length - 1}" title="${esc(label)}" aria-label="${esc(label)}">${ICON.repost}${count || ''}</button>`;
}

// ------------------------------------------------------------ the lists
// Every post of a list, newest first, each with its author; on the owner's
// own list, the reposts as well. Worked out once.
function timeline(of) {
  of.timeline ??= of.blogs.flatMap(b => b.posts.map(p => ({ ...p, login: b.login, name: b.name, avatar: b.avatar })))
    .concat(of === data ? [...reposted.values()].map(asItem) : [])
    .sort((a, b) => b.ts - a.ts);
  return of.timeline;
}

// Likes and comments wherever they could be counted, plus the Hacker News thread.
function statsHTML(p) {
  const thread = p.thread, hn = p.hn, out = [];
  const where = thread ? t('where')[thread.source] || t('where').github : '';
  if (thread && thread.likes) out.push(`<a class="stat" href="${link(thread.url)}" target="_blank" rel="noopener" title="${esc(t('likes', thread.likes, where))}">${ICON.heart}${thread.likes}</a>`);
  if (thread && thread.comments) out.push(`<a class="stat" href="${link(thread.url)}" target="_blank" rel="noopener" title="${esc(t('comments', thread.comments, where))}">${ICON.talk}${thread.comments}</a>`);
  if (hn) out.push(`<a class="stat hn" href="${link(hn.url)}" target="_blank" rel="noopener" title="${esc(t('hn', hn.points, hn.comments))}"><i>Y</i>${hn.points}</a>`);
  return out.join('');
}

// What a post can be done with and how it was received: always in one place,
// under it.
function infoHTML(p) {
  const w = wording(p);
  const flip = w.tr ? `<button class="flip${w.on ? ' on' : ''}" type="button" data-flip="${esc(key(p.url))}" aria-pressed="${w.on}" title="${esc(t(w.on ? 'trShown' : 'trHidden'))}" aria-label="${esc(t(w.on ? 'trShown' : 'trHidden'))}">${ICON.translate}</button>` : '';
  return `<div class="info">${repostButton(p)}${statsHTML(p)}${flip}</div>`;
}
const freshHTML = ts => (lastSeen && ts > lastSeen ? `<i class="new" title="${esc(t('fresh'))}"></i>` : '');
const faceHTML = (person, size) => `<img src="${link(person.avatar)}" alt="" width="${size}" height="${size}" loading="lazy">`;

// `solo` is a post among one person's own: who wrote it goes without saying.
function postHTML(p, blog, solo) {
  const why = blog && blog.via ? `<span class="why">${esc(t('followedBy', names(blog.via, blog.via_count)))}</span>` : '';
  return `<article class="post${solo ? ' solo' : ''}">
${solo ? '' : `<a class="av" ${toPerson(p.login)} tabindex="-1" aria-hidden="true">${faceHTML(p, 36)}</a>`}
<div>
<div class="by">${solo ? '' : `<a class="who" ${toPerson(p.login)}>${esc(p.name)}</a>`}${time(p.date)}${freshHTML(p.ts)}${why}</div>
<h3><a href="${link(p.url)}" target="_blank" rel="noopener">${esc(wording(p).title)}</a></h3>
${wording(p).summary ? `<p>${esc(tidy(wording(p).summary))}</p>` : ''}
${infoHTML(p)}
</div></article>`;
}

// A post someone reposted: who, their note, and the post itself set back behind a rule.
function repostHTML(item, solo) {
  const group = item.reposts, r = group[0];
  // The post as this page knows it, or as much as the repost says about it.
  const p = known.get(key(r.url)) || { url: r.url, title: r.title, name: r.author || hostOf(r.url), login: r.login,
    avatar: r.login ? `${github(r.login)}.png?size=72` : '' };
  const who = names(group.map(q => q.by), group.length, by => `<a ${toPerson(by.login)}>${esc(by.name)}</a>`);
  const notes = group.filter(q => q.note).slice(0, 2).map(q => `<p class="note">${group.length > 1 ? `<b>${esc(q.by.name.split(/\s+/)[0])}</b> ` : ''}${esc(q.note)}</p>`).join('');
  return `<article class="post repost${solo ? ' solo' : ''}">
${solo ? '' : `<a class="av" ${toPerson(r.by.login)} tabindex="-1" aria-hidden="true">${faceHTML(r.by, 36)}</a>`}
<div>
<div class="by"><b>${solo ? t('repostedSolo') : t('reposted', who)}</b>${time(item.date)}${freshHTML(item.ts)}</div>
${notes}
<div class="quote">
<div class="by"><a class="who" ${toPerson(p.login)}>${p.avatar ? faceHTML(p, 20) : ''}${esc(p.name)}</a>${p.date ? time(p.date) : ''}</div>
<h3><a href="${link(p.url)}" target="_blank" rel="noopener">${esc(wording(p).title)}</a></h3>
${wording(p).summary ? `<p>${esc(tidy(wording(p).summary))}</p>` : ''}
</div>
${infoHTML(p)}
</div></article>`;
}

// The head of one person's posts. This is the one place their links out are:
// their site, their GitHub profile and, if they have one, their own followroll.
function profileHTML(who) {
  const out = (url, icon, label, title) => `<a href="${link(url)}" target="_blank" rel="noopener" title="${esc(title)}">${icon}${esc(label)}</a>`;
  const b = who.blog, page = rolls[who.login];
  return `<div class="profile">
${faceHTML(who, 56)}
<div>
<h2>${esc(who.name)}</h2>
<div class="outs">${b ? out(b.site, ICON.site, b.host, t('theirSite', who.name)) : ''}${out(github(who.login), ICON.github, 'GitHub', t('onGitHub', who.login))}${page ? out(page, ICON.mark, 'followroll', t('theirRoll', who.name)) : ''}</div>
${b && b.via ? `<p>${esc(t('followedBy', names(b.via, b.via_count)))}</p>` : ''}
</div></div>`;
}

function feedHTML() {
  const { blogs } = list(), everything = timeline(list());
  const byLogin = new Map(blogs.map(b => [b.login, b]));
  const who = personOf(state.who);
  let posts = everything;
  // One person: what they wrote and, on the owner's list, what they reposted.
  if (who) posts = (who.blog ? who.blog.posts : []).map(p => ({ ...p, login: who.login, name: who.name, avatar: who.avatar }))
    .concat(state.view === 'following' ? (data.reposts || []).filter(r => same(r.by.login, who.login)).map(r => asItem([r])) : [])
    .sort((a, b) => b.ts - a.ts);
  // Discover is for meeting people: each shows their newest post only.
  else if (state.view === 'discover') posts = everything.filter((p, i) => everything.findIndex(q => q.login === p.login) === i);
  const shown = posts.slice(0, state.shown);
  let html = who ? profileHTML(who) : '', last = null;
  for (const p of shown) {
    const label = period(p.date);
    if (label !== last) { html += `<h2>${label}</h2>`; last = label; }
    html += p.reposts ? repostHTML(p, !!who) : postHTML(p, state.view === 'discover' && !who ? byLogin.get(p.login) : null, !!who);
  }
  if (!posts.length) html += `<p class="empty">${state.view === 'following' && !who ? t('emptyFollowing', data.following) : t('empty')}</p>`;
  if (posts.length > shown.length)
    html += `<button class="more" type="button" data-do="more">${t('more', Math.min(PAGE, posts.length - shown.length))}</button>`;
  return html + updatedHTML();
}

const updatedHTML = () => `<p class="updated">${t('updated', time(data.updated, ago))}</p>`;

function personHTML(b) {
  const on = state.who === b.login;
  const about = [b.name, b.via ? t('followedBy', names(b.via, b.via_count)) : b.host, t('lastPost', ago(b.posts[0].date)), rolls[b.login] ? t('hasRoll') : ''].filter(Boolean).join(' · ');
  return `<div class="person heat${heat(b.posts[0].date)}${on ? ' on' : ''}">
<button class="pick" type="button" data-login="${esc(b.login)}" aria-pressed="${on}" title="${esc(about)}">
<span class="face">${faceHTML(b, 24)}</span>
<span class="id"><b>${esc(b.name)}</b>${rolls[b.login] ? ICON.mark : ''}<em>${esc(b.name.split(/\s+/)[0])}</em></span>
<span class="months" title="${esc(t('monthsKey'))}">${b.months.map(n => `<i class="m${Math.min(n, 4)}"></i>`).join('')}</span>
</button>
</div>`;
}

function peopleHTML() {
  const { blogs } = list();
  // The narrow layout shows people as one scrolling row, so it takes them all;
  // so does the wide one, unless the list is long.
  const all = state.everyone || narrow.matches || blogs.length <= 24;
  const shown = all ? blogs : blogs.slice(0, PEOPLE);
  return `<div class="people-wrap"><button class="nudge prev" type="button" data-nudge="-1" tabindex="-1" aria-hidden="true">${ICON.chevron}</button>
<div class="people">${shown.map(personHTML).join('')}</div>
<button class="nudge next" type="button" data-nudge="1" tabindex="-1" aria-hidden="true">${ICON.chevron}</button></div>
${blogs.length > shown.length ? `<button class="all" type="button" data-do="everyone">${t('showAll', blogs.length)}</button>` : ''}
${updatedHTML()}`;
}

// ------------------------------------------------------------ about followroll
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
  const curve = (a, b, strong, later) => lines.push(`<path pathLength="1" d="M${a.x} ${a.y} C${(a.x + b.x) / 2} ${a.y} ${(a.x + b.x) / 2} ${b.y} ${b.x} ${b.y}" class="${strong ? 'strong' : ''}${later ? ' later' : ''}"/>`);
  const mids = middle.map((via, i) => ({ ...via, x: columns[1], y: spread(middle.length, i) }));
  const ends = found.map((blog, i) => ({ blog, x: columns[2], y: spread(found.length, i) }));
  for (const mid of mids) curve(you, mid, false);
  for (const end of ends) for (const mid of mids) if (end.blog.via.some(via => via.login === mid.login)) curve(mid, end, end.blog.via_count > 1, true);
  face(you.x, you.y, small ? 18 : 24, data.owner.avatar, 'you');
  mids.forEach((mid, i) => face(mid.x, mid.y, small ? 15 : 17, `https://github.com/${encodeURIComponent(mid.login)}.png?size=72`, `m${i}`));
  const labels = ends.map((end, i) => {
    face(end.x, end.y, small ? 15 : 17, end.blog.avatar, `e${i}`);
    return `<text x="${end.x + 26}" y="${end.y - 2}">${esc(end.blog.name)}</text><text x="${end.x + 26}" y="${end.y + 14}" class="dim">${esc(t('graphBy', end.blog.via_count))}</text>`;
  });
  return `<figure class="graph"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t('graphLabel', data.owner.name))}">
<defs>${clips.join('')}</defs>${lines.join('')}${faces.join('')}${labels.join('')}</svg></figure>`;
}

// About followroll itself, as opposed to this page's content: the few
// questions a visitor has, each answered in a sentence or two and a picture.
// Making one's own is the last of them, with its steps right there.
// A question carries the link to itself, which shows beside it under the pointer.
const askHTML = (place, words) => `<h2>${words}<a class="anchor" href="#${place}" title="${esc(t('linkHere'))}" aria-label="${esc(t('linkHere'))}">#</a></h2>`;

function aboutHTML() {
  const owner = data.owner, first = owner.name.split(/\s+/)[0];
  const blogs = data.blogs.filter(b => !b.self).length;
  const posts = data.blogs.reduce((sum, b) => sum + b.posts.length, 0);
  const step = (icon, big, label) => `<div class="step">${icon}<b>${big}</b><small>${label}</small></div>`;
  const then = `<i>${ICON.arrow}</i>`, flow = t('flow');
  return `<main class="wrap"><div class="about">
<section id="${QUESTIONS[0]}">
${askHTML(QUESTIONS[0], t('thisPage'))}
<p>${t('thisPageText', esc(owner.name))}</p>
<div class="flow">
${step(ICON.github, data.following, flow[0])}${then}
${step(ICON.site, blogs, flow[1])}${then}
${step(ICON.feed, posts.toLocaleString(locale()), flow[2])}${then}
${step(ICON.mark, flow[3], flow[4])}
</div>
</section>

${data.discover && data.discover.blogs.length ? `<section id="${QUESTIONS[1]}">
${askHTML(QUESTIONS[1], t('whatDiscover'))}
<p>${t('discoverText', esc(first))}</p>
${graphSVG()}
</section>` : ''}

${makeHTML()}
</div></main>`;
}

// What a reader can set for themselves, all of it kept in their browser, and
// which version this copy is. A newer one is one line here; how to get it is
// said in a sheet, when asked for.
function settingsHTML() {
  const latest = newer();
  const choice = (attr, names, on, label) => `<span class="seg">${names.map(name => `<button type="button" data-${attr}="${name}"${name === on ? ' class="on"' : ''}>${label(name)}</button>`).join('')}</span>`;
  return `<main class="wrap"><div class="about">
<h2 class="title">${t('settings')}</h2>
<dl class="prefs">
<dt>${t('language')}</dt><dd>${choice('lang', ['', ...Object.keys(WORDS)], chosenLang(), name => (name ? WORDS[name].name : t('themes')['']))}</dd>
<dt>${t('theme')}</dt><dd>${choice('shade', ['', 'light', 'dark'], theme(), name => t('themes')[name])}</dd>
${me() ? `<dt>${t('repostAs')}</dt><dd><span>github.com/<b>${esc(me())}</b>/followroll</span><button class="text" type="button" data-do="forget">${t('forget')}</button></dd>` : ''}
${data.version ? `<dt>${t('version')}</dt><dd><span>${esc(data.version)}</span>${latest
    ? `<button class="text fresh" type="button" data-do="update"><i class="new"></i>${esc(t('update', latest.version))}</button>` : ''}</dd>` : ''}
</dl>
<p class="small">${t('keptHere')}</p>
</div></main>`;
}

// How to update: the two presses on GitHub, a picture of them, and the way there
function updateHTML() {
  const latest = newer(), repo = /^[\w.-]+\/[\w.-]+$/.test(data.repo || '') ? `https://github.com/${data.repo}` : '';
  return `<small>${t('version')} ${esc(data.version)}</small>
<h3>${esc(t('update', latest.version))}</h3>
<p>${t('howUpdate')}</p>
<img src="setup/update${isDark() ? '-dark' : ''}.webp" alt="${esc(t('updateAlt'))}" width="784" height="676">
<div class="go">${repo ? `<a class="button" href="${repo}" target="_blank" rel="noopener">${t('openRepo')}${ICON.out}</a>` : ''}<a class="text" href="${link(latest.url)}" target="_blank" rel="noopener">${esc(t('whatsNew', latest.version))}</a></div>`;
}

// What takes a few words and a picture is said in a sheet over the page when
// it is asked for, rather than written into the page.
function sheet(html) {
  const pop = document.createElement('dialog');
  pop.className = 'pop';
  pop.innerHTML = `<div>${html}<button class="close" type="button" title="${esc(t('close'))}" aria-label="${esc(t('close'))}">${ICON.x}</button></div>`;
  // A press on the ground around the sheet, which is the dialog itself, closes it too
  pop.addEventListener('click', e => { if (e.target === pop || e.target.closest('.close')) pop.close(); });
  pop.addEventListener('close', () => pop.remove());
  document.body.append(pop);
  pop.showModal();
}

// ------------------------------------------------------------ making your own
// One step at a time, each with a button that opens the right page on GitHub
// and a picture of what to press there.
const STEP_TO = [() => `${UPSTREAM}/fork`, own => `${own}/actions`, own => `${own}/settings/pages`,
  own => `${own}/actions/workflows/following.yml`, own => `${own}/actions/workflows/following.yml`];

// The button that opens GitHub for the step on screen. Past the fork, the
// address depends on whose fork it is, so it asks for the username first.
function openHTML() {
  const step = t('steps')[state.step], second = state.went ? ' ghost' : '';
  if (!step) return me() ? `<a class="button" href="https://${encodeURIComponent(me().toLowerCase())}.github.io/followroll/" target="_blank" rel="noopener">${t('openMine')}${ICON.out}</a>`
    : `<button class="button" type="button" data-do="needme">${t('openMine')}</button>`;
  if (state.step && !me()) return `<button class="button${second}" type="button" data-do="needme" title="${esc(t('needName'))}">${step.label}${ICON.out}</button>`;
  return `<a class="button${second}" data-do="went" href="${link(STEP_TO[state.step](mine()))}" target="_blank" rel="noopener">${step.label}${ICON.out}</a>`;
}

function makeHTML() {
  const steps = t('steps'), n = Math.max(0, Math.min(state.step, steps.length)), step = steps[n];
  state.step = n;
  const dots = steps.map((s, i) => `<button type="button" data-do="step" data-step="${i}" class="${i === n ? 'on' : i < n ? 'done' : ''}" title="${esc(s.title)}" aria-label="${esc(t('stepOf', i + 1, steps.length))}: ${esc(s.title)}"${i === n ? ' aria-current="step"' : ''}>${i < n ? ICON.check : i + 1}</button>`).join('<i></i>');
  const back = n ? `<button class="back" type="button" data-do="back">${t('back')}</button>` : '';
  const card = step ? `<section class="card">
<small>${t('stepOf', n + 1, steps.length)}</small>
<h3>${step.title}</h3>
<p>${step.say}</p>
<img class="shot" src="setup/${n + 1}${isDark() ? '-dark' : ''}.webp" alt="${esc(step.alt)}" width="778" height="210">
<div class="go"><span>${openHTML()}</span><button class="button${state.went ? '' : ' ghost'}" type="button" data-do="next">${n === steps.length - 1 ? t('done') : t('next')}</button>${back}</div>
</section>` : `<section class="card">
<small>${t('allDone', steps.length)}</small>
<h3>${t('thatsIt')}</h3>
<p>${t('built')}</p>
<div class="go"><span>${openHTML()}</span>${back}</div>
<p class="small">${t('alsoDiscussions', me() ? t('inSettings', `${link(mine())}/settings`) : '')}</p>
</section>`;
  return `<section class="wizard" id="${QUESTIONS[2]}">
${askHTML(QUESTIONS[2], t('make'))}
<p>${t('setupLead')}</p>
<label class="you">${t('yourName')}<input name="me" value="${esc(me())}" placeholder="${esc(t('namePh'))}" aria-label="${esc(t('yourName'))}" autocomplete="username" autocapitalize="none" spellcheck="false"></label>
<div class="dots">${dots}</div>
${card}
</section>`;
}

// ------------------------------------------------------------ the page
// Whether the row of faces has more to show on either side
function edges() {
  const row = app.querySelector('.people'), wrap = row && row.parentElement;
  if (!wrap) return;
  wrap.classList.toggle('more-left', row.scrollLeft > 4);
  wrap.classList.toggle('more-right', row.scrollLeft + row.clientWidth < row.scrollWidth - 4);
}

// One bar, read like a path: followroll, which leads back to the start; whose
// followroll this is, who opens here like anyone else on the page; its two
// lists; and at the far end what is about the page rather than of it.
function render() {
  acts.length = 0;
  app.classList.remove('still');
  document.documentElement.lang = locale();
  const tab = (view, count) => `<button type="button" role="tab" data-view="${view}" aria-selected="${state.view === view}"${state.view === view ? ' class="on"' : ''}>${t(view)}<span>${count}</span></button>`;
  app.innerHTML = `
<nav class="bar"><div class="wrap">
<div class="brand">
<a class="mark" href="./" data-do="home" title="${esc(t('home'))}">${ICON.mark}followroll</a><i class="of">/</i>
<a class="owner" ${toPerson(data.owner.login)}>${faceHTML(data.owner, 24)}<h1>${esc(data.title)}</h1></a>
</div>
<div class="tabs" role="tablist">${tab('following', data.blogs.length)}${data.discover ? tab('discover', data.discover.blogs.length) : ''}</div>
<div class="ends">
<a class="plain${state.view === 'about' ? ' on' : ''}" href="#about" title="${esc(t('aboutTitle'))}">${t('about')}</a>
<a class="gear${state.view === 'settings' ? ' on' : ''}" href="#settings" title="${esc(t('settings'))}" aria-label="${esc(t('settings'))}">${ICON.gear}${newer() ? '<i class="new"></i>' : ''}</a>
</div>
</div></nav>
${state.view === 'about' ? aboutHTML() : state.view === 'settings' ? settingsHTML() : `<div class="wrap cols">
<main class="feed">${feedHTML()}</main>
<aside class="side" aria-label="${esc(t(state.view === 'discover' ? 'toDiscover' : 'people'))}">${peopleHTML()}</aside>
</div>`}`;
  app.querySelector('.people')?.addEventListener('scroll', edges, { passive: true });
  edges();
}

// An address that names a place within a view opens the view there
const settle = () => { if (state.at) document.getElementById(state.at)?.scrollIntoView({ block: 'start' }); };

// Renders again where the reader is, without playing again what was drawn
// when they arrived
function refresh() {
  const top = window.scrollY, along = app.querySelector('.people')?.scrollLeft || 0;
  render();
  app.classList.add('still');
  const row = app.querySelector('.people');
  if (row) { row.scrollLeft = along; edges(); }
  window.scrollTo(0, top);
}

// A line under the post to write a note on; the first time it also asks which
// account to repost to.
function compose(button) {
  const holder = button.closest('.post').lastElementChild, open = holder.querySelector('.as');
  app.querySelectorAll('.as').forEach(form => form.remove());
  if (open) return;
  holder.insertAdjacentHTML('beforeend', `<form class="as" data-act="${esc(button.dataset.act)}">
${me() ? '' : `<input name="me" required pattern="[A-Za-z0-9][A-Za-z0-9\\-]{0,38}" placeholder="${esc(t('userPh'))}" aria-label="${esc(t('userPh'))}" title="${esc(t('userTitle'))}" autocomplete="username" autocapitalize="none" spellcheck="false">`}
<input name="note" maxlength="500" placeholder="${esc(t('notePh'))}" aria-label="${esc(t('notePh'))}" autocomplete="off">
<button type="submit" title="${esc(t('repostTitle'))}">${t('repost')}</button></form>`);
  holder.querySelector('.as input').focus();
}

// Sends the repost to GitHub with everything filled in, note included, so
// that all that is left to do there is press Start discussion. If that
// followroll cannot take it yet, says why here instead of leading to a dead end.
app.addEventListener('submit', async e => {
  const form = e.target.closest('.as');
  if (!form) return;
  e.preventDefault();
  const post = acts[form.dataset.act], note = form.elements.note.value.trim();
  const login = form.elements.me ? form.elements.me.value.trim() : me();
  const send = tab => {
    const url = repostURL(login, post, note);
    setMe(login);
    markSent(post.url);
    if (tab) { tab.opener = null; tab.location.replace(url); } else window.open(url, '_blank', 'noopener');
    refresh();   // the line goes away, and the button shows it has been sent
  };
  if (isReady(login)) return send();
  // A browser only lets a page open a tab during the click itself, so the
  // tab is opened now and then filled, or closed, once GitHub has answered.
  const tab = window.open('', '_blank'), button = form.querySelector('button');
  button.disabled = true;
  const answer = await readiness(login);
  button.disabled = false;
  if (answer === 'ok' || answer === 'unknown') return send(tab);
  if (tab) tab.close();
  if (answer === 'closed') setMe(login);
  form.querySelector('.hint')?.remove();
  form.insertAdjacentHTML('beforeend', `<div class="hint">${answer === 'closed' ? t('closed', `https://github.com/${encodeURIComponent(login)}/followroll`) : t('missing', esc(login))}</div>`);
});

// The username typed on the setup page is kept as it is typed, and the
// button for the step follows it.
app.addEventListener('input', e => {
  if (!e.target.matches('.you input')) return;
  const login = e.target.value.trim();
  setMe(/^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(login) ? login : '');
  app.querySelector('.go span').innerHTML = openHTML();
});

app.addEventListener('click', e => {
  const pick = e.target.closest('.pick'), tab = e.target.closest('.tabs button'), nudge = e.target.closest('.nudge');
  const act = e.target.closest('[data-do]')?.dataset.do, rp = e.target.closest('.rp'), tongue = e.target.closest('[data-lang]');
  if (nudge) { const row = app.querySelector('.people'); return row.scrollBy({ left: nudge.dataset.nudge * row.clientWidth * 0.8, behavior: 'smooth' }); }
  if (rp) {   // one already made opens where it is kept; otherwise a line to write it on
    const post = acts[rp.dataset.act];
    return post.source ? window.open(post.source, '_blank', 'noopener') : compose(rp);
  }
  if (tongue) { keep.set(LANG, tongue.dataset.lang); lang = chosenLang() || browserLang(); return refresh(); }
  const shade = e.target.closest('[data-shade]'), flip = e.target.closest('.flip');
  if (shade) { keep.set(THEME, shade.dataset.shade); applyTheme(); return refresh(); }
  if (flip) { flipped.has(flip.dataset.flip) ? flipped.delete(flip.dataset.flip) : flipped.add(flip.dataset.flip); return refresh(); }
  if (act === 'home') {   // the start: the first list, everyone, from the top
    e.preventDefault();
    Object.assign(state, { view: 'following', who: null, shown: PAGE });
    writeHash();
    render();
    return window.scrollTo(0, 0);
  }
  if (act === 'update') return sheet(updateHTML());
  if (act === 'needme') return app.querySelector('.you input').focus();
  if (act === 'went') {   // GitHub opens in its own tab; here, "Next" becomes the thing to press
    e.preventDefault();
    window.open(e.target.closest('a').href, '_blank', 'noopener');
    state.went = true;
    return refresh();
  }
  if (tab) {
    // The tab you are on takes you back to everyone, at the top.
    if (tab.dataset.view === state.view && !state.who && window.scrollY === 0) return;
    Object.assign(state, { view: tab.dataset.view, who: null, shown: PAGE, everyone: tab.dataset.view === state.view && state.everyone });
  } else if (pick) {
    state.who = state.who === pick.dataset.login ? null : pick.dataset.login;
    state.shown = PAGE;
  } else if (act === 'more') { state.shown += PAGE;
  } else if (act === 'everyone') { state.everyone = true;
  } else if (act === 'forget') { setMe('');
  } else if (act === 'step') { Object.assign(state, { step: +e.target.closest('[data-step]').dataset.step, went: false });
  } else if (act === 'next') { Object.assign(state, { step: state.step + 1, went: false });
  } else if (act === 'back') { Object.assign(state, { step: state.step - 1, went: false });
  } else return;
  writeHash();
  // Keep the reader's place for "more" and the like; a new person or tab starts at the top.
  if (['more', 'everyone', 'forget', 'step', 'next', 'back'].includes(act)) return refresh();
  const along = app.querySelector('.people')?.scrollLeft || 0;
  render();
  const row = app.querySelector('.people'), body = app.querySelector('.cols, .about');
  if (row) { row.scrollLeft = along; edges(); }   // the row of faces stays where it was
  if (body.getBoundingClientRect().top < 0) body.scrollIntoView({ block: 'start' });
});

// With a mouse, the row of faces is pulled along by hand, the way a finger
// would on a touch screen. A pull is not a click on the face under it.
let pull = null;
app.addEventListener('pointerdown', e => {
  const row = e.target.closest('.people');
  if (row && e.pointerType === 'mouse' && e.button === 0 && row.scrollWidth > row.clientWidth) pull = { row, x: e.clientX, left: row.scrollLeft, moved: false };
});
app.addEventListener('dragstart', e => { if (e.target.closest('.people')) e.preventDefault(); });
window.addEventListener('pointermove', e => {
  if (!pull) return;
  const dx = e.clientX - pull.x;
  if (!pull.moved && Math.abs(dx) < 5) return;
  pull.moved = true;
  pull.row.classList.add('pulling');
  pull.row.scrollLeft = pull.left - dx;
});
window.addEventListener('pointerup', () => {
  if (!pull) return;
  const { row, moved } = pull;
  pull = null;
  row.classList.remove('pulling');
  if (!moved) return;
  const swallow = e => { e.stopPropagation(); e.preventDefault(); };
  window.addEventListener('click', swallow, { capture: true, once: true });
  setTimeout(() => window.removeEventListener('click', swallow, true));
});

narrow.addEventListener('change', render);
dusk.addEventListener('change', () => { if (state.view === 'about') refresh(); });   // its pictures come in both
window.addEventListener('resize', edges);
window.addEventListener('hashchange', () => {
  const was = state.view, who = state.who;
  readHash();
  state.shown = PAGE;
  // From one question to another, About stays as it is: only the place changes
  if (state.view === 'about' && was === 'about') return state.at ? settle() : window.scrollTo(0, 0);
  render();
  const body = app.querySelector('.cols, .about');
  if (state.view !== was) window.scrollTo(0, 0);   // followroll's own pages and the lists are different pages
  else if (state.who !== who && body.getBoundingClientRect().top < 0) body.scrollIntoView({ block: 'start' });
  settle();
});

applyTheme();
readHash();
render();
settle();
