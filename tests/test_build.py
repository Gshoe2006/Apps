import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
ATOM = "{http://www.w3.org/2005/Atom}"
CFG = {"title": "", "intro": "", "exclude": [], "include_prereleases": False}


class PortalTest(unittest.TestCase):
    def setUp(self):
        gh = build.GitHub(fixtures=FIXTURES)
        self.apps = build.collect(gh, "Gshoe2006", dict(CFG), "apps")
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "site"
        build.build(self.apps, dict(CFG), "Gshoe2006", self.out, "https://example.test/apps/")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_public_released_apps(self):
        # forks, private, archived, the portal itself and repos with no release are left out
        self.assertEqual([a["repo"]["name"] for a in self.apps], ["inkline"])

    def test_exclude_list(self):
        gh = build.GitHub(fixtures=FIXTURES)
        cfg = dict(CFG, exclude=["Inkline"])
        self.assertEqual(build.collect(gh, "Gshoe2006", cfg, "apps"), [])

    def test_pages_written(self):
        for f in ["index.html", "feed.xml", "theme.css", "inkline/index.html", "inkline/feed.xml"]:
            self.assertTrue((self.out / f).exists(), f)
        index = (self.out / "index.html").read_text()
        latest = self.apps[0]["releases"][0]
        self.assertIn(build.version(latest), index)
        self.assertIn('href="inkline/feed.xml"', index)

    def test_release_headings_sit_below_the_page(self):
        app = (self.out / "inkline/index.html").read_text()
        self.assertEqual(app.count("<h1"), 1)

    def test_feeds_are_valid_atom(self):
        for f in ["feed.xml", "inkline/feed.xml"]:
            root = ET.parse(self.out / f).getroot()
            entries = root.findall(ATOM + "entry")
            self.assertEqual(len(entries), len(self.apps[0]["releases"]), f)
            self.assertTrue(entries[0].find(ATOM + "content").text)

    def test_no_apps_page(self):
        out = Path(self.tmp.name) / "empty"
        build.build([], dict(CFG), "Gshoe2006", out, "https://example.test/apps/")
        self.assertIn("No apps have published a release yet", (out / "index.html").read_text())
        ET.parse(out / "feed.xml")


if __name__ == "__main__":
    unittest.main()
