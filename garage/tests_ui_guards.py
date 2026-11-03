"""garage-050 F0: what no restyle may break, and the helpers that read the rendered pages."""
import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Bike, Category, Item
from .services.ownership import create_inventory
from .test_html import accessible_text, find_all, parse, row_by_href, visible_text

PAGES = ("index", "bike-list", "item-list", "maintenance", "statistics", "export", "more", "add",
         "usage-ride-list", "history", "usage-profile-list", "category-list")
OTHER_ORIGIN = re.compile(r"(?:https?:)?//[^\s'\")]*", re.IGNORECASE)  # the protocol-relative form too
CHIP = '<p>Vencido <span aria-hidden="true">≥</span><span class="sr-only">al menos</span> 95 %</p>'


class TextHelperTests(SimpleTestCase):
    def test_accessible_text_hears_sr_only_and_not_aria_hidden(self):
        heard = accessible_text(parse(CHIP))
        self.assertIn("al menos", heard)
        self.assertNotIn("≥", heard)

    def test_visible_text_shows_neither(self):
        shown = visible_text(parse(CHIP))
        self.assertNotIn("al menos", shown)
        self.assertNotIn("≥", shown)

    def test_everything_else_stays_in_order_in_both(self):
        self.assertEqual(accessible_text(parse(CHIP)), "Vencido al menos 95 %")
        self.assertEqual(visible_text(parse(CHIP)), "Vencido 95 %")

    def test_empty_input_has_no_text_and_no_elements(self):
        for html in ("", "   \n "):
            with self.subTest(html=html):
                self.assertEqual(visible_text(parse(html)), "")
                self.assertEqual(accessible_text(parse(html)), "")
                self.assertEqual(find_all(parse(html)), [])

    def test_text_is_unescaped_with_its_whitespace_collapsed(self):
        self.assertEqual(visible_text(parse("<p>  En\n    &lt;Gravel&gt; &amp;\t más </p>")), "En <Gravel> & más")

    def test_adjacent_elements_are_not_separated(self):
        # Like inline elements on the screen: only the template's own whitespace separates them.
        self.assertEqual(visible_text(parse("<b>a</b><i>b</i> <i>c</i>")), "ab c")

    def test_sr_only_inside_aria_hidden_is_silent(self):
        self.assertEqual(accessible_text(parse('<span aria-hidden="true"><span class="sr-only">x</span></span>')), "")

    def test_the_node_itself_can_be_the_hidden_one(self):
        hidden = find_all(parse('<svg class="ring" aria-hidden="true"><text>95 %</text></svg>'), "svg")[0]
        self.assertEqual(visible_text(hidden), "")
        self.assertEqual(accessible_text(hidden), "")
        hidden = find_all(parse('<span class="sr-only">x</span>'), "span")[0]
        self.assertEqual(visible_text(hidden), "")
        self.assertEqual(accessible_text(hidden), "x")

    def test_aria_hidden_false_hides_nothing(self):
        root = parse('<span aria-hidden="false">x</span>')
        self.assertEqual(visible_text(root), "x")
        self.assertEqual(accessible_text(root), "x")

    def test_the_hidden_attribute_hides_from_everyone(self):
        root = parse("<p>a<aside hidden>b</aside></p>")
        self.assertEqual(visible_text(root), "a")
        self.assertEqual(accessible_text(root), "a")

    def test_code_comments_and_the_head_are_not_text(self):
        root = parse("<!doctype html><html><head><title>T</title><style>a{}</style></head>"
                     "<body><!-- nota --><script>x()</script>Hola</body></html>")
        self.assertEqual(visible_text(root), "Hola")
        self.assertEqual(accessible_text(root), "Hola")


class FindAllTests(SimpleTestCase):
    def test_a_class_is_a_whole_word_not_a_substring(self):
        self.assertEqual(find_all(parse('<span class="entry-name">x</span>'), cls="entry"), [])

    def test_several_classes_are_all_required_in_any_order_and_others_are_allowed(self):
        root = parse('<a class="st-due compact entry" id="full"></a><a class="entry" id="plain"></a>')
        self.assertEqual([node.attrs["id"] for node in find_all(root, cls="entry compact")], ["full"])

    def test_tag_and_attributes_narrow_the_search(self):
        root = parse('<a class="x" href="/a/" aria-current="page"></a><a class="x" href="/b/"></a><span class="x"></span>')
        self.assertEqual(len(find_all(root, cls="x")), 3)
        self.assertEqual(len(find_all(root, "a", cls="x")), 2)
        self.assertEqual([node.attrs["href"] for node in find_all(root, "a", href="/b/")], ["/b/"])

    def test_an_underscore_in_an_attribute_name_stands_for_a_hyphen(self):
        root = parse('<a aria-current="page" href="/a/"></a><a href="/b/"></a>')
        self.assertEqual([node.attrs["href"] for node in find_all(root, aria_current="page")], ["/a/"])
        self.assertEqual(find_all(root, aria_current="step"), [])

    def test_true_means_present_with_any_value(self):
        root = parse('<svg id="a" aria-hidden="true"></svg><svg id="b"></svg><input id="c" disabled>')
        self.assertEqual([node.attrs["id"] for node in find_all(root, "svg", aria_hidden=True)], ["a"])
        self.assertEqual([node.attrs["id"] for node in find_all(root, disabled=True)], ["c"])

    def test_descendants_in_document_order_without_the_node_itself(self):
        root = parse('<div id="outer"><div id="first"><div id="nested"></div></div><div id="last"></div></div>')
        outer = find_all(root, "div")[0]
        self.assertEqual(outer.attrs["id"], "outer")
        self.assertEqual([node.attrs["id"] for node in find_all(outer, "div")], ["first", "nested", "last"])

    def test_void_and_self_closed_elements_hold_nothing(self):
        root = parse('<p><input name="a"><br><svg><use href="#i"/></svg><span>x</span></p>')
        for tag in ("input", "br", "use"):
            with self.subTest(tag=tag):
                self.assertEqual(find_all(find_all(root, tag)[0], "span"), [])
        self.assertEqual(visible_text(find_all(root, "p")[0]), "x")

    def test_unbalanced_markup_keeps_its_text(self):
        root = parse("<div><span>a</div></b>b<p>c")
        self.assertEqual(visible_text(find_all(root, "div")[0]), "a")  # </div> closes the open <span> too
        self.assertEqual(visible_text(root), "abc")


class RowByHrefTests(SimpleTestCase):
    ROWS = ('<ul><li><a class="entry compact" href="/garage/items/1/"><span class="entry-name">Cadena</span></a></li>'
            '<li><a class="entry" href="/garage/items/1/edit/"><span class="entry-name">Editar</span></a></li>'
            '<li><a class="entry" href="/x/?a=1&amp;b=2"><span class="entry-name">Con query</span></a></li></ul>'
            '<a href="/garage/items/2/">Enlace suelto</a>')

    def test_the_row_with_exactly_that_link(self):
        self.assertEqual(visible_text(row_by_href(self.ROWS, "/garage/items/1/")), "Cadena")

    def test_the_link_is_compared_unescaped(self):
        self.assertEqual(visible_text(row_by_href(self.ROWS, "/x/?a=1&b=2")), "Con query")

    def test_no_row_fails_saying_which(self):
        for href in ("/garage/items/9/", "/garage/items/2/", ""):  # nothing there; a link that is not a row; empty
            with self.subTest(href=href), self.assertRaisesRegex(AssertionError, "0 rows"):
                row_by_href(self.ROWS, href)

    def test_two_rows_with_the_same_link_never_pick_one_silently(self):
        html = '<a class="entry" href="/a/">x</a><a class="entry" href="/a/">y</a>'
        with self.assertRaisesRegex(AssertionError, "2 rows"):
            row_by_href(html, "/a/")


class PageGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("guard-user", password="test-only-password")
        category = create_inventory(cls.user, Category, name="Cadenas")
        create_inventory(cls.user, Bike, name="Carretera")
        create_inventory(cls.user, Item, name="Cadena 11v", category=category)

    def setUp(self):
        self.client.force_login(self.user)

    def page(self, name):
        response = self.client.get(reverse("garage:" + name))
        self.assertEqual(response.status_code, 200)
        return parse(response.content.decode())

    def test_every_page_has_one_navigation_with_five_tabs(self):
        for name in PAGES:
            with self.subTest(name=name):
                navigations = find_all(self.page(name), "nav", cls="tabbar")
                self.assertEqual(len(navigations), 1)
                self.assertEqual(len(find_all(navigations[0], "a", cls="tab")), 5)

    def test_stylesheets_and_preconnects_stay_on_this_origin(self):
        def links_with(root, rel):
            return [link for link in find_all(root, "link") if rel in link.attrs.get("rel", "").lower().split()]

        for name in PAGES:
            with self.subTest(name=name):
                root = self.page(name)
                self.assertTrue(links_with(root, "stylesheet"), "a page without stylesheets proves nothing")
                hrefs = [link.attrs.get("href", "") for rel in ("stylesheet", "preconnect") for link in links_with(root, rel)]
                self.assertEqual([href for href in hrefs if urlsplit(href).scheme or urlsplit(href).netloc], [])

    def test_the_css_names_no_other_origin(self):
        with open(finders.find("garage/garage.css"), encoding="utf-8") as sheet:
            css = sheet.read()
        self.assertEqual(OTHER_ORIGIN.findall(css), [])

    def test_the_service_worker_leaves_photos_to_the_network(self):
        body = self.client.get(reverse("garage:service-worker")).content.decode()
        self.assertIn("url.pathname.startsWith('/garage/photos/')", body)


class OtherOriginPatternTests(SimpleTestCase):
    def test_it_catches_every_way_of_naming_another_origin(self):
        for css in ("a{background:url(https://x.test/a.png)}", "@import 'http://x.test/a.css';",
                    "@font-face{src:url(//x.test/f.woff2)}", 'a{background:url("HTTPS://x.test/a.png")}'):
            with self.subTest(css=css):
                self.assertTrue(OTHER_ORIGIN.search(css))

    def test_a_path_on_this_origin_is_fine(self):
        self.assertIsNone(OTHER_ORIGIN.search("@font-face{src:url(/static/garage/fonts/f.woff2)}"))
