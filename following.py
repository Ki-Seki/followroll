#!/usr/bin/env python3
"""Build a page of recent posts from the blogs of the people someone follows on GitHub.

For each followed account the script looks for a personal site (the website on
the GitHub profile, then <login>.github.io), finds its feed, and keeps it only
when the site is that person's own: it is their GitHub Pages site, their Pages
repository's CNAME points at it, or its home page links back to their GitHub
profile. Nobody has to opt in or change anything on their blog.

Comment and reaction counts are read wherever that works without logging in:
GitHub Discussions (giscus), GitHub Issues (utterances, gitalk), Disqus and
Twikoo. A post that was discussed on Hacker News gets its points and comment
count from there.

The Discover list looks one step further: the accounts followed by the people
you follow. The ones most of them follow are tried first.

Writes following.json into the output folder, next to the page that displays
it (the files in site/), and state.json, what this run learned about each
account. The next run reads both back from the published site: someone known
to have no blog is left alone for a month, a known feed is asked only whether
it has changed, and older posts keep the counts they had. When GitHub can't be
read, the previous list is reused, and so is a blog that is down during a run.

Usage: following.py [--output DIR] [--no-page]

Environment (an empty value counts as unset):
  GITHUB_TOKEN / GH_TOKEN   token for the GitHub API; `gh auth token` is tried next
  FOLLOWING_LOGIN           whose following list to read (default: the repository
                            owner on GitHub Actions, else the token's own account)
  FOLLOWING_TITLE           page title (default: "<name> is following")
  FOLLOWING_PREVIOUS_URL    where the previous run's following.json is published
                            (default: this repository's GitHub Pages address)
  FOLLOWING_MAX_PEOPLE      most followed accounts to look at, newest first (default: 500)
  FOLLOWING_DISCOVER        most second-degree accounts to look at for the Discover
                            list; 0 turns it off (default: 200)
  FOLLOWING_WORKERS         concurrent sites (default: 24)
"""

import argparse
import base64
import calendar
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
API_URL = "https://api.github.com/graphql"
USER_AGENT = "Mozilla/5.0 (compatible; followroll/1.0; +https://github.com/Ki-Seki/followroll)"
TIMEOUT = 12
MAX_BYTES = 3_000_000
MAX_PEOPLE = int(os.environ.get("FOLLOWING_MAX_PEOPLE") or 500)
WORKERS = int(os.environ.get("FOLLOWING_WORKERS") or 24)
DISCOVER_PEOPLE = int(os.environ.get("FOLLOWING_DISCOVER") or 200)
POSTS_PER_BLOG = 10   # posts kept per blog
DISCOVER_POSTS = 3    # posts kept per blog on the Discover list, none older than a year
MAX_POSTS = 200       # posts kept in all

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


def post_json(url, body):
    """POSTs JSON and returns the decoded JSON reply, or None."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read(MAX_BYTES))
    except Exception:
        return None


def text_of(body):
    return body.decode("utf-8", errors="replace")


def plain(markup, limit=200):
    """HTML to one line of text, cut at `limit` characters."""
    markup = re.sub(r"<(script|style)\b.*?</\1>", " ", markup or "", flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()
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


def graphql(query, **variables):
    """Returns the response's data, or None on any failure."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {TOKEN}", "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read()).get("data")
    except Exception:
        return None


def whose_list():
    login = os.environ.get("FOLLOWING_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if login:
        return login
    data = graphql("{viewer{login}}")
    return data["viewer"]["login"] if data else None


LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def friends_of(people, skip):
    """The accounts followed by `people` (first 100 each) that are not in `skip`.

    Returns {login: {"person": account, "via": [who among `people` follows them]}}."""
    found = {}
    for start in range(0, len(people), 15):
        batch = [person for person in people[start:start + 15] if LOGIN.match(person["login"])]
        # One request for the whole batch: each account is an aliased field.
        fields = " ".join(
            'u%d: user(login: "%s") { following(first: 100) { nodes { login name websiteUrl avatarUrl(size: 96) '
            'followers { totalCount } } } }' % (index, person["login"]) for index, person in enumerate(batch))
        data = graphql("{ %s }" % fields) or {}
        for index, person in enumerate(batch):
            for account in ((data.get(f"u{index}") or {}).get("following") or {}).get("nodes", []):
                if account["login"].lower() in skip:
                    continue
                entry = found.setdefault(account["login"], {"person": account, "via": []})
                entry["via"].append({"login": person["login"], "name": person.get("name") or person["login"]})
    return found


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
    return (final, posts, authors, fresh) if posts else None


BLOG_PATH = re.compile(r"^/(blog|posts?|writing|articles?|notes|essays)/?$", re.I)


def declared_feeds(base, tags):
    return [urljoin(base, link["href"]) for link in tags.links
            if "alternate" in link.get("rel", "").lower()
            and link.get("type", "").lower() in FEED_TYPES and link.get("href")]


def find_feed(site):
    """Returns (feed URL, posts, home page text, author names, validators) for a site.

    None means the site gave no usable answer (try again soon); False means
    it answered and has no feed."""
    status, base, body, _ = fetch(site)
    if status != "ok":
        return False if status == "gone" else None
    home = text_of(body)
    tags = Tags(home)
    # Then the usual paths at the site root, except on shared hosts
    # (dept.edu/~me), where the root's feed belongs to the institution.
    parts = urlparse(base)
    shared = parts.path.startswith("/~") or re.search(r"\.(edu|ac)(\.[a-z]{2})?$", parts.netloc)
    root = (base if base.endswith("/") else base + "/") if shared else f"{parts.scheme}://{parts.netloc}/"
    for url in dict.fromkeys(declared_feeds(base, tags) + [urljoin(root, path) for path in FEED_PATHS]):
        feed = read_feed(url)
        if feed:
            return feed[0], feed[1], home, feed[2], feed[3]
    # A landing page with the blog one level down: follow its "Blog" link.
    for href in dict.fromkeys(tags.anchors):
        page = urljoin(base, href)
        if host(page) != host(base) or not BLOG_PATH.match(urlparse(page).path):
            continue
        response = get(page)
        for url in declared_feeds(response[0], Tags(text_of(response[1]))) if response else []:
            feed = read_feed(url)
            if feed:
                return feed[0], feed[1], home, feed[2], feed[3]
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
    data = graphql("query($owner:String!,$name:String!){repository(owner:$owner,name:$name){"
                   "nameWithOwner hasDiscussionsEnabled}}", owner=login, name=f"{login}.github.io")
    repo = (data or {}).get("repository") or {}
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
    """Comment and reaction counts of one Discussion or Issue, found by search or by number."""
    kind, typename = ("DISCUSSION", "Discussion") if discussion else ("ISSUE", "Issue")
    comments = "comments(first:100){totalCount nodes{replies{totalCount}}}" if discussion else "comments{totalCount}"
    fields = f"title url reactionGroups{{content reactors{{totalCount}}}} {comments}"
    if number is not None:
        owner, name = repo.split("/", 1)
        field = "discussion" if discussion else "issue"
        data = graphql("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                       "%s(number:$number){%s}}}" % (field, fields), owner=owner, name=name, number=number)
        return ((data or {}).get("repository") or {}).get(field)
    data = graphql("query($q:String!){search(type:%s,query:$q,first:5){nodes{... on %s{%s}}}}"
                   % (kind, typename, fields), q=f"repo:{repo} {query}")
    return [node for node in ((data or {}).get("search") or {}).get("nodes", []) if node]


def counts_of(node, source):
    replies = sum(reply["replies"]["totalCount"] for reply in node["comments"].get("nodes") or [])
    # A like is any reaction that is not a thumbs-down or a "confused".
    likes = sum(group["reactors"]["totalCount"] for group in node.get("reactionGroups") or []
                if group["content"] not in ("THUMBS_DOWN", "CONFUSED"))
    return {"source": source, "url": node["url"], "comments": node["comments"]["totalCount"] + replies,
            "likes": likes}


def github_threads(posts, comments, first_page):
    """Fills in post["thread"] for a blog whose comments are GitHub Discussions or Issues."""
    system, repo = comments["system"], comments["repo"]
    if "/" not in repo:
        return
    misses = 0
    for index, post in enumerate(posts):
        node = None
        if system == "gitalk":
            # gitalk opens an issue titled after the page, with its address in the body
            address = host(post["url"]) + urlparse(post["url"]).path
            nodes = github_thread(repo, False, query=f'in:body "{address}"')
            if not nodes:
                nodes = [found for found in github_thread(repo, False, query=f'in:title "{phrase(post["title"])}"')
                         if post["title"] in found.get("title", "")]
            node = nodes[0] if nodes else None
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
                    node = github_thread(repo, system == "giscus", number=int(title)) if str(title).isdigit() else None
                else:
                    found = github_thread(repo, system == "giscus", query=f'in:title "{phrase(title)}"')
                    exact = [n for n in found if n.get("title", "").strip().rstrip("/") == title.strip().rstrip("/")]
                    node = (exact or [None])[0]
                if node:
                    # The name that worked goes first from now on.
                    comments["mapping"], comments["settled"] = kind, True
                    break
        if node and "comments" in node:
            misses = 0
            counts = counts_of(node, system)
            if counts["comments"] or counts["likes"]:
                post["thread"] = counts
        else:
            misses += 1


def disqus_threads(posts, forum):
    """Comment counts from Disqus's public counter, all posts in one request."""
    query = "&".join("2=" + quote(post["url"], safe="") for post in posts)
    response = get(f"https://{forum}.disqus.com/count-data.js?{query}")
    match = re.search(r"displayCount\((\{.*\})\)", text_of(response[1]), re.S) if response else None
    try:
        counts = {entry["id"]: entry["comments"] for entry in json.loads(match.group(1))["counts"]} if match else {}
    except (ValueError, KeyError, TypeError):
        counts = {}
    for post in posts:
        if counts.get(post["url"]):
            post["thread"] = {"source": "disqus", "url": post["url"] + "#disqus_thread",
                              "comments": counts[post["url"]], "likes": 0}


def twikoo_threads(posts, server):
    """Comment counts from the blog's own Twikoo server, all posts in one request."""
    paths = {urlparse(post["url"]).path: post for post in posts}
    reply = post_json(server, {"event": "GET_COMMENTS_COUNT", "urls": list(paths), "includeReply": True})
    for entry in (reply or {}).get("data") or []:
        if isinstance(entry, dict) and entry.get("count") and entry.get("url") in paths:
            paths[entry["url"]]["thread"] = {"source": "twikoo", "url": paths[entry["url"]]["url"],
                                             "comments": entry["count"], "likes": 0}


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
    recent = time.time() - 14 * 86400
    posts = [post for blog in blogs for post in blog["posts"]
             if post["url"] not in SEEN or post["ts"] > recent]
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


def is_own_site(person, site, home, authors):
    """Whether a site is this account's own rather than, say, their employer's."""
    login, name = person["login"].lower(), squash(person.get("name"))
    if host(site) == f"{login}.github.io":
        return True
    # The home page links back to their GitHub profile
    if re.search(rf"github\.com/{re.escape(login)}(?![\w-])", home.lower()):
        return True
    # The address carries their login or name: danluu.com, simonwillison.net
    address = squash(host(site))
    if (len(squash(login)) >= 4 and squash(login) in address) or (len(name) >= 5 and name in address):
        return True
    # The feed names them, and nobody else, as its author. A feed with several
    # authors is a team's or a company's blog.
    if len(name) >= 4 and authors and all(name in author or (len(author) >= 4 and author in name) for author in authors):
        return True
    # Their Pages repository's CNAME points at the site
    data = graphql('query($owner:String!,$name:String!){repository(owner:$owner,name:$name){'
                   'object(expression:"HEAD:CNAME"){... on Blob{text}}}}', owner=login, name=f"{login}.github.io")
    cname = (((data or {}).get("repository") or {}).get("object") or {}).get("text") or ""
    return cname.strip().lower().removeprefix("www.") == host(site)


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


def patience(key, definite):
    """Seconds before an account without a blog is looked at again: about a
    month when the answer was definite, a few days when its site was just not
    answering. Spread out by name, so they don't all come due on one day."""
    spread = zlib.crc32(key.encode())
    return ((30 + spread % 10) if definite else (2 + spread % 3)) * 86400


def new_blog(person, site, feed, posts):
    return {"login": person["login"], "name": person.get("name") or person["login"],
            "avatar": person.get("avatarUrl"), "site": site, "host": host(site), "feed": feed,
            "self": bool(person.get("self")),
            "months": months(post["ts"] for post in posts),
            "posts": posts[:POSTS_PER_BLOG]}


def refresh_counts(posts, comments, first_page=None):
    """Reads comment and like counts again where they may have moved."""
    if not comments:
        return
    if comments["system"] in ("disqus", "twikoo"):   # one request covers every post
        todo = posts
    else:   # one request a post, so only new and recent ones
        recent = time.time() - 90 * 86400
        todo = [post for post in posts if post["url"] not in SEEN or post["ts"] > recent]
    for post in todo:
        post.pop("thread", None)
    if todo:
        read_threads(todo, comments, first_page if todo[0] is posts[0] else None)


def revisit(person, known, full):
    """The blog of an account whose feed is already known, or None if the feed has gone."""
    key = person["login"].lower()
    before = BLOGS.get(person["login"])
    # "Has it changed?" is only worth asking when the old entry can be reused.
    reusable = before and (known.get("full") or not full)
    feed = read_feed(known["feed"], known.get("validators") if reusable else None)
    if feed is None:
        return None
    comments = known.get("comments")
    if feed == "same":
        blog = {**before, "name": person.get("name") or person["login"], "avatar": person.get("avatarUrl"),
                "self": bool(person.get("self")), "months": months(known.get("dates") or [])}
        blog.pop("via", None), blog.pop("via_count", None)
        refresh_counts(blog["posts"], comments)
        NEW[key] = {**known, "checked": int(time.time())}
        return blog
    address, posts, _, validators = feed
    blog = new_blog(person, known["site"], address, posts)
    earlier = {post["url"]: post for post in (before or {}).get("posts", [])}
    for post in blog["posts"]:   # counts carried over until they are read again
        for field in ("thread", "hn"):
            if field in earlier.get(post["url"], {}):
                post[field] = earlier[post["url"]][field]
    page = None
    if blog["posts"][0]["url"] not in SEEN:
        # A new post: a chance to notice comments the blog has added since.
        response = get(blog["posts"][0]["url"])
        page = text_of(response[1]) if response else None
        if page and not comments:
            comments = comment_system(page, Tags(page), person["login"])
    refresh_counts(blog["posts"], comments, page)
    NEW[key] = {**known, "checked": int(time.time()), "feed": address, "validators": validators,
                "comments": comments, "dates": [post["ts"] for post in posts], "full": full}
    return blog


def blog_of(person, full=True):
    """The person's blog with its recent posts, or None.

    `full` asks for a whole page of posts rather than the few Discover shows."""
    key = person["login"].lower()
    website = (person.get("websiteUrl") or "").strip()
    known = OLD.get(key)
    if known and known.get("website") == website:
        if known.get("feed"):
            blog = revisit(person, known, full)
            if blog:
                return blog
            NEW[key] = known   # not answering today: same again next time
        elif time.time() - known["checked"] < patience(key, known.get("definite", True)):
            NEW[key] = known
            return None
    answered = False
    for site in candidate_sites(person):
        found = find_feed(site)
        answered = answered or found is not None
        if not found:
            continue
        feed, posts, home, authors, validators = found
        if not is_own_site(person, site, home, authors):
            break
        blog = new_blog(person, site, feed, posts)
        # The newest post's page tells where the blog's comments live.
        response = get(blog["posts"][0]["url"])
        page = text_of(response[1]) if response else None
        comments = comment_system(page, Tags(page), person["login"]) if page else None
        if comments:
            read_threads(blog["posts"], comments, page)
        NEW[key] = {"website": website, "checked": int(time.time()), "site": site, "feed": feed,
                    "validators": validators, "comments": comments,
                    "dates": [post["ts"] for post in posts], "full": full}
        return blog
    if not (known and known.get("feed")):   # a known blog that is down is not forgotten
        NEW[key] = {"website": website, "checked": int(time.time()), "feed": None, "definite": answered}
    return None


# ---------------------------------------------------------------- main

def previous_url(name):
    """Where the last run published a file: this repository's Pages site."""
    if os.environ.get("FOLLOWING_PREVIOUS_URL"):
        return os.environ["FOLLOWING_PREVIOUS_URL"].rsplit("/", 1)[0] + "/" + name
    owner, _, repo = os.environ.get("GITHUB_REPOSITORY", "").partition("/")
    if not repo:
        return None
    base = f"https://{owner.lower()}.github.io/"
    return base + ("" if repo.lower() == f"{owner.lower()}.github.io" else repo + "/") + name


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


def timeline(blogs):
    """Dates the posts and returns them all, newest first, each with its author."""
    for blog in blogs:
        for post in blog["posts"]:
            post["date"] = iso(post["ts"])
    return sorted(({**post, "login": blog["login"], "name": blog["name"], "avatar": blog["avatar"]}
                   for blog in blogs for post in blog["posts"]), key=lambda post: post["ts"], reverse=True)


def discover(people, taken):
    """Blogs one step further out: accounts followed by the people you follow."""
    known = {person["login"].lower() for person in people}
    candidates = friends_of([person for person in people if not person.get("self")], known)
    # Those followed by most of your follows first, then the widely followed.
    ranked = sorted(candidates.values(), key=lambda entry: (
        -len(entry["via"]), -entry["person"]["followers"]["totalCount"]))[:DISCOVER_PEOPLE]
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
    return {"candidates": len(candidates), "looked_at": len(ranked), "blogs": blogs, "posts": timeline(blogs)}


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
    BLOGS.update({blog["login"]: blog for blog in before})
    SEEN.update(post["url"] for blog in before for post in blog["posts"])
    # The owner's own blog is part of their timeline too.
    people = people + [{**owner, "self": True}]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        blogs = list(pool.map(blog_of, people))
    # A blog that is down right now keeps its entry from the previous run.
    known = {blog["login"]: blog for blog in (cache or {}).get("blogs", [])}
    reachable = {person["login"] for person, blog in zip(people, blogs) if blog}
    blogs = [blog for blog in blogs if blog]
    blogs += [blog for person in people if person["login"] not in reachable
              and (blog := known.get(person["login"])) and get(blog["site"]) is None]
    # A host several accounts point at is an employer or a platform.
    hosts = collections.Counter(blog["host"] for blog in blogs)
    blogs = [blog for blog in blogs if hosts[blog["host"]] == 1 and blog["posts"]]
    blogs.sort(key=lambda blog: blog["posts"][0]["ts"], reverse=True)
    add_hacker_news(blogs)
    name = owner["name"] or owner["login"]
    return {"updated": iso(time.time()),
            "owner": {"login": owner["login"], "name": name, "avatar": owner["avatarUrl"], "url": owner["url"]},
            "title": os.environ.get("FOLLOWING_TITLE") or f"{name} is following",
            "following": total, "looked_at": len(people) - 1,
            "blogs": blogs, "posts": timeline(blogs)[:MAX_POSTS],
            "discover": discover(people, set(hosts)) if DISCOVER_PEOPLE else None}


def write_page(output, result):
    """Copies the page next to the list, with the list and its title filled in."""
    shutil.copytree(HERE / "site", output, dirs_exist_ok=True)
    fields = {
        "title": html.escape(result["title"]),
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

    cache = load_previous(output, "following.json")
    result = collect(cache, load_previous(output, "state.json"))
    if result is None:
        if cache is None:
            sys.exit("following: GitHub not readable (no token, or the API call failed) and no earlier list to reuse")
        result = cache
        print("following: GitHub not readable, reusing the earlier list", file=sys.stderr)
    output.mkdir(parents=True, exist_ok=True)
    (output / "following.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if NEW:   # only a run that looked has something new to remember
        (output / "state.json").write_text(json.dumps({"people": NEW}, ensure_ascii=False), encoding="utf-8")
    if not args.no_page:
        write_page(output, result)
    print(f"following: {sum(not blog.get('self') for blog in result['blogs'])} blogs among {result['looked_at']} accounts, "
          f"{len(result['posts'])} posts, updated {result['updated']}")
    if result.get("discover"):
        found = result["discover"]
        print(f"discover: {len(found['blogs'])} active blogs among the {found['looked_at']} most followed "
              f"of {found['candidates']} second-degree accounts")


if __name__ == "__main__":
    main()
