"""garage-050 F1b: the fonts are ours, the service worker holds them, and they are there without a network (spec D4, F1b, §7.2)."""
import hashlib
import json
import os
import re
import tempfile
from unittest import mock
from urllib.parse import urljoin

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from django.urls import reverse

from test_support import contrast

from .assets import VERSIONED, asset_url, asset_version

FIGTREE, OUTFIT = "figtree-latin-wght-v1.woff2", "outfit-latin-wght-v1.woff2"
# The figures of PROCEDENCIA.md, written here by hand: read from a file beside the fonts, they would follow any swap.
SHA256 = {
    FIGTREE: "8330490a01c60c196eae00b823de8102275aaa5862e7b76a7af21b8745338928",
    OUTFIT: "92684e4acde79ef07758cd09380b7e01e9824d8b061eddeda046f78c166d7b12",
    "OFL-Figtree.txt": "140d37233e7f3ce7313798befa9600893bcceaf41a55fa0fa5ad52f7f657a268",
    "OFL-Outfit.txt": "c676351bf8576b9aba743cd5eaa8c0e7ee0d51f805d720447b4df4ddb6a2e416",
}
LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, "
         "U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
MOST_BYTES = 61440  # 60 KiB; they weigh 52 412 today.


def font_path(name):
    found = finders.find(f"garage/fonts/{name}")
    if not found:
        raise AssertionError(f"garage/fonts/{name} is not among the static files")
    return found


def stylesheet():
    with open(finders.find("garage/garage.css"), encoding="utf-8") as sheet:
        return sheet.read()


def requested_urls():
    """What the browser would ask for: every url() of the stylesheet, as written, comments left out."""
    bare = re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.DOTALL)
    return re.findall(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""", bare)


def font_faces():
    return {dict(contrast.declarations(rule.body)).get("font-family", "").strip("\"'"): dict(contrast.declarations(rule.body))
            for rule in contrast.rules(stylesheet()) if rule.selector == "@font-face"}


class ProvenanceTests(SimpleTestCase):
    def test_each_file_is_the_one_downloaded_with_permission(self):
        for name, expected in SHA256.items():
            with self.subTest(file=name), open(font_path(name), "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), expected)

    def test_the_fonts_stay_small(self):
        self.assertLessEqual(os.path.getsize(font_path(FIGTREE)) + os.path.getsize(font_path(OUTFIT)), MOST_BYTES)


class FontFaceTests(SimpleTestCase):
    def test_there_is_one_face_per_family_and_nothing_else(self):
        rules = [rule for rule in contrast.rules(stylesheet()) if rule.selector == "@font-face"]
        self.assertEqual(len(rules), 2)
        self.assertEqual(sorted(font_faces()), ["Figtree", "Outfit"])

    def test_each_face_says_its_file_its_weights_how_it_swaps_and_what_it_covers(self):
        for family, name, weights in (("Figtree", FIGTREE, "400 700"), ("Outfit", OUTFIT, "500 700")):
            with self.subTest(family=family):
                face = font_faces().get(family, {})
                self.assertEqual(face.get("src"), f'url(fonts/{name}) format("woff2")')
                self.assertEqual(face.get("font-weight"), weights)
                self.assertEqual(face.get("font-display"), "swap")
                self.assertEqual(face.get("unicode-range"), LATIN)


class PrecacheTests(SimpleTestCase):
    """The worker finds a request in its cache by the whole URL, query included, so a font precached under
    any other URL would be missing offline and downloaded twice."""

    def setUp(self):
        body = self.client.get(reverse("garage:service-worker")).content.decode()
        self.assets = json.loads(re.search(r"^const ASSETS = (\[.*\]);$", body, re.MULTILINE).group(1))

    def test_the_stylesheet_asks_for_the_two_fonts_and_nothing_else(self):
        self.assertEqual(sorted(requested_urls()), [f"fonts/{FIGTREE}", f"fonts/{OUTFIT}"])

    def test_what_the_stylesheet_asks_for_is_what_the_worker_stores(self):
        urls = requested_urls()
        self.assertEqual(len(urls), 2)
        for url in urls:
            with self.subTest(url=url):
                requested = urljoin(asset_url("garage/garage.css"), url)
                self.assertIn(requested, self.assets)
                self.assertNotIn("v=", requested)

    def test_each_font_is_stored_once(self):
        fonts = [asset for asset in self.assets if ".woff2" in asset]
        self.assertEqual(sorted(fonts), [f"/static/garage/fonts/{FIGTREE}", f"/static/garage/fonts/{OUTFIT}"])

    def test_everything_else_keeps_its_version_query(self):
        others = [asset for asset in self.assets if ".woff2" not in asset]
        self.assertIn(f"/static/garage/garage.css?v={asset_version()}", others)
        self.assertIn(f"/static/garage/garage.js?v={asset_version()}", others)
        self.assertEqual([asset for asset in others if not asset.endswith(f"?v={asset_version()}")], [])


class VersionTests(SimpleTestCase):
    def test_each_font_exists_and_counts_for_the_version(self):
        urls = requested_urls()
        self.assertEqual(len(urls), 2)
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(finders.find(f"garage/{url}"))
                self.assertIn(f"garage/{url}", VERSIONED)

    def test_another_font_means_another_version(self):
        # What it is for: the worker's cache only changes when the version does (sw.js deletes the previous one).
        real = finders.find
        for name in (FIGTREE, OUTFIT):
            with self.subTest(font=name), tempfile.NamedTemporaryFile(suffix=".woff2") as other:
                other.write(b"another font")
                other.flush()
                with mock.patch("garage.assets.finders.find",
                                side_effect=lambda path: other.name if path == f"garage/fonts/{name}" else real(path)):
                    changed = asset_version.__wrapped__()
                self.assertNotEqual(changed, asset_version.__wrapped__())
