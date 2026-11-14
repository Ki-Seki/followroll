#!/usr/bin/env python3
"""Build a page of recent posts from the blogs of the people someone follows on GitHub.

For each followed account the script looks for a personal site (the website on
the GitHub profile, then <login>.github.io), finds its feed, and keeps it only
when the feed is that person's own writing: the site is their GitHub Pages
site, its address carries their name, their Pages repository's CNAME points at
it, or it links back to their GitHub profile. A profile on someone else's site
is not enough to make that site's blog theirs. Nobody has to opt in or change
anything on their blog.

Comment and reaction counts are read wherever that works without logging in:
GitHub Discussions (giscus), GitHub Issues (utterances, gitalk), Disqus and
Twikoo. A post that was discussed on Hacker News gets its points and comment
count from there.

The Discover list looks one step further: the accounts followed by the people
you follow. The ones most of them follow are tried first.

The list grows from run to run. A post stays after it has dropped out of its
blog's feed, so each blog's history builds up; and every run looks at another
batch of second-degree accounts it has not seen, until all of them are covered.

Writes following.json into the output folder, next to the page that displays
it (the files in site/), reposts.json, and state.json, what this run learned about each
account. The next run reads both back from the published site: someone known
to have no blog is left alone for a month, a known feed is asked only whether
it has changed, and older posts keep the counts they had.

A repost is an open discussion the owner started in their own copy of this
repository (the page's repost button fills it in). The run publishes them as
reposts.json, and reads the same file from the page of every followed person
who has one, at https://<login>.github.io/followroll/. That fixed address is
why the repository has to keep its name.

Each copy knows its own version (VERSION below) and asks which release of
followroll is the latest, so the page can say when it is time to sync the fork.

With a DeepSeek key in the environment, the titles and summaries of posts are
translated as well, Chinese ones into English and the rest into Chinese, so
that a reader of either language can read the whole list. Words translated
before are not sent again: the translations ride along in following.json.

A run may add to the list and update it, but a request that fails never takes
anything away: a blog that can't be read keeps its last entry (for two weeks),
a count that can't be read keeps its last value, and Discover keeps its last
list unless every following list behind it could be read.

Usage: following.py [--output DIR] [--no-page]

Environment (an empty value counts as unset):
  GITHUB_TOKEN / GH_TOKEN   token for the GitHub API; `gh auth token` is tried next
  FOLLOWING_LOGIN           whose following list to read (default: the repository
                            owner on GitHub Actions, else the token's own account)
  FOLLOWING_TITLE           what the page is called (default: the owner's name)
  FOLLOWING_PREVIOUS_URL    where the previous run's following.json is published
                            (default: this repository's GitHub Pages address)
  FOLLOWING_MAX_PEOPLE      most followed accounts to look at, newest first (default: 500)
  FOLLOWING_DISCOVER        how many second-degree accounts not seen before each
                            run looks at for Discover; 0 turns it off (default: 200)
  FOLLOWING_WORKERS         concurrent sites (default: 24)
  DEEPSEEK_API_KEY          turns translation on; without it nothing is sent anywhere
  DEEPSEEK_MODEL            the model asked to translate (default: deepseek-flash)
  TRANSLATE_MAX_CHARS       most characters sent for translation in one run (default: 300000)
"""

import argparse
import collections
import concurrent.futures
import datetime
import email.utils
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

HERE = Path(__file__).resolve().parent
VERSION = "1.2.0"                 # goes up with every release
UPSTREAM = "Ki-Seki/followroll"   # where the releases are published
API_URL = "https://api.github.com/graphql"
USER_AGENT = f"Mozilla/5.0 (compatible; followroll/{VERSION}; +https://github.com/{UPSTREAM})"
TIMEOUT = 12
MAX_BYTES = 3_000_000
MAX_PEOPLE = int(os.environ.get("FOLLOWING_MAX_PEOPLE") or 500)
WORKERS = int(os.environ.get("FOLLOWING_WORKERS") or 24)
DISCOVER_PEOPLE = int(os.environ.get("FOLLOWING_DISCOVER") or 200)
POSTS_PER_BLOG = 100    # posts kept per blog, as they build up over the runs
DISCOVER_POSTS = 3      # posts kept per blog on the Discover list, none older than a year
MAX_POSTS = 1500        # posts kept in all; the oldest go first
COUNTED_POSTS = 20      # newest posts of a blog whose comment counts are read
DISCOVER_LIMIT = 2000   # second-degree accounts considered at all, best-ranked first
REPO = "followroll"     # every copy of this repository keeps this name, so pages can find each other
REPOSTS = 100           # newest reposts kept per person

# A profile link to an account on someone else's platform is not a blog.
NOT_A_BLOG = (
    "linkedin.com", "twitter.com", "x.com", "scholar.google", "zhihu.com",
    "bilibili.com", "weibo.com", "huggingface.co", "youtube.com",
    "instagram.com", "facebook.com", "t.me", "orcid.org", "researchgate.net",
    "github.com", "gitee.com", "kaggle.com", "linktr.ee",
)
FEED_TYPES = ("application/rss+xml", "application/atom+xml",
              "application/feed+json", "application/json")
FEED_PATHS = (
    "index.xml", "feed.xml", "atom.xml", "rss.xml", "feed", "feed/", "rss",
    "blog/index.xml", "blog/feed.xml", "blog/atom.xml", "blog/rss.xml",
    "posts/index.xml", "post/index.xml", "feed.json",
)
# The sample posts that ship with the academicpages Jekyll template
PLACEHOLDER_POST = re.compile(r"/posts/\d{4}/\d{2}/blog-post-\d+/?$")


# ----------------------------------------------------------------- web

ACCEPT = "text/html,application/xhtml+xml,application/atom+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8"


def fetch(url, validators=None):
    """Returns (status, final URL, bytes, validators).

    status is "ok", "same" (unchanged since the validators were issued),
    "gone" (the server says there is nothing here) or "fail" (no usable answer)."""
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if validators and validators.get("etag"):
        headers["If-None-Match"] = validators["etag"]
    if validators and validators.get("modified"):
        headers["If-Modified-Since"] = validators["modified"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return "fail", url, b"", None
            fresh = {"etag": response.headers.get("ETag"), "modified": response.headers.get("Last-Modified")}
            return "ok", response.geturl(), body, fresh
    except urllib.error.HTTPError as error:
        status = "same" if error.code == 304 else "gone" if error.code in (404, 410) else "fail"
        return status, url, b"", None
    except Exception:
        return "fail", url, b"", None


def get(url):
    """Returns (final URL, bytes) or None."""
    status, final, body, _ = fetch(url)
    return (final, body) if status == "ok" else None


def post_json(url, body, token=None, timeout=TIMEOUT, limit=MAX_BYTES):
    """POSTs JSON. Returns (the decoded JSON reply or None, the HTTP status if the server refused)."""
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(limit)), None
    except urllib.error.HTTPError as error:
        return None, error.code
    except Exception:
        return None, None


def text_of(body):
    return body.decode("utf-8", errors="replace")


def plain(markup, limit=200):
    """HTML to one line of text, cut at `limit` characters."""
    markup = re.sub(r"<(script|style)\b.*?</\1>", " ", markup or "", flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()
    text = re.sub(r" ([,.;:!?])", r"\1", text)   # a tag before punctuation leaves a space there
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


class Tags(HTMLParser):
    """The <link>, <script> and <meta> attributes, link targets and <title> of a page."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.links, self.scripts, self.metas, self.anchors, self.title = [], [], [], [], ""
        self._in_title = False
        try:
            self.feed(markup)
        except Exception:
            pass

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value or "" for key, value in attrs}
        if tag == "link":
            self.links.append(attrs)
        elif tag == "script":
            self.scripts.append(attrs)
        elif tag == "meta":
            self.metas.append(attrs)
        elif tag == "a" and attrs.get("href"):
            self.anchors.append(attrs["href"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


# -------------------------------------------------------------- GitHub

def token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


TOKEN = token()


def graphql_reply(query, **variables):
    """The whole reply ({"data": ..., "errors": ...}), or None when GitHub gave no usable answer.

    Tried three times: these requests fail now and then for no lasting reason."""
    for pause in (0, 2, 6):
        time.sleep(pause)
        reply, refused = post_json(API_URL, {"query": query, "variables": variables}, TOKEN, timeout=30, limit=None)
        if refused in (401, 404):   # a bad token or address will not get better
            return None
        if isinstance(reply, dict) and reply.get("data") is not None:
            return reply
    return None


def graphql(query, **variables):
    """Returns the response's data, or None on any failure."""
    return (graphql_reply(query, **variables) or {}).get("data")


def repository(owner, name, fields):
    """The asked-for fields of a repository: {} when there is none, None when GitHub gave no answer."""
    data = graphql("query($owner:String!,$name:String!){repository(owner:$owner,name:$name){%s}}" % fields,
                   owner=owner, name=name)
    return None if data is None else data.get("repository") or {}


def whose_list():
    login = os.environ.get("FOLLOWING_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if login:
        return login
    data = graphql("{viewer{login}}")
    return data["viewer"]["login"] if data else None


LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def friends_of(people, skip):
    """The accounts followed by `people` (first 100 each) that are not in `skip`.

    Returns (found, complete): found is {login: {"person": account, "via": [who
    among `people` follows them]}}; complete is False when some following list
    could not be read, in which case `found` must not replace an earlier one."""
    found, complete = {}, True
    for start in range(0, len(people), 5):
        batch = [person for person in people[start:start + 5] if LOGIN.match(person["login"])]
        # One request for the batch: each account is an aliased field.
        fields = " ".join(
            'u%d: user(login: "%s") { following(first: 100) { nodes { login name websiteUrl avatarUrl(size: 96) '
            'followers { totalCount } } } }' % (index, person["login"]) for index, person in enumerate(batch))
        reply = graphql_reply("{ %s }" % fields)
        data = (reply or {}).get("data") or {}
        # An account that no longer exists is an answer; anything else missing is not.
        deleted = {error["path"][0] for error in (reply or {}).get("errors") or []
                   if error.get("type") == "NOT_FOUND" and error.get("path")}
        if any(data.get(f"u{index}") is None and f"u{index}" not in deleted for index in range(len(batch))):
            complete = False
        for index, person in enumerate(batch):
            for account in ((data.get(f"u{index}") or {}).get("following") or {}).get("nodes", []):
                if account["login"].lower() in skip:
                    continue
                entry = found.setdefault(account["login"], {"person": account, "via": []})
                entry["via"].append({"login": person["login"], "name": person.get("name") or person["login"]})
    return found, complete


def profile(login):
    data = graphql("query($login:String!){user(login:$login){login name url websiteUrl avatarUrl(size:192)}}", login=login)
    return (data or {}).get("user")


def following(login):
    """Returns (accounts, total): the accounts `login` follows, newest first."""
    query = ("query($login:String!,$after:String){user(login:$login){following(first:100,after:$after){"
             "totalCount pageInfo{hasNextPage endCursor} nodes{login name websiteUrl avatarUrl(size:96)}}}}")
    people, after, total = [], None, 0
    while len(people) < MAX_PEOPLE:
        data = graphql(query, login=login, after=after)
        if not data or not data.get("user"):
            return None, 0
        page = data["user"]["following"]
        people += page["nodes"]
        total = page["totalCount"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return people[:MAX_PEOPLE], total


# --------------------------------------------------------------- feeds

def timestamp(value):
    """Seconds since the epoch for an RFC 822 or ISO 8601 date, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            when = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return int(when.timestamp())


def name_of(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def xml_posts(base, body):
    """Returns (posts, author names) from an RSS or Atom feed."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], set()
    posts, authors = [], set()
    for item in root.iter():
        if name_of(item) in ("author", "creator", "managingeditor"):
            names = [child.text for child in item if name_of(child) == "name"] or [item.text]
            authors.update(squash(name) for name in names if name)
        if name_of(item) not in ("item", "entry"):
            continue
        fields, link = {}, None
        for child in item:
            name = name_of(child)
            fields.setdefault(name, "".join(child.itertext()))
            # Atom: <link href>, where rel="alternate" (or no rel) is the post itself
            if name == "link" and child.get("href") and child.get("rel", "alternate") == "alternate":
                link = link or child.get("href")
        link = link or fields.get("link", "").strip()
        posts.append({
            "title": plain(fields.get("title"), 200),
            "url": urljoin(base, link) if link else None,
            "ts": timestamp(fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("date")),
            "summary": plain(fields.get("description") or fields.get("summary") or fields.get("content") or fields.get("encoded")),
        })
    return posts, authors - {""}


def json_posts(base, body):
    """Returns (posts, author names) from a JSON Feed."""
    try:
        feed = json.loads(body)
    except ValueError:
        return [], set()
    if not isinstance(feed, dict) or "jsonfeed.org" not in str(feed.get("version", "")):
        return [], set()
    people = (feed.get("authors") or []) + [feed.get("author") or {}]
    authors = {squash(person.get("name")) for person in people if isinstance(person, dict)} - {""}
    return [{
        "title": plain(item.get("title"), 200),
        "url": urljoin(base, item["url"]) if item.get("url") else None,
        "ts": timestamp(item.get("date_published") or item.get("date_modified")),
        "summary": plain(item.get("summary") or item.get("content_html") or item.get("content_text")),
    } for item in feed.get("items", []) if isinstance(item, dict)], authors


def read_feed(url, validators=None):
    """Returns "same" for an unchanged feed, None for no usable feed, else
    (feed URL, posts newest first, author names, validators)."""
    status, final, body, fresh = fetch(url, validators)
    if status != "ok":
        return "same" if status == "same" else None
    posts, authors = json_posts(final, body) if body.lstrip()[:1] == b"{" else xml_posts(final, body)
    # Real posts only: titled, dated, not in the future
    now = time.time()
    posts = [post for post in posts if post["url"] and post["title"] and post["ts"]
             and post["ts"] < now + 86400 and not PLACEHOLDER_POST.search(post["url"])
             and urlparse(post["url"]).scheme in ("http", "https")]   # a feed is untrusted input
    posts.sort(key=lambda post: post["ts"], reverse=True)
    # A feed can list the same address twice; the newer entry stands.
    posts = list({post["url"]: post for post in reversed(posts)}.values())[::-1]
    return (final, posts, authors, fresh) if posts else None


# What find_feed returns when a profile link leads to an account on someone
# else's platform: no feed, and no use keeping one found there before.
ELSEWHERE = object()
BLOG_PATH = re.compile(r"^/(blog|posts?|writing|articles?|notes|essays)/?$", re.I)


def declared_feeds(base, tags):
    return [urljoin(base, link["href"]) for link in tags.links
            if "alternate" in link.get("rel", "").lower()
            and link.get("type", "").lower() in FEED_TYPES and link.get("href")]


def find_feed(site):
    """Returns (feed URL, posts, home page text, author names, validators,
    the page's address after any redirects) for a site.

    None means the site gave no usable answer (try again soon); False means
    it answered and has no feed; ELSEWHERE means the link leads on to an
    account on someone else's platform."""
    status, base, body, _ = fetch(site)
    if status != "ok":
        return False if status == "gone" else None
    if is_platform(base):
        return ELSEWHERE
    home = text_of(body)
    tags = Tags(home)
    # Then the usual paths at the site root, except on shared hosts
    # (dept.edu/~me), where the root's feed belongs to the institution.
    parts = urlparse(base)
    shared = parts.path.startswith("/~") or re.search(r"\.(edu|ac)(\.[a-z]{2})?$", parts.netloc)
    root = (base if base.endswith("/") else base + "/") if shared else urljoin(base, "/")
    for url in dict.fromkeys(declared_feeds(base, tags) + [urljoin(root, path) for path in FEED_PATHS]):
        feed = read_feed(url)
        if feed:
            return feed[0], feed[1], home, feed[2], feed[3], base
    # A landing page with the blog one level down: follow its "Blog" link.
    for href in dict.fromkeys(tags.anchors):
        page = urljoin(base, href)
        if host(page) != host(base) or not BLOG_PATH.match(urlparse(page).path):
            continue
        response = get(page)
        for url in declared_feeds(response[0], Tags(text_of(response[1]))) if response else []:
            feed = read_feed(url)
            if feed:
                return feed[0], feed[1], home, feed[2], feed[3], base
        break
    return False


# ------------------------------------------------------------ comments
# Blogs wire their comment widget up in many ways: a script tag, a few lines
# of inline JavaScript, a theme's bundled script. So the settings are looked
# for loosely, and where one is missing the likely values are tried in turn.

def near(page, word, span=1500):
    """The text around each place `word` appears, where a widget's settings sit."""
    return " ".join(page[max(0, match.start() - span):match.end() + span]
                    for match in re.finditer(re.escape(word), page, re.I))


def setting(text, name):
    """A widget setting, written as data-name="v", name: 'v' or setAttribute('data-name', 'v')."""
    match = (re.search(rf"""data-{name}["']\s*,\s*["']([^"']+)["']""", text)
             or re.search(rf"""(?:data-)?["']?{name}["']?\s*[:=]\s*["']([^"']+)["']""", text))
    return match.group(1) if match else None


def pages_repo_with_discussions(login):
    """<login>/<login>.github.io when it has Discussions on: where giscus usually points."""
    repo = repository(login, f"{login}.github.io", "nameWithOwner hasDiscussionsEnabled") or {}
    return repo.get("nameWithOwner") if repo.get("hasDiscussionsEnabled") else None


def comment_system(page, tags, login):
    """Where a blog's comments live, when they can be counted from outside."""
    for script in tags.scripts:
        src = script.get("src", "")
        if "giscus.app" in src and script.get("data-repo"):
            return {"system": "giscus", "repo": script["data-repo"],
                    "mapping": script.get("data-mapping", "pathname"), "term": script.get("data-term")}
        if "utteranc.es" in src and script.get("repo"):
            mapping = script.get("issue-term") or ("number" if script.get("issue-number") else "pathname")
            return {"system": "utterances", "repo": script["repo"], "mapping": mapping,
                    "term": script.get("issue-number")}
    if "giscus" in page.lower():
        around = near(page, "giscus")
        repo = setting(around, "repo")
        # The settings can sit in a script this page only links to. giscus
        # most often stores comments in the blog's own repository.
        repo = repo if repo and "/" in repo else pages_repo_with_discussions(login)
        if repo:
            return {"system": "giscus", "repo": repo, "mapping": setting(around, "mapping") or "pathname",
                    "term": setting(around, "term")}
    if "utteranc" in page.lower():
        around = near(page, "utteranc")
        repo = setting(around, "repo")
        if repo and "/" in repo:
            return {"system": "utterances", "repo": repo, "mapping": setting(around, "issue-term") or "pathname",
                    "term": None}
    match = re.search(r"new Gitalk\(\{(.{0,1500})", page, re.S)
    if match:
        repo, owner = setting(match.group(1), "repo"), setting(match.group(1), "owner")
        if repo and owner:
            return {"system": "gitalk", "repo": f"{owner}/{repo}"}
    match = (re.search(r"""disqus_shortname\s*=\s*["']([\w-]+)["']""", page)
             or re.search(r"""//([\w-]+)\.disqus\.com/(?:embed|count)\.js""", page))
    if match:
        return {"system": "disqus", "forum": match.group(1)}
    match = re.search(r"""twikoo\.init\(\{[^}]*?envId:\s*["'](https?://[^"']+)["']""", page, re.S)
    if match:
        return {"system": "twikoo", "server": match.group(1)}
    return None


def own_term(page, tags):
    """The discussion name or number a page sets for itself, if it does."""
    for script in tags.scripts:
        if "giscus.app" in script.get("src", "") or "utteranc.es" in script.get("src", ""):
            return script.get("data-term") or script.get("issue-number")
    return setting(near(page, "giscus"), "term")


def phrase(text):
    """Text made safe to quote inside a GitHub search."""
    return text.replace('"', " ").strip()


def thread_titles(comments, url, page, tags):
    """The titles a post's discussion may have, the configured one first.

    Returns [(mapping, title)]: giscus and utterances name a discussion after
    the page's path, address or title, depending on a setting that may not be
    readable from the page."""
    path = urlparse(url).path
    og_title = next((meta.get("content") for meta in tags.metas if meta.get("property") == "og:title"), None)
    by = {"pathname": "index" if len(path) < 2 else re.sub(r"\.\w+$", "", path[1:]), "url": url,
          "title": tags.title.strip() or None, "og:title": og_title}
    mapping = comments["mapping"].lower()
    # A fixed name or number is set page by page, so it is read from this page.
    first = (mapping, own_term(page, tags) if mapping in ("specific", "number") else by.get(mapping))
    order = [first] + [(kind, by[kind]) for kind in ("pathname", "url", "title", "og:title")]
    seen, titles = set(), []
    for kind, title in order:
        if title and title not in seen:
            seen.add(title)
            titles.append((kind, title))
    return titles


def github_thread(repo, discussion, query=None, number=None):
    """One Discussion or Issue, found by search or by number.

    By number: the thread, or False when there is none. By search: the list of
    matches. Either way None means GitHub gave no answer."""
    kind, typename = ("DISCUSSION", "Discussion") if discussion else ("ISSUE", "Issue")
    comments = "comments(first:100){totalCount nodes{replies{totalCount}}}" if discussion else "comments{totalCount}"
    fields = f"title url reactionGroups{{content reactors{{totalCount}}}} {comments}"
    if number is not None:
        owner, name = repo.split("/", 1)
        field = "discussion" if discussion else "issue"
        data = graphql("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                       "%s(number:$number){%s}}}" % (field, fields), owner=owner, name=name, number=number)
        return None if data is None else ((data.get("repository") or {}).get(field) or False)
    data = graphql("query($q:String!){search(type:%s,query:$q,first:5){nodes{... on %s{%s}}}}"
                   % (kind, typename, fields), q=f"repo:{repo} {query}")
    return None if data is None else [node for node in (data.get("search") or {}).get("nodes", []) if node]


def counts_of(node, source):
    replies = sum(reply["replies"]["totalCount"] for reply in node["comments"].get("nodes") or [])
    # A like is any reaction that is not a thumbs-down or a "confused".
    likes = sum(group["reactors"]["totalCount"] for group in node.get("reactionGroups") or []
                if group["content"] not in ("THUMBS_DOWN", "CONFUSED"))
    return {"source": source, "url": node["url"], "comments": node["comments"]["totalCount"] + replies,
            "likes": likes}


def github_threads(posts, comments, first_page):
    """Updates post["thread"] for a blog whose comments are GitHub Discussions or Issues.

    A post whose lookup gets no answer keeps the counts it had."""
    system, repo = comments["system"], comments["repo"]
    if "/" not in repo:
        return
    misses = 0
    for index, post in enumerate(posts):
        node, answered = None, True
        if system == "gitalk":
            # gitalk opens an issue titled after the page, with its address in the body
            address = host(post["url"]) + urlparse(post["url"]).path
            found = github_thread(repo, False, query=f'in:body "{address}"')
            if not found and found is not None:
                found = github_thread(repo, False, query=f'in:title "{phrase(post["title"])}"')
                found = found and [match for match in found if post["title"] in match.get("title", "")]
            answered, node = found is not None, (found or [None])[0]
        else:
            # The page itself is needed when the name comes from it; otherwise
            # only while it is still unclear which name this blog uses.
            from_page = comments["mapping"].lower() in ("title", "og:title", "specific", "number")
            if index == 0 and first_page is not None:
                page = first_page
            else:
                wanted = from_page or (misses < 3 and not comments.get("settled"))
                response = get(post["url"]) if wanted else None
                page = text_of(response[1]) if response else ""
            titles = thread_titles(comments, post["url"], page, Tags(page))
            # After a few posts with nothing under any name, stop trying them all.
            for kind, title in titles if misses < 3 else titles[:1]:
                if kind == "number":
                    found = github_thread(repo, system == "giscus", number=int(title)) if str(title).isdigit() else False
                else:
                    found = github_thread(repo, system == "giscus", query=f'in:title "{phrase(title)}"')
                    if found is not None:
                        found = next((match for match in found
                                      if match.get("title", "").strip().rstrip("/") == title.strip().rstrip("/")), False)
                if found is None:
                    answered = False
                    break
                if found:
                    node = found
                    # The name that worked goes first from now on.
                    comments["mapping"], comments["settled"] = kind, True
                    break
        if not answered:
            continue
        counts = counts_of(node, system) if node and "comments" in node else None
        if counts and (counts["comments"] or counts["likes"]):
            post["thread"] = counts
        else:
            post.pop("thread", None)
        misses = 0 if node else misses + 1


def disqus_threads(posts, forum):
    """Comment counts from Disqus's public counter, all posts in one request."""
    query = "&".join("2=" + quote(post["url"], safe="") for post in posts)
    response = get(f"https://{forum}.disqus.com/count-data.js?{query}")
    match = re.search(r"displayCount\((\{.*\})\)", text_of(response[1]), re.S) if response else None
    try:
        counts = {entry["id"]: entry["comments"] for entry in json.loads(match.group(1))["counts"]}
    except (AttributeError, ValueError, KeyError, TypeError):
        return   # no answer: the posts keep what they had
    for post in posts:
        if counts.get(post["url"]):
            post["thread"] = {"source": "disqus", "url": post["url"] + "#disqus_thread",
                              "comments": counts[post["url"]], "likes": 0}
        else:
            post.pop("thread", None)


def twikoo_threads(posts, server):
    """Comment counts from the blog's own Twikoo server, all posts in one request."""
    paths = {urlparse(post["url"]).path: post for post in posts}
    reply, _ = post_json(server, {"event": "GET_COMMENTS_COUNT", "urls": list(paths), "includeReply": True})
    if not isinstance(reply, dict) or not isinstance(reply.get("data"), list):
        return   # no answer: the posts keep what they had
    counts = {entry.get("url"): entry.get("count") for entry in reply["data"] if isinstance(entry, dict)}
    for path, post in paths.items():
        if counts.get(path):
            post["thread"] = {"source": "twikoo", "url": post["url"], "comments": counts[path], "likes": 0}
        else:
            post.pop("thread", None)


def read_threads(posts, comments, first_page):
    if comments["system"] == "disqus":
        disqus_threads(posts, comments["forum"])
    elif comments["system"] == "twikoo":
        twikoo_threads(posts, comments["server"])
    else:
        github_threads(posts, comments, first_page)


def address_key(url):
    parts = urlparse(url)
    return parts.netloc.lower().removeprefix("www.") + parts.path.rstrip("/")


def hacker_news(post):
    """Adds post["hn"] when the post was discussed on Hacker News."""
    response = get("https://hn.algolia.com/api/v1/search?restrictSearchableAttributes=url&hitsPerPage=5&query="
                   + quote(post["url"], safe=""))
    try:
        hits = json.loads(response[1])["hits"] if response else []
    except (ValueError, KeyError):
        return
    same = [hit for hit in hits if hit.get("url") and address_key(hit["url"]) == address_key(post["url"])]
    if not same:
        return
    best = max(same, key=lambda hit: hit.get("points") or 0)
    points, comments = best.get("points") or 0, best.get("num_comments") or 0
    if points >= 5 or comments >= 2:   # a submission nobody noticed says nothing
        post["hn"] = {"url": f"https://news.ycombinator.com/item?id={best['objectID']}",
                      "points": points, "comments": comments}


def add_hacker_news(blogs):
    """Looks up posts not seen before and recent ones; older ones keep what they had."""
    recent, old = time.time() - 14 * 86400, time.time() - 730 * 86400
    posts = [post for blog in blogs for post in blog["posts"]
             if post["ts"] > recent or (post["url"] not in SEEN and post["ts"] > old)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(hacker_news, posts))


# ------------------------------------------------------------- one blog

def is_platform(site):
    """Whether a profile link points at an account on someone else's platform."""
    name = host(site)
    return any(name == platform or name.endswith("." + platform) or name.startswith(platform + ".")
               for platform in NOT_A_BLOG)


def candidate_sites(person):
    sites = []
    website = (person.get("websiteUrl") or "").strip()
    if website:
        website = website if "://" in website else "https://" + website
        if not is_platform(website):
            sites.append(website)
    pages = f"https://{person['login'].lower()}.github.io/"
    if not any(host(site) == host(pages) for site in sites):
        sites.append(pages)
    return sites


def squash(text):
    """Lower-case letters and digits only, for loose name comparisons."""
    return re.sub(r"[\W_]+", "", (text or "").lower())


def belongs(page, feed):
    """Whether a feed is this page's own rather than that of the whole host
    the page sits on: medium.com/@them and medium.com/feed/@them, but not
    example.com/people/them and example.com/blog/feed.xml."""
    path = urlparse(page).path.rstrip("/").lower()
    if not path:
        return True   # the front page speaks for its host
    there = urlparse(feed).path.lower()
    return host(page) == host(feed) and (there.startswith(path + "/") or path.rsplit("/", 1)[-1] in there.split("/"))


def is_own_site(person, site, page, home, authors, feed):
    """Whether a feed found from someone's site is their own writing rather
    than, say, their employer's. None when that could not be found out today.

    `site` is the link that was followed, `page` is where it really leads,
    after any redirects, and `home` is what that page says."""
    login, name = person["login"].lower(), squash(person.get("name"))
    carries = lambda text: (len(squash(login)) >= 4 and squash(login) in text) or (len(name) >= 5 and name in text)
    # Their own Pages site, wherever it may lead on to
    if f"{login}.github.io" in (host(site), host(page)):
        return True
    # The address carries their login or name: danluu.com, simonwillison.net
    if carries(squash(host(page))):
        return True
    # The feed names them, and nobody else, as its author. A feed with several
    # authors is a team's or a company's blog.
    if len(name) >= 4 and authors and all(name in author or (len(author) >= 4 and author in name) for author in authors):
        return True
    # Their own corner of a host they share, with a feed of its own: dev.to/them
    own = belongs(page, feed)
    if own and carries(squash(urlparse(page).path)):
        return True
    # The page links back to their GitHub profile. On a page that is one of
    # many on its host, with a feed that is the host's and not the page's,
    # that says whose page it is, not whose feed: a profile on a company's
    # site sits beside the company's blog. There the host's front page has to
    # point back at them too.
    back = re.compile(rf"github\.com/{re.escape(login)}(?![\w-])")
    if back.search(home.lower()):
        if own:
            return True
        status, _, body, _ = fetch(urljoin(page, "/"))
        if status == "ok" and back.search(text_of(body).lower()):
            return True
        if status == "fail":
            return None
    # Their Pages repository's CNAME points at the site
    repo = repository(login, f"{login}.github.io", 'object(expression:"HEAD:CNAME"){... on Blob{text}}')
    if repo is None:
        return None
    cname = (repo.get("object") or {}).get("text") or ""
    return cname.strip().lower().removeprefix("www.") == host(page)


def months(dates):
    """Posts per month over the last 12 months, oldest first."""
    counts, now = [0] * 12, time.time()
    for ts in dates:
        index = 11 - int((now - ts) // (30.4 * 86400))
        if 0 <= index < 12:
            counts[index] += 1
    return counts


# What the previous run left behind, and what this one will leave.
OLD, NEW = {}, {}    # login (lower case) -> what is known about the account
BLOGS = {}           # login -> its blog entry in the previous list
SEEN = set()         # addresses of the posts in the previous list


RULES = 2                # goes up when the test for whose blog a site is gets stricter
KEEP_DOWN = 14 * 86400   # how long a blog that can't be read stays on the list
FORGET = 90 * 86400      # how long an account not looked at stays remembered


def patience(key, definite):
    """Seconds before an account without a blog is looked at again: about a
    month when the answer was definite, a few days when its site was just not
    answering. Spread out by name, so they don't all come due on one day."""
    spread = zlib.crc32(key.encode())
    return ((30 + spread % 10) if definite else (2 + spread % 3)) * 86400


def new_blog(person, site, feed, posts, earlier=()):
    """A blog's entry: the posts in its feed now, then the older ones seen on earlier runs.

    Within the stretch of time the feed covers, the feed is the truth: a post
    missing there was removed or moved by its author. Older than that, a post
    has only scrolled out of the feed, and stays."""
    oldest = min(post["ts"] for post in posts)
    current = {post["url"] for post in posts}
    before = {post["url"]: post for post in earlier}
    for post in posts:   # counts carried over until they are read again
        for field in ("thread", "hn"):
            if field in before.get(post["url"], {}):
                post[field] = before[post["url"]][field]
    kept = [post for post in earlier if post["ts"] < oldest and post["url"] not in current]
    return {"login": person["login"], "name": person.get("name") or person["login"],
            "avatar": person.get("avatarUrl"), "site": site, "host": host(site), "feed": feed,
            "self": bool(person.get("self")),
            "months": months(post["ts"] for post in posts + kept),
            "posts": (posts + kept)[:POSTS_PER_BLOG]}


def recent_dates(*lists):
    """Post times from the last 400 days, for the month squares."""
    start = time.time() - 400 * 86400
    return sorted({ts for dates in lists for ts in dates if ts > start})


def shown_on_discover(posts):
    """What the Discover list shows of a blog: its newest few posts, none older than a year."""
    year = time.time() - 365 * 86400
    return [post for post in posts if post["ts"] > year][:DISCOVER_POSTS]


def refresh_counts(posts, comments, first_page=None, full=True):
    """Reads comment and like counts again where they may have moved."""
    if not comments:
        return
    newest = posts[:COUNTED_POSTS] if full else shown_on_discover(posts)
    if comments["system"] in ("disqus", "twikoo"):   # one request covers them all
        todo = newest
    else:   # one request a post, so only new and recent ones
        recent = time.time() - 90 * 86400
        todo = [post for post in newest if post["url"] not in SEEN or post["ts"] > recent]
    if todo:
        read_threads(todo, comments, first_page if todo[0] is posts[0] else None)


def counts_again(person, blog, comments, full):
    """Reads the counts of a blog looked at before, where they may have moved. Returns its comment system."""
    counted = blog["posts"] if full else shown_on_discover(blog["posts"])
    page = None
    if counted and counted[0]["url"] not in SEEN:
        # A new post: a chance to notice comments the blog has added since.
        response = get(counted[0]["url"])
        page = text_of(response[1]) if response else None
        if page and not comments:
            comments = comment_system(page, Tags(page), person["login"])
    refresh_counts(blog["posts"], comments, page, full)
    return comments


def revisit(person, known, full):
    """The blog of an account whose feed is already known, or None if the feed has gone."""
    key = person["login"].lower()
    before = BLOGS.get(person["login"])
    # "Has it changed?" is only worth asking when the answer saves work. It
    # does when the old entry can be reused: it must hold as many posts as
    # asked for, and have been built from the whole feed rather than its first
    # few posts, as earlier versions did. And it does for a blog that had
    # nothing recent enough for Discover to show: unchanged, it still has not.
    dormant = not before and not full and not shown_on_discover([{"ts": ts} for ts in known.get("dates") or []])
    reusable = (before or dormant) and (known.get("full") or not full) and known.get("whole")
    feed = read_feed(known["feed"], known.get("validators") if reusable else None)
    if feed is None:
        return None
    comments = known.get("comments")
    if feed == "same" and not before:   # unchanged, and it had nothing recent enough to show
        NEW[key] = {**known, "checked": int(time.time()), "failing": None}
        return {"login": person["login"], "host": host(known["site"]), "posts": []}
    if feed == "same":
        blog = {**before, "name": person.get("name") or person["login"], "avatar": person.get("avatarUrl"),
                "self": bool(person.get("self")), "months": months(recent_dates(known.get("dates") or []))}
        blog.pop("via", None), blog.pop("via_count", None)
        refresh_counts(blog["posts"], comments, full=full)
        NEW[key] = {**known, "checked": int(time.time()), "failing": None}
        return blog
    address, posts, _, validators = feed
    blog = new_blog(person, known["site"], address, posts, (before or {}).get("posts", []))
    comments = counts_again(person, blog, comments, full)
    NEW[key] = {**known, "checked": int(time.time()), "feed": address, "validators": validators,
                "comments": comments, "full": full, "whole": True, "failing": None,
                "dates": recent_dates(known.get("dates") or [], [post["ts"] for post in posts])}
    return blog


def blog_of(person, full=True):
    """The person's blog with its recent posts, or None.

    `full` asks for a whole page of posts rather than the few Discover shows."""
    key = person["login"].lower()
    website = (person.get("websiteUrl") or "").strip()
    known = OLD.get(key)
    if known and known.get("website") == website:
        if known.get("feed"):
            # A blog let in under an older, laxer test is not taken on trust:
            # it is looked at again from the start, below.
            if known.get("rules", 1) >= RULES:
                blog = revisit(person, known, full)
                if blog:
                    return blog
        elif time.time() - known["checked"] < patience(key, known.get("definite", True)):
            NEW[key] = known
            return None
    answered, not_theirs = False, False
    for site in candidate_sites(person):
        found = find_feed(site)
        if found is ELSEWHERE:
            answered = not_theirs = True
            continue
        answered = answered or found is not None
        if not found:
            continue
        feed, posts, home, authors, validators, landed = found
        own = is_own_site(person, site, landed, home, authors, feed)
        if own is None:
            answered = False   # no telling today, which counts as no answer
            break
        if not own:
            not_theirs = True
            break
        # A blog known before keeps the older posts it has built up.
        same = known and known.get("feed") == feed
        blog = new_blog(person, site, feed, posts, (BLOGS.get(person["login"]) or {}).get("posts", []) if same else ())
        counted = blog["posts"][:COUNTED_POSTS] if full else shown_on_discover(blog["posts"])
        if same:
            comments = counts_again(person, blog, known.get("comments"), full)
        elif counted:
            # The newest post's page tells where the blog's comments live.
            response = get(blog["posts"][0]["url"])
            page = text_of(response[1]) if response else None
            comments = comment_system(page, Tags(page), person["login"]) if page else None
            if comments:
                read_threads(counted, comments, page)
        else:
            comments = None
        NEW[key] = {"website": website, "checked": int(time.time()), "site": site, "feed": feed,
                    "validators": validators, "comments": comments, "rules": RULES,
                    "dates": recent_dates((known.get("dates") or []) if same else [], [post["ts"] for post in posts]),
                    "full": full, "whole": True}
        return blog
    if known and known.get("feed") and known.get("website") == website and not not_theirs:
        # A blog found before can't be read today. It stays as it was, and is
        # tried again next time; only after two weeks of this is it let go.
        # (One that turned out not to be theirs goes at once.)
        since = known.get("failing") or int(time.time())
        NEW[key] = {**known, "failing": since}
        before = BLOGS.get(person["login"])
        if before and time.time() - since < KEEP_DOWN:
            kept = {**before, "name": person.get("name") or person["login"], "avatar": person.get("avatarUrl"),
                    "self": bool(person.get("self"))}
            kept.pop("via", None), kept.pop("via_count", None)
            return kept
        return None
    NEW[key] = {"website": website, "checked": int(time.time()), "feed": None, "definite": answered}
    return None


# ------------------------------------------------------------- reposts

MARK = re.compile(r"<!--\s*followroll\s+(\{.*?\})\s*-->", re.S)
WRITERS = ("OWNER", "MEMBER", "COLLABORATOR")   # whose discussions are the repository's own
OLD_ROLLS, NEW_ROLLS = {}, {}   # login (lower case) -> what is known about their followroll page


def roll_address(login):
    """Where `login`'s own followroll page is, if they have one."""
    return f"https://{login.lower()}.github.io/{REPO}/"


def short(value, limit):
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def repost(entry):
    """A repost with just the fields the page uses, or None if it names no post.

    `entry` may come from someone else's page, so nothing in it is taken on trust."""
    if not isinstance(entry, dict):
        return None
    url, when = short(entry.get("url"), 500), entry.get("ts")
    if not url.startswith(("http://", "https://")) or not isinstance(when, (int, float)):
        return None
    login, source = short(entry.get("login"), 40), short(entry.get("source"), 300)
    return {"url": url, "title": short(entry.get("title"), 300) or url, "author": short(entry.get("author"), 100),
            "login": login if LOGIN.match(login) else "", "note": short(entry.get("note"), 500),
            "ts": int(when), "source": source if source.startswith("https://github.com/") else ""}


def own_reposts(login):
    """What the owner reposted, newest first, or None when GitHub gave no answer.

    A repost is an open discussion in this repository, started by someone who
    can push to it, that carries a `<!-- followroll {...} -->` line naming the
    post. Whatever else it says is the note. Deleting or closing it takes the
    repost back."""
    owner, _, name = (os.environ.get("GITHUB_REPOSITORY") or f"{login}/{REPO}").partition("/")
    repo = repository(owner, name, "discussions(first:100,states:[OPEN],orderBy:{field:CREATED_AT,direction:DESC}){"
                                   "nodes{title body url createdAt authorAssociation}}")
    if repo is None:
        return None
    found = []
    for thread in (repo.get("discussions") or {}).get("nodes") or []:
        match = MARK.search(thread.get("body") or "")
        if not match or thread.get("authorAssociation") not in WRITERS:
            continue
        try:
            about = json.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(about, dict):
            continue
        note = plain(re.sub(r"<!--.*?-->", " ", thread["body"], flags=re.S), 500)
        entry = repost({**about, "title": thread.get("title"), "note": note,
                        "ts": timestamp(thread.get("createdAt")), "source": thread.get("url")})
        if entry:
            found.append(entry)
    return found[:REPOSTS]


def roll_of(person):
    """What is known about a followed person's own followroll page: its address
    and what they reposted there. None when there was no answer and nothing is
    known from before."""
    key, now = person["login"].lower(), int(time.time())
    known = OLD_ROLLS.get(key)
    # Someone without a page is asked again about a day later, spread out by
    # name: a page made today should show in its followers' pages tomorrow.
    if known and not known.get("page") and now - known["checked"] < (20 + zlib.crc32(key.encode()) % 6) * 3600:
        return known
    status, final, body, validators = fetch(roll_address(key) + "reposts.json", (known or {}).get("validators"))
    if status == "same":
        return {**known, "checked": now}
    if status == "ok":
        try:
            theirs = json.loads(body)
        except ValueError:
            theirs = None
        if isinstance(theirs, dict) and isinstance(theirs.get("reposts"), list) and final.startswith("https://"):
            entries = [entry for entry in map(repost, theirs["reposts"][:REPOSTS]) if entry]
            return {"checked": now, "page": final.rsplit("/", 1)[0] + "/", "validators": validators, "reposts": entries}
        status = "gone"   # something else lives at that address
    if status == "gone":
        return {"checked": now, "page": None}
    return known   # no answer today: what was known stays


def reposts_of(owner, followed, cache):
    """Returns (reposts, pages): the owner's reposts and those of the people
    they follow, newest first, each with who it is `by`; and the address of
    every followed person's own followroll page, by login."""
    mine = own_reposts(owner["login"])
    if mine is None:   # no answer: the ones known before stay
        mine = [entry for entry in (cache or {}).get("reposts", []) if entry["by"]["login"] == owner["login"]]
    me = {"login": owner["login"], "name": owner["name"] or owner["login"], "avatar": owner["avatarUrl"], "page": None}
    reposts, pages = [{**entry, "by": me} for entry in mine], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rolls = list(pool.map(roll_of, followed))
    for person, roll in zip(followed, rolls):
        if roll:
            NEW_ROLLS[person["login"].lower()] = roll
        if roll and roll.get("page"):
            pages[person["login"]] = roll["page"]
            by = {"login": person["login"], "name": person.get("name") or person["login"],
                  "avatar": person.get("avatarUrl"), "page": roll["page"]}
            reposts += [{**entry, "by": by} for entry in roll.get("reposts") or []]
    reposts.sort(key=lambda entry: entry["ts"], reverse=True)
    for entry in reposts:
        entry["date"] = iso(entry["ts"])
    return reposts[:MAX_POSTS], pages


# ------------------------------------------------------------ releases

RELEASE = re.compile(r"^v?(\d+(?:\.\d+){0,2})$")


def latest_release():
    """The newest release of followroll, {"version": "1.2.0", "url": its notes}, or None when unknown."""
    request = urllib.request.Request(f"https://api.github.com/repos/{UPSTREAM}/releases/latest", headers={
        "Authorization": f"Bearer {TOKEN}", "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            release = json.loads(response.read(MAX_BYTES))
    except Exception:
        return None
    match = RELEASE.match(str(release.get("tag_name") or "")) if isinstance(release, dict) else None
    url = str(release.get("html_url") or "") if match else ""
    return {"version": match.group(1), "url": url} if url.startswith("https://github.com/") else None


def is_newer(version, than):
    numbers = lambda text: [int(part) for part in text.split(".")] + [0, 0]
    return numbers(version)[:3] > numbers(than)[:3]


# --------------------------------------------------------- translation
# Optional. With DEEPSEEK_API_KEY set, post titles and summaries are translated
# when the page is built: Chinese into English, everything else into Chinese.
# The page shows a post in the reader's language and lets them turn it back.

TRANSLATE_URL = "https://api.deepseek.com/chat/completions"
TRANSLATE_KEY = os.environ.get("DEEPSEEK_API_KEY") or ""
TRANSLATE_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
TRANSLATE_MAX_CHARS = int(os.environ.get("TRANSLATE_MAX_CHARS") or 300_000)
TRANSLATE_BATCH = 20           # posts sent in one request, at most
TRANSLATE_BATCH_CHARS = 5000   # and characters, so that what comes back fits in one answer
TRANSLATE_WORKERS = 4          # requests at a time
TRANSLATE_TIMEOUT = 90         # seconds to wait for one answer
TRANSLATE_SECONDS = 300        # no request starts after this long: what is left waits for the next run
PROMPT_VERSION = 1       # goes up when the prompt changes, so that everything is translated again
LANGUAGES = {"zh": "Simplified Chinese", "en": "English"}
PROMPT = """You translate the titles and summaries of blog posts for a reading list into {language}.

The input is a JSON object. Each value has a "title" and a "summary". Reply with a JSON object that has exactly the same keys, each value holding the "title" and the "summary" translated into {language}. Translate faithfully and naturally, the way a careful human translator would. Leave code, product names, numbers and URLs as they are, and keep people's names written in Latin letters exactly as they are: never turn a pinyin name into Chinese characters. A summary may be cut off mid-sentence: translate what is there and keep its trailing "…". Keep an empty summary empty. Reply with the JSON object only."""


class Refused(Exception):
    """DeepSeek will not take requests on this key: it is wrong, or out of credit."""


def target_language(text):
    """Chinese text goes into English and everything else into Chinese; None when there is nothing to translate."""
    han, words = len(re.findall(r"[\u4e00-\u9fff]", text)), len(re.findall(r"[A-Za-z]+", text))
    if not han and not words:
        return "zh" if re.search(r"[^\W\d_]", text) else None   # another script altogether
    return "en" if han > words else "zh"


def translation_key(lang, title, summary):
    return hashlib.sha256(json.dumps([PROMPT_VERSION, lang, title, summary]).encode()).hexdigest()[:20]


def words(post):
    """The title and summary of a post: what gets translated."""
    return post["title"], post.get("summary") or ""


def known_translations():
    """The translations the previous list carries, by what they are translations of."""
    known = {}
    for blog in BLOGS.values():
        for post in blog["posts"]:
            tr = post.get("tr")
            if isinstance(tr, dict) and tr.get("lang") in LANGUAGES and tr.get("title"):
                known[translation_key(tr["lang"], *words(post))] = tr
    return known


def ask_deepseek(items, lang):
    """Translates {id: {"title", "summary"}} into `lang`. Returns the ones that
    came back well formed, in the same shape; the tokens used; and whether the
    rest is worth asking for again in smaller pieces, which it is when DeepSeek
    turned the request down as it stands or its answer was cut short. Raises
    Refused when the key is no good."""
    body = {"model": TRANSLATE_MODEL,
            "messages": [{"role": "system", "content": PROMPT.replace("{language}", LANGUAGES[lang])},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            "thinking": {"type": "disabled"}, "max_tokens": 8192, "stream": False}
    unfit = (400, 413, 422)   # the request itself will not do
    for pause in (0, 5):
        time.sleep(pause)
        reply, refused = post_json(TRANSLATE_URL, body, TRANSLATE_KEY, timeout=TRANSLATE_TIMEOUT, limit=None)
        if refused in (401, 402):
            raise Refused("the key was not accepted" if refused == 401 else "the account is out of credit")
        if reply is not None or refused is None or refused in unfit:
            break   # an answer, silence, or a plain no: the same again would get the same
    if reply is None and refused not in unfit:
        return {}, 0, False   # no answer today
    try:
        text = reply["choices"][0]["message"]["content"]
        answer = json.loads(text[text.index("{"):text.rindex("}") + 1])   # with or without a code fence around it
    except Exception:
        answer = None   # turned down, or cut short
    done = {}
    for name, source in items.items():
        got = answer.get(name) if isinstance(answer, dict) else None
        if isinstance(got, dict) and short(got.get("title"), 300) and isinstance(got.get("summary", ""), str):
            done[name] = {"lang": lang, "title": short(got["title"], 300),
                          "summary": short(got.get("summary", ""), 600) if source["summary"] else ""}
    usage = (reply.get("usage") if isinstance(reply, dict) else None) or {}
    return done, usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0), True


def translate(blogs):
    """Gives each post its translation: the one made before where its words
    have not changed, and a new one from DeepSeek where a key is set. A post
    that cannot be translated today simply goes without until next time."""
    known, waiting, reused = known_translations(), {"zh": [], "en": []}, 0
    for blog in blogs:
        for post in blog["posts"]:
            post.pop("tr", None)
            title, summary = words(post)
            lang = target_language(f"{title}\n{summary}")
            if not lang:
                continue
            key = translation_key(lang, title, summary)
            if key in known:
                post["tr"], reused = known[key], reused + 1
            else:
                waiting[lang].append(post)
    left = sum(len(posts) for posts in waiting.values())
    if not TRANSLATE_KEY:
        if reused:
            print(f"translation: {reused} kept from before, {left} new ones waiting for a DeepSeek key")
        return
    # The newest first, and no more characters in all than the limit for one
    # run. A batch is as many posts as will fit in one answer.
    batches, budget = [], TRANSLATE_MAX_CHARS
    for lang, posts in waiting.items():
        posts.sort(key=lambda post: post["ts"], reverse=True)
        batch, size = [], 0
        for post in posts:
            length = sum(map(len, words(post)))
            budget -= length
            if budget < 0:
                break
            if batch and (len(batch) == TRANSLATE_BATCH or size + length > TRANSLATE_BATCH_CHARS):
                batches.append((lang, batch))
                batch, size = [], 0
            batch.append(post)
            size += length
        if batch:
            batches.append((lang, batch))
    deadline = time.time() + TRANSLATE_SECONDS

    def ask(batch):
        """Translates a batch. What does not come back is asked for again in
        halves, down to single posts, so that one post DeepSeek will not take,
        or an answer cut short, does not hold back the posts sent with it."""
        lang, posts = batch
        if time.time() > deadline:
            return 0, 0
        done, tokens, again = ask_deepseek(
            {str(index): dict(zip(("title", "summary"), words(post))) for index, post in enumerate(posts)}, lang)
        for index, post in enumerate(posts):
            if str(index) in done:
                post["tr"] = done[str(index)]
        made, rest = len(done), [post for index, post in enumerate(posts) if str(index) not in done]
        if again and rest and len(posts) > 1:
            half = (len(rest) + 1) // 2
            for part in filter(None, (rest[:half], rest[half:])):
                more, used = ask((lang, part))
                made, tokens = made + more, tokens + used
        return made, tokens

    made = tokens = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=TRANSLATE_WORKERS) as pool:
            for count, used in pool.map(ask, batches):
                made, tokens = made + count, tokens + used
    except Refused as refusal:
        print(f"::warning::Posts were not translated: DeepSeek says {refusal}.")
    print(f"translation: {reused} kept from before, {made} new ({tokens} tokens, {TRANSLATE_MODEL}), {left - made} still waiting")


# ---------------------------------------------------------------- main

def previous_url(name):
    """Where the last run published a file: this repository's Pages site."""
    if os.environ.get("FOLLOWING_PREVIOUS_URL"):
        return os.environ["FOLLOWING_PREVIOUS_URL"].rsplit("/", 1)[0] + "/" + name
    owner = os.environ.get("GITHUB_REPOSITORY", "").partition("/")[0]
    return roll_address(owner) + name if owner else None


def load_previous(output, name):
    """A file from the previous run: the local copy, else the published one."""
    local = output / name
    try:
        if local.exists():
            return json.loads(local.read_text(encoding="utf-8"))
        response = get(previous_url(name)) if previous_url(name) else None
        return json.loads(response[1]) if response else None
    except ValueError:
        return None


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dated(blogs):
    """Gives every post its date in the form the page reads. Returns the blogs."""
    for blog in blogs:
        for post in blog["posts"]:
            post["date"] = iso(post["ts"])
    return blogs


def within_budget(blogs):
    """Trims the oldest posts across all blogs once there are more than MAX_POSTS."""
    every = sorted((post["ts"] for blog in blogs for post in blog["posts"]), reverse=True)
    if len(every) > MAX_POSTS:
        for blog in blogs:   # a blog always keeps its newest post
            blog["posts"] = blog["posts"][:1] + [post for post in blog["posts"][1:] if post["ts"] >= every[MAX_POSTS - 1]]
    return blogs


def discover(people, taken, before):
    """Blogs one step further out: accounts followed by the people you follow.

    `before` is the previous run's Discover list, kept as it is when this run
    could not read every following list: half the picture would rank
    different people to the top and drop the rest."""
    known = {person["login"].lower() for person in people}
    candidates, complete = friends_of([person for person in people if not person.get("self")], known)
    if not complete and before:
        print("discover: GitHub did not return every following list, keeping the previous Discover list",
              file=sys.stderr)
        return before
    # Those followed by most of your follows first, then the widely followed.
    ranked = sorted(candidates.values(), key=lambda entry: (
        -len(entry["via"]), -entry["person"]["followers"]["totalCount"], entry["person"]["login"].lower()
    ))[:DISCOVER_LIMIT]
    # Everyone an earlier run looked at costs little now (their verdict is
    # remembered), so they all stay in; on top, a batch never seen before.
    unseen = [entry for entry in ranked if entry["person"]["login"].lower() not in OLD]
    batch = {id(entry) for entry in unseen[:DISCOVER_PEOPLE]}
    ranked = [entry for entry in ranked if entry["person"]["login"].lower() in OLD or id(entry) in batch]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        found = list(pool.map(lambda entry: blog_of(entry["person"], full=False), ranked))
    blogs, year = [], time.time() - 365 * 86400
    for entry, blog in zip(ranked, found):
        if not blog or blog["host"] in taken:
            continue
        blog["posts"] = [post for post in blog["posts"] if post["ts"] > year][:DISCOVER_POSTS]
        if blog["posts"]:
            blog["via"], blog["via_count"] = entry["via"][:3], len(entry["via"])
            blogs.append(blog)
    hosts = collections.Counter(blog["host"] for blog in blogs)
    blogs = [blog for blog in blogs if hosts[blog["host"]] == 1]
    # Most vouched-for first; the page orders the posts by date itself.
    blogs.sort(key=lambda blog: (-blog["via_count"], -blog["posts"][0]["ts"]))
    add_hacker_news(blogs)
    return {"candidates": len(candidates), "looked_at": len(ranked), "waiting": len(unseen) - len(batch),
            "blogs": dated(blogs)}


def collect(cache, state):
    """Returns the new list, or None when GitHub can't be read."""
    login = whose_list() if TOKEN else None
    if not login:
        return None
    owner = profile(login)
    people, total = following(login)
    if owner is None or people is None:
        return None
    before = (cache or {}).get("blogs", []) + ((cache or {}).get("discover") or {}).get("blogs", [])
    OLD.update((state or {}).get("people") or {})
    OLD_ROLLS.update((state or {}).get("rolls") or {})
    BLOGS.update({blog["login"]: blog for blog in before})
    SEEN.update(post["url"] for blog in before for post in blog["posts"])
    # The owner's own blog is part of their timeline too.
    people = people + [{**owner, "self": True}]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        blogs = list(pool.map(blog_of, people))
    blogs = [blog for blog in blogs if blog]
    # A host several accounts point at is an employer or a platform.
    hosts = collections.Counter(blog["host"] for blog in blogs)
    blogs = [blog for blog in blogs if hosts[blog["host"]] == 1 and blog["posts"]]
    blogs.sort(key=lambda blog: blog["posts"][0]["ts"], reverse=True)
    add_hacker_news(blogs)
    name = owner["name"] or owner["login"]
    found = discover(people, set(hosts), (cache or {}).get("discover")) if DISCOVER_PEOPLE else None
    reposts, pages = reposts_of(owner, people[:-1], cache)
    latest = latest_release() or (cache or {}).get("latest")   # no answer: the last one known
    # Accounts this run did not get to are not forgotten straight away.
    for key, entry in OLD.items():
        if key not in NEW and time.time() - entry.get("checked", 0) < FORGET:
            NEW[key] = entry
    blogs = dated(within_budget(blogs))
    translate(blogs + ((found or {}).get("blogs") or []))
    return {"updated": iso(time.time()),
            "owner": {"login": owner["login"], "name": name, "avatar": owner["avatarUrl"], "url": owner["url"]},
            "title": os.environ.get("FOLLOWING_TITLE") or name,
            "following": total, "looked_at": len(people) - 1,
            "blogs": blogs, "discover": found, "reposts": reposts, "rolls": pages,
            "latest": latest}


def write_page(output, result):
    """Copies the page next to the list, with the list and its title filled in."""
    shutil.copytree(HERE / "site", output, dirs_exist_ok=True)
    fields = {
        "title": html.escape(f"{result['title']} · followroll"),
        "description": html.escape(f"Recent posts from the blogs of the people @{result['owner']['login']} follows on GitHub."),
        "avatar": html.escape(result["owner"]["avatar"]),
        # Inside <script>, only a closing tag could end the element early.
        "data": json.dumps(result, ensure_ascii=False).replace("</", "<\\/"),
    }
    page = (HERE / "site" / "index.html").read_text(encoding="utf-8")
    page = re.sub(r"\{\{(\w+)\}\}", lambda match: fields[match.group(1)], page)
    # A changed stylesheet or script gets a new address, so a browser never
    # pairs a cached old one with the new page.
    for name in ("style.css", "app.js"):
        digest = hashlib.sha256((HERE / "site" / name).read_bytes()).hexdigest()[:10]
        page = page.replace(f'"{name}"', f'"{name}?v={digest}"')
    (output / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", default="_site", help="folder to write the page into (default: _site)")
    parser.add_argument("--no-page", action="store_true", help="write following.json only")
    args = parser.parse_args()
    output = Path(args.output)

    # Other people's pages look for this one at <owner>.github.io/followroll/.
    name = os.environ.get("GITHUB_REPOSITORY", "").partition("/")[2]
    if name and name != REPO:
        sys.exit(f'::error::This repository is called "{name}", but it has to be called "{REPO}": that is the '
                 "address other followroll pages look for yours at. Rename it under Settings → General.")

    cache = load_previous(output, "following.json")
    result = collect(cache, load_previous(output, "state.json"))
    if result is None:
        if cache is None:
            sys.exit("following: GitHub not readable (no token, or the API call failed) and no earlier list to reuse")
        result = cache
        print("following: GitHub not readable, reusing the earlier list", file=sys.stderr)
    # This copy's own version and repository, whatever an earlier list said.
    result["version"] = VERSION
    result["repo"] = os.environ.get("GITHUB_REPOSITORY") or f"{result['owner']['login']}/{REPO}"
    latest = result.get("latest")
    if latest and is_newer(latest["version"], VERSION):
        print(f"::notice::followroll {latest['version']} is out and this copy is {VERSION}. "
              f"Press Sync fork on the repository's page to update. What's new: {latest['url']}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "following.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    # The owner's own reposts, for the pages of the people who follow them.
    owner = result["owner"]
    mine = [{field: value for field, value in entry.items() if field not in ("by", "date")}
            for entry in result.get("reposts", []) if entry["by"]["login"] == owner["login"]]
    (output / "reposts.json").write_text(json.dumps(
        {"login": owner["login"], "name": owner["name"], "reposts": mine}, ensure_ascii=False, indent=1), encoding="utf-8")
    if NEW:   # only a run that looked has something new to remember
        (output / "state.json").write_text(json.dumps({"people": NEW, "rolls": NEW_ROLLS}, ensure_ascii=False), encoding="utf-8")
    if not args.no_page:
        write_page(output, result)
    print(f"following: {sum(not blog.get('self') for blog in result['blogs'])} blogs among {result['looked_at']} accounts, "
          f"{sum(len(blog['posts']) for blog in result['blogs'])} posts, updated {result['updated']}")
    if result.get("reposts"):
        print(f"reposts: {len(mine)} of the owner's own, {len(result['reposts']) - len(mine)} by the people they follow, "
              f"{len(result.get('rolls') or {})} of whom have a followroll page")
    if result.get("discover"):
        found = result["discover"]
        print(f"discover: {len(found['blogs'])} active blogs among the {found['looked_at']} second-degree accounts "
              f"looked at so far, {found.get('waiting', 0)} of {found['candidates']} still to look at")


if __name__ == "__main__":
    main()
