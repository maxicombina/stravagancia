"""garage-050 F0: what no restyle may break, and the helpers that read the rendered pages."""
import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from test_support import contrast

from .models import Bike, Category, Item
from .services.ownership import create_inventory
from .test_html import accessible_text, find_all, parse, row_by_href, visible_text

PAGES = ("index", "bike-list", "item-list", "maintenance", "statistics", "export", "more", "add",
         "usage-ride-list", "history", "usage-profile-list", "category-list")
OTHER_ORIGIN = re.compile(r"(?:https?:)?//[^\s'\")]*", re.IGNORECASE)  # the protocol-relative form too
CHIP = '<p>Vencido <span aria-hidden="true">≥</span><span class="sr-only">al menos</span> 95 %</p>'
# D11, one skin for iOS and Android: all a system may still decide is whether something is there and the room it leaves.
FOR_ONE_SYSTEM = {"display", "height", "min-height", "padding-bottom"}


def stylesheet():
    with open(finders.find("garage/garage.css"), encoding="utf-8") as sheet:
        return sheet.read()


def rules_for_one_system(css):
    return [rule for rule in contrast.rules(css) if "data-os" in rule.selector + rule.body]  # In the body: nested in another rule.


def skin_by_system(css):
    """What the rules for one system declare beyond FOR_ONE_SYSTEM, as `selector { property }`."""
    return [f"{rule.selector} {{ {name} }}" for rule in rules_for_one_system(css)
            for name, _ in contrast.declarations(rule.body) if name.lower() not in FOR_ONE_SYSTEM]


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

    def test_a_search_box_shows_its_whole_name_on_the_narrowest_phone(self):
        # The placeholder is the only visible name of the field, and one that does not fit is cut with no ellipsis.
        # At 320 px the field leaves 169 px, and this font takes up to 8,4 px a character: 199 px for 25, 151 for 18, 136 for 17.
        for name in ("usage-ride-list", "bike-list", "item-list"):
            with self.subTest(name=name):
                boxes = find_all(self.page(name), "input", id="q")
                self.assertEqual(len(boxes), 1)
                self.assertLessEqual(len(boxes[0].attrs["placeholder"]), 20, boxes[0].attrs["placeholder"])

    def test_the_css_names_no_other_origin(self):
        self.assertEqual(OTHER_ORIGIN.findall(stylesheet()), [])

    def test_each_system_keeps_what_works_differently_on_it(self):
        # D11: the add button, the way back and the install steps. Both versions go in the page and the stylesheet hides one.
        def uses(root, tag, cls):
            return [use.attrs["href"] for node in find_all(root, tag, cls=cls) for use in find_all(node, "use")]

        home, menu, more = self.page("index"), self.page("add"), self.page("more")
        self.assertEqual(uses(home, "a", "icon-btn only-ios"), ["#i-plus"])
        self.assertEqual(uses(home, "a", "fab only-android"), ["#i-plus"])
        self.assertEqual(uses(menu, "svg", "ic only-ios"), ["#i-chev-left"])
        self.assertEqual(uses(menu, "svg", "ic only-android"), ["#i-arrow-left"])
        self.assertIn("Compartir", visible_text(find_all(more, "p", cls="only-ios")[0]))
        self.assertIn("Instalar app", visible_text(find_all(more, "p", cls="only-android")[0]))
        css = stylesheet()
        for selector, display in ((".only-android", "none !important"), ('html[data-os="android"] .only-ios', "none !important"),
                                  ('html[data-os="android"] .only-android:not([hidden])', "revert !important")):
            with self.subTest(selector=selector):
                self.assertEqual(contrast.declared(css, selector).get("display"), display)

    def test_the_service_worker_leaves_photos_to_the_network(self):
        body = self.client.get(reverse("garage:service-worker")).content.decode()
        self.assertIn("url.pathname.startsWith('/garage/photos/')", body)


class OneSkinTests(SimpleTestCase):
    maxDiff = None  # On failing, the guard's whole list is what says what to look at.

    def test_no_system_has_a_look_of_its_own(self):
        # D11, measured by what it asks and not by a list of selectors: such a list would only copy the stylesheet.
        css = stylesheet()
        self.assertTrue(rules_for_one_system(css), "a stylesheet with no such rules proves nothing")
        self.assertEqual(skin_by_system(css), [])

    def test_the_way_back_looks_the_same_on_both(self):
        # Spec §5, `_back.html`: in --primary and with an icon of 24 px, the chevron on iOS and the arrow on Android.
        css = stylesheet()
        self.assertEqual(contrast.declared(css, ".back").get("color"), "var(--primary)")
        back_icon = contrast.declared(css, ".back .ic")
        self.assertEqual((back_icon.get("width"), back_icon.get("height")), ("24px", "24px"))


class SkinBySystemTests(SimpleTestCase):
    """The guard above, on stylesheets written to catch it out: a checker that cannot fail proves nothing."""

    def test_anything_else_a_rule_for_one_system_declares_is_found(self):
        for declaration in ("color: var(--ink)", "border-radius: 24px", "font-size: 12px", "background: var(--primary-soft)",
                            "--tabbar: 70px", "transform: none", "padding: 0", "padding-top: 8px", "max-height: 6px", "BORDER-TOP: 0"):
            with self.subTest(declaration=declaration):
                self.assertEqual(len(skin_by_system(f'html[data-os="android"] .x {{ {declaration}; }}')), 1)

    def test_only_what_is_there_and_the_room_it_leaves_is_allowed(self):
        css = """html[data-os="android"] .a { display: revert !important; }
                 html:not([data-os="android"]) .b { height: 6px; min-height: 0; padding-bottom: 96px; }"""
        self.assertEqual(skin_by_system(css), [])

    def test_every_way_of_writing_the_attribute_counts(self):
        for selector in ('html[data-os="ios"] .x', "html[data-os='ios'] .x", "html[data-os=ios] .x", ':root[data-os="android"]',
                         'html:not([data-os="android"]) .x'):
            with self.subTest(selector=selector):
                self.assertEqual(skin_by_system(f"{selector} {{ color: var(--ink); }}"), [f"{selector} {{ color }}"])

    def test_one_system_in_a_list_is_enough(self):
        self.assertEqual(len(skin_by_system('.a, html[data-os="android"] .b { color: var(--ink); }')), 1)

    def test_a_rule_inside_an_at_rule_is_found(self):
        css = """@media (min-width: 900px) { html[data-os="android"] .a { color: var(--ink); } }
                 @supports (display: grid) { @media print { html[data-os="ios"] .b { margin: 0; } } }"""
        self.assertEqual(skin_by_system(css), ['html[data-os="android"] .a { color }', 'html[data-os="ios"] .b { margin }'])

    def test_a_rule_nested_in_another_is_found(self):
        self.assertEqual(len(skin_by_system('.a { html[data-os="android"] & { color: var(--ink); } }')), 1)

    def test_every_declaration_is_listed_not_just_the_first(self):
        self.assertEqual(skin_by_system('html[data-os="android"] .a { color: red; display: none; margin: 0 }'),
                         ['html[data-os="android"] .a { color }', 'html[data-os="android"] .a { margin }'])

    def test_comments_and_rules_for_everyone_are_left_out(self):
        css = """/* html[data-os="android"] .a { color: red; } */
                 .a { color: var(--ink); /* data-os */ }"""
        self.assertEqual(rules_for_one_system(css), [])

    def test_an_empty_stylesheet_has_nothing_to_list(self):
        self.assertEqual(skin_by_system(""), [])


class TightRoomTests(SimpleTestCase):
    def test_a_figure_of_a_tile_can_go_on_to_a_second_line(self):
        # On a tile with a background, the next tile paints over what sticks out: «máx 1.234», of 3 figures at 320 px, lost its last digit.
        self.assertNotEqual(contrast.declared(stylesheet(), ".stats b").get("white-space"), "nowrap")

    def test_a_long_word_in_a_name_on_the_ride_review_wraps(self):
        # «SantaCruzHightowerCC2026» widened the page by 67 px at 390 px, as a bike and as a piece of gear.
        css = stylesheet()
        self.assertEqual(contrast.declared(css, ".switches label > span").get("overflow-wrap"), "anywhere")
        tile = contrast.declared(css, ".choice:not(.icons) label > span")
        # Not `anywhere`: it would lower the minimum width that keeps an ordinary word whole, «desconocid/a» or «Stumpjumpe/r» on a phone.
        self.assertEqual((tile.get("overflow-wrap"), tile.get("width")), ("break-word", "min-content"))
        self.assertNotIn("overflow-wrap", contrast.declared(css, ".choice label"))



class FieldRowTests(SimpleTestCase):
    def test_the_two_boxes_stay_level_whatever_the_columns_hold(self):
        # With `align-items: end` a rejected «Tiempo» dropped the box of «Unidad» 54,6 px at 320 px. And a label on two lines must not stretch the one beside it.
        css = stylesheet()
        self.assertNotIn("align-items", contrast.declared(css, ".field-row"))
        field = contrast.declared(css, ".field-row .field")
        self.assertEqual(field.get("grid-template-rows"), "subgrid")
        self.assertEqual(field.get("row-gap"), "0", "a row left empty, with no help and no error, would leave its gap under the box")
        self.assertEqual(contrast.declared(css, ".field-row .field > label").get("align-self"), "end")

    def test_every_part_a_field_can_hold_has_a_row_of_its_own(self):
        # A subgrid adds no rows: with fewer, a help and an error would land on each other.
        self.assertEqual(contrast.declared(stylesheet(), ".field-row .field").get("grid-row"), "span 4")  # label, control, help and errors: garage/_field.html

    def test_the_next_field_keeps_the_room_of_a_loose_field(self):
        # The next label stood 4 px under the box above and 6 px over its own: it seemed to name the wrong box.
        css = stylesheet()
        self.assertEqual(contrast.declared(css, ".field-row + :is(.field, .field-row)").get("margin-top"), contrast.declared(css, ".page .field")["margin"].split()[2])


class TrioTests(SimpleTestCase):
    def test_the_columns_of_a_rule_keep_their_rows_level(self):
        # Beside a longer caption, the short column shared out what it had left: at 320 px its bar fell 9 px below the other's. The caption takes it now.
        self.assertEqual(contrast.declared(stylesheet(), ".trio > div").get("grid-template-rows"), "auto auto 1fr")


class ChartTests(SimpleTestCase):
    def test_a_long_mark_of_the_axis_keeps_its_first_digit(self):
        # The marks end at x=28, and at 10,5 px «15.000» measures 35: the svg cut what passed x=0, and the axis read 5.000, 0.000, 5.000 and 0.
        self.assertEqual(contrast.declared(stylesheet(), ".chart svg").get("overflow"), "visible")

    def test_the_arrow_keys_bring_the_bubble_into_view(self):
        # At 844x390, with the chart of a bike just focused, 7 of 12 bubbles stood above the top of the screen, 2 of them entirely. Only the keys: not a scroll under a finger.
        with open(finders.find("garage/garage.js"), encoding="utf-8") as script:
            source = script.read()
        keys = source[source.index("svg.addEventListener('keydown'"):]
        self.assertEqual(keys[:keys.index("});")].count("step("), 2)
        self.assertIn("const step = index => { pick(index); tip.scrollIntoView({ block: 'nearest' }); };", source)

    def test_the_bubble_goes_over_the_bars_only_where_the_chart_does_not_fit_between_them(self):
        # At 844x390 the chart measures 369 px and the bars leave 140: of «junio 2026: 417 km» only the lower edge showed under the top bar.
        css = stylesheet()
        low = [rule for rule in contrast.rules(css) if rule.selector == ".tip" and any("max-height" in condition for condition in rule.conditions)]
        self.assertEqual(len(low), 1)
        bubble = int(dict(contrast.declarations(low[0].body))["z-index"])
        for bar in (".appbar", ".actionbar", ".fab", ".tabbar"):
            with self.subTest(bar=bar):
                self.assertGreater(bubble, int(contrast.declared(css, bar)["z-index"]))
        # On a taller view there is no need, and a bubble left open by a tap sat on the tab bar, over «Taller», while scrolling.
        self.assertNotIn("z-index", contrast.declared(css, ".tip"))


class FocusClearOfTheBarTests(SimpleTestCase):
    def test_the_room_for_the_tab_bar_goes_only_where_the_bar_goes(self):
        # Spec §4.5: 16 px from 1000 px, with the sidebar of F4a. With the bar still floating there, Tab left 89 of 379 elements under it at 1280x800.
        wide = [rule for rule in contrast.rules(stylesheet()) if any("min-width" in condition for condition in rule.conditions)]
        lowered = {rule.conditions for rule in wide if "scroll-padding-bottom" in dict(contrast.declarations(rule.body))}
        moved = {rule.conditions for rule in wide if rule.selector == ".tabbar" and "top" in dict(contrast.declarations(rule.body))}
        self.assertEqual(lowered - moved, set())

    def test_on_a_very_low_view_the_action_bar_stays_in_the_flow(self):
        # 1280x800 at 400 % is 320x200: the three bars took 223 px, and Tab left all it reached in a form out of sight.
        low = [rule for rule in contrast.rules(stylesheet()) if any("max-height" in condition for condition in rule.conditions)]
        self.assertEqual([dict(contrast.declarations(rule.body)).get("position") for rule in low if rule.selector == ".actionbar"], ["static"])
        # And what scrolls into view no longer leaves it room: 64 px above and 186 below are more than the 200 there are.
        self.assertEqual({rule.selector for rule in low if "scroll-padding-bottom" in dict(contrast.declarations(rule.body))}, {"html, html:has(.actionbar, .fab)"})


class OtherOriginPatternTests(SimpleTestCase):
    def test_it_catches_every_way_of_naming_another_origin(self):
        for css in ("a{background:url(https://x.test/a.png)}", "@import 'http://x.test/a.css';",
                    "@font-face{src:url(//x.test/f.woff2)}", 'a{background:url("HTTPS://x.test/a.png")}'):
            with self.subTest(css=css):
                self.assertTrue(OTHER_ORIGIN.search(css))

    def test_a_path_on_this_origin_is_fine(self):
        self.assertIsNone(OTHER_ORIGIN.search("@font-face{src:url(/static/garage/fonts/f.woff2)}"))
