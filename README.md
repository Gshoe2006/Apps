# App portal

One page where customers can see every app, its latest version, what changed and
where to download it, and subscribe to updates by RSS. Built from GitHub Releases and
published on GitHub Pages. Nothing to host and no customer data stored.

- **Home page:** every public app with its latest version and release date.
- **One page per app:** the latest release notes and downloads, then earlier releases.
- **RSS (Atom) feeds:** one per app (`<app>/feed.xml`) and one for everything (`feed.xml`).
  Customers subscribe to only the apps they use, in any feed reader or by email through
  a feed-to-email service.

## Which apps appear

Every repository on the account that is **public, not a fork, not archived, and has at
least one published release**. A new app shows up by itself the first time you publish a
release. Drafts and pre-releases are left out.

To hide an app, add its name to `exclude` in `portal.json`. That file also sets the site
`title`, the `intro` line under it, and `include_prereleases`.

## How it updates

`.github/workflows/portal.yml` rebuilds the site:

- on every push to `main`,
- every 3 hours, which picks up new releases,
- when you press **Actions → Build and publish the app portal → Run workflow**.

### Optional: refresh the moment you publish a release

Add this workflow to an app repo. It needs a fine-grained personal access token with
**Contents: read and write** on this portal repo only, saved in the app repo as the secret
`PORTAL_TOKEN`:

```yaml
# .github/workflows/notify-portal.yml in an app repo
name: Tell the app portal
on:
  release:
    types: [published]
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -fsS -X POST \
            -H "Authorization: Bearer ${{ secrets.PORTAL_TOKEN }}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/${{ github.repository_owner }}/apps/dispatches \
            -d '{"event_type":"app-released"}'
```

Replace `apps` in the URL if you named the portal repo something else.

## First-time setup

1. In this repo, open **Settings → Pages** and set **Source** to **GitHub Actions**.
2. Push to `main`, or run the workflow. The site is published at
   `https://<your-login>.github.io/<this-repo>/`.

## Change the look

All colours, spacing and type sizes are variables at the top of `theme.css`, with a dark
version underneath.

## Run it locally

```sh
python3 -m unittest discover -s tests            # tests, offline
python3 build.py --fixtures tests/fixtures --owner Gshoe2006   # offline preview in site/
GITHUB_TOKEN=... python3 build.py --owner Gshoe2006            # real data
```

Standard library Python 3 only. No dependencies.
