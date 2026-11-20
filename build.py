#!/usr/bin/env python3
"""Build the app portal: one static site listing every public app on a GitHub
account with its latest release, its release history and an Atom feed.

Standard library only. Run by .github/workflows/portal.yml; to try it locally:

    GITHUB_TOKEN=... python3 build.py --owner YOUR_LOGIN
    python3 build.py --fixtures tests/fixtures --owner demo   # offline
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com"
RELEASES_PER_APP = 20


# ---------------------------------------------------------------- fetching --

class GitHub:
    def __init__(self, token=None, fixtures=None):
        self.token = token
        self.fixtures = Path(fixtures) if fixtures else None

    def get(self, path, fixture):
        if self.fixtures:
            f = self.fixtures / fixture
            return json.loads(f.read_text()) if f.exists() else []
        req = urllib.request.Request(API + path, headers={
            # html+json adds body_html: release notes rendered and sanitised by GitHub
            "Accept": "application/vnd.github.html+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "app-portal-builder",
        })
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def repos(self, owner):
        out, page = [], 1
        while True:
            batch = self.get(f"/users/{owner}/repos?type=owner&per_page=100&page={page}",
                             "repos.json")
            out += batch
            if self.fixtures or len(batch) < 100:
                return out
            page += 1

    def releases(self, owner, name):
        rel = self.get(f"/repos/{owner}/{name}/releases?per_page={RELEASES_PER_APP}",
                       f"releases-{name}.json")
        return [r for r in rel if not r.get("draft")]


def load_config():
    f = ROOT / "portal.json"
    cfg = json.loads(f.read_text()) if f.exists() else {}
    cfg.setdefault("title", "")
    cfg.setdefault("intro", "")
    cfg.setdefault("exclude", [])
    cfg.setdefault("include_prereleases", False)
    return cfg


def collect(gh, owner, cfg, portal_repo):
    excluded = {n.lower() for n in cfg["exclude"]} | {portal_repo.lower()}
    apps = []
    for repo in gh.repos(owner):
        if (repo.get("private") or repo.get("fork") or repo.get("archived")
                or repo["name"].lower() in excluded):
            continue
        releases = gh.releases(owner, repo["name"])
        if not cfg["include_prereleases"]:
            releases = [r for r in releases if not r.get("prerelease")]
        if not releases:
            continue  # an app appears once it has published a release
        releases.sort(key=lambda r: r.get("published_at") or "", reverse=True)
        apps.append({"repo": repo, "releases": releases})
    apps.sort(key=lambda a: a["releases"][0]["published_at"], reverse=True)
    return apps


# --------------------------------------------------------------- rendering --

def esc(s):
    return html.escape(s or "", quote=True)


def when(iso):
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f'<time datetime="{esc(iso)}">{d.strftime("%-d %B %Y")}</time>'


def size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


def notes(rel, demote_to=3):
    """GitHub's sanitised HTML, with headings moved below the page's own."""
    body = rel.get("body_html") or ""
    if not body.strip():
        return '<p class="muted">No release notes.</p>'

    def shift(m):
        level = min(6, int(m.group(2)) + demote_to - 1)
        return f"<{m.group(1)}h{level}"
    return re.sub(r"<(/?)h([1-6])", shift, body)


def release_title(rel):
    name, tag = (rel.get("name") or "").strip(), rel["tag_name"]
    return name or tag


def version(rel):
    return rel["tag_name"].lstrip("vV")


def downloads(rel):
    assets = rel.get("assets") or []
    if not assets:
        return ""
    items = "".join(
        f'<li><a href="{esc(a["browser_download_url"])}">{esc(a["name"])}</a>'
        f' <span class="muted">{size(a["size"])}</span></li>' for a in assets)
    return f'<ul class="downloads" aria-label="Downloads">{items}</ul>'


def page(title, body, base, feed_href, feed_title, description):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="stylesheet" href="{base}theme.css">
<link rel="alternate" type="application/atom+xml" title="{esc(feed_title)}" href="{feed_href}">
</head>
<body>
{body}
<footer class="site-footer"><div class="wrap">
<p class="muted">Updated {when(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))} from GitHub Releases.</p>
</div></footer>
</body>
</html>
"""


def header(site_title, base, crumb=None):
    trail = f'<span aria-hidden="true">/</span> <span>{esc(crumb)}</span>' if crumb else ""
    return f"""<header class="site-header"><div class="wrap">
<nav aria-label="Breadcrumb"><a href="{base}">{esc(site_title)}</a> {trail}</nav>
</div></header>"""


def subscribe(feed_href, repo_url, label):
    return f"""<div class="subscribe">
<a class="button" href="{feed_href}">Subscribe to {esc(label)} updates (RSS)</a>
<a class="button secondary" href="{esc(repo_url)}/releases">Watch releases on GitHub</a>
</div>"""


def render_index(apps, cfg, owner):
    title = cfg["title"] or f"{owner}'s apps"
    intro = cfg["intro"] or "The latest version of every app, what changed, and where to download it."
    cards = []
    for a in apps:
        repo, latest = a["repo"], a["releases"][0]
        name = repo["name"]
        cards.append(f"""<li class="card">
<h2><a href="{esc(name)}/">{esc(name)}</a></h2>
<p>{esc(repo.get("description") or "")}</p>
<p class="meta"><span class="badge">{esc(version(latest))}</span> released {when(latest["published_at"])}</p>
<p class="card-links"><a href="{esc(name)}/">What's new</a>
<a href="{esc(name)}/feed.xml">RSS feed</a></p>
</li>""")
    empty = '<p class="empty">No apps have published a release yet. They appear here as soon as they do.</p>'
    body = f"""{header(title, "./")}
<main class="wrap">
<h1>{esc(title)}</h1>
<p class="lede">{esc(intro)}</p>
<div class="subscribe"><a class="button" href="feed.xml">Subscribe to every app (RSS)</a></div>
{f'<ul class="cards">{"".join(cards)}</ul>' if cards else empty}
</main>"""
    return page(title, body, "", "feed.xml", f"{title} (all apps)", intro)


def render_app(app, cfg, owner):
    site_title = cfg["title"] or f"{owner}'s apps"
    repo, rels = app["repo"], app["releases"]
    name, latest = repo["name"], rels[0]
    links = [f'<a href="{esc(repo["html_url"])}">Source on GitHub</a>']
    if repo.get("homepage"):
        links.insert(0, f'<a href="{esc(repo["homepage"])}">Website</a>')
    older = "".join(f"""<article class="release">
<h3 id="v{esc(version(r))}">{esc(release_title(r))}</h3>
<p class="meta"><span class="badge">{esc(version(r))}</span> released {when(r["published_at"])}
· <a href="{esc(r["html_url"])}">On GitHub</a></p>
<details><summary>Release notes and downloads</summary>
<div class="notes">{notes(r, 4)}</div>
{downloads(r)}
</details>
</article>""" for r in rels[1:])
    body = f"""{header(site_title, "../", name)}
<main class="wrap">
<h1>{esc(name)}</h1>
<p class="lede">{esc(repo.get("description") or "")}</p>
<p class="card-links">{" ".join(links)}</p>
{subscribe("feed.xml", repo["html_url"], name)}
<section class="latest" aria-labelledby="latest">
<h2 id="latest">Latest: {esc(release_title(latest))}</h2>
<p class="meta"><span class="badge">{esc(version(latest))}</span> released {when(latest["published_at"])}
· <a href="{esc(latest["html_url"])}">On GitHub</a></p>
{downloads(latest)}
<div class="notes">{notes(latest, 3)}</div>
</section>
{f'<section aria-labelledby="earlier"><h2 id="earlier">Earlier releases</h2>{older}</section>' if older else ""}
</main>"""
    return page(f"{name}: {site_title}", body, "../", "feed.xml",
                f"{name} updates", repo.get("description") or name)


def render_feed(feed_id, title, self_url, alt_url, entries):
    def entry(app, r):
        name = app["repo"]["name"]
        return f"""<entry>
<id>{esc(r["html_url"])}</id>
<title>{esc(name)} {esc(version(r))}: {esc(release_title(r))}</title>
<link rel="alternate" type="text/html" href="{esc(r["html_url"])}"/>
<published>{r["published_at"]}</published>
<updated>{r["published_at"]}</updated>
<author><name>{esc(name)}</name></author>
<content type="html">{esc(notes(r, 2) + downloads(r))}</content>
</entry>"""
    updated = entries[0][1]["published_at"] if entries else \
        dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<id>{esc(feed_id)}</id>
<title>{esc(title)}</title>
<updated>{updated}</updated>
<link rel="self" href="{esc(self_url)}"/>
<link rel="alternate" type="text/html" href="{esc(alt_url)}"/>
{"".join(entry(a, r) for a, r in entries)}
</feed>
"""


def build(apps, cfg, owner, out, site_url):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(ROOT / "theme.css", out / "theme.css")
    (out / ".nojekyll").write_text("")
    site_url = site_url.rstrip("/") + "/"
    title = cfg["title"] or f"{owner}'s apps"

    (out / "index.html").write_text(render_index(apps, cfg, owner))
    everything = sorted(((a, r) for a in apps for r in a["releases"]),
                        key=lambda e: e[1]["published_at"], reverse=True)[:50]
    (out / "feed.xml").write_text(render_feed(
        site_url, f"{title} (all apps)", site_url + "feed.xml", site_url, everything))

    for a in apps:
        name = a["repo"]["name"]
        d = out / name
        d.mkdir()
        (d / "index.html").write_text(render_app(a, cfg, owner))
        url = f"{site_url}{name}/"
        (d / "feed.xml").write_text(render_feed(
            url, f"{name} updates", url + "feed.xml", url,
            [(a, r) for r in a["releases"]]))
    return len(apps)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--owner", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    p.add_argument("--out", default="site")
    p.add_argument("--site-url", default=os.environ.get("SITE_URL", ""))
    p.add_argument("--fixtures", help="read API responses from this folder instead")
    args = p.parse_args()
    if not args.owner:
        sys.exit("Pass --owner or set GITHUB_REPOSITORY_OWNER.")
    portal_repo = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or ROOT.name
    site_url = args.site_url or f"https://{args.owner.lower()}.github.io/{portal_repo}/"

    gh = GitHub(os.environ.get("GITHUB_TOKEN"), args.fixtures)
    try:
        apps = collect(gh, args.owner, load_config(), portal_repo)
    except urllib.error.HTTPError as e:
        sys.exit(f"GitHub API error {e.code} for {e.url}: {e.read().decode()[:300]}")
    n = build(apps, load_config(), args.owner, ROOT / args.out, site_url)
    print(f"Built {n} app page(s) into {args.out}/")


if __name__ == "__main__":
    main()
