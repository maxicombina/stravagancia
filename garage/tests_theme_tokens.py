"""garage-050 F1a: the «Anillos» tokens meet AA, and they are what the stylesheet paints with (spec §3)."""
import contextlib
import io
import json
import os
import re
import tempfile

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase
from django.urls import reverse

from test_support import contrast

from .test_html import find_all, parse


def stylesheet():
    with open(finders.find("garage/garage.css"), encoding="utf-8") as sheet:
        return sheet.read()


MINIMAL = """
/* A brace in a comment } must not end the block. */
:root { --bg: #ffffff; --ink: #000000; --c-free: 1px; color-scheme: light; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #000000; --ink: #ffffff; color-scheme: dark; }
}
"""


class FormulaTests(SimpleTestCase):
    """Known results from the WCAG definition and from the spec's own recalculation."""

    def test_the_two_ends_of_the_scale(self):
        self.assertAlmostEqual(contrast.ratio("#000000", "#ffffff"), 21)
        self.assertAlmostEqual(contrast.ratio("#5536C8", "#5536C8"), 1)

    def test_which_one_is_the_foreground_does_not_matter(self):
        self.assertEqual(contrast.ratio("#1C1A21", "#F5F3EF"), contrast.ratio("#F5F3EF", "#1C1A21"))

    def test_the_short_form_and_the_case_mean_the_same_color(self):
        self.assertEqual(contrast.ratio("#fff", "#000"), contrast.ratio("#FFFFFF", "#000000"))

    def test_figures_recalculated_in_the_spec(self):
        for one, other, expected in (("#1C1A21", "#F5F3EF", 15.54), ("#FFFFFF", "#5536C8", 7.64), ("#D2312F", "#FFFFFF", 4.98),
                                     ("#B42318", "#F5F3EF", 5.93), ("#FF7B72", "#1D1A23", 6.80), ("#fab219", "#ffffff", 1.83)):
            with self.subTest(one=one, other=other):
                self.assertEqual(round(contrast.ratio(one, other), 2), expected)

    def test_what_is_not_a_color_is_an_error_and_not_a_figure(self):
        for value in ("transparent", "var(--x)", "#12", "#12345", "#ggg", "", None):
            with self.subTest(value=value), self.assertRaises(contrast.TokenError):
                contrast.ratio(value, "#ffffff")


class ReadingTests(SimpleTestCase):
    """The tool itself, on stylesheets written to catch it out: a checker that cannot fail proves nothing."""

    def test_it_reads_each_theme_block(self):
        blocks = contrast.token_blocks(MINIMAL)
        self.assertEqual(blocks["light"]["--bg"], "#ffffff")
        self.assertEqual(blocks["dark"]["--bg"], "#000000")
        self.assertNotIn("forced", blocks)

    def test_it_reads_the_forced_block_once_it_exists(self):
        blocks = contrast.token_blocks(MINIMAL + ':root[data-theme="dark"] { --bg: #000000; }')
        self.assertEqual(blocks["forced"], {"--bg": "#000000"})

    def test_a_dark_theme_keeps_what_it_does_not_override(self):
        tokens = contrast.theme_tokens(contrast.token_blocks(MINIMAL), "dark")
        self.assertEqual(tokens["--bg"], "#000000")
        self.assertEqual(tokens["--c-free"], "1px")

    def test_a_stylesheet_without_a_block_is_an_error_and_not_a_pass(self):
        for css in ("", ":root { --bg: #fff; }", '@media (prefers-color-scheme: dark) { :root { --bg: #000; } }',
                    ":root { } @media (prefers-color-scheme: dark) { :root { } }"):
            with self.subTest(css=css), self.assertRaises(contrast.TokenError):
                contrast.check(css)

    def test_unbalanced_braces_are_an_error(self):
        with self.assertRaises(contrast.TokenError):
            contrast.rules(":root { --bg: #fff;")

    def test_a_pair_below_its_minimum_fails_and_every_pair_counts_twice(self):
        pairs = (("--ink", "--bg", 4.5, "ok"), ("--grey", "--bg", 4.5, "low"))
        css = MINIMAL + ":root { --grey: #777777; }"
        results = {(item.foreground, item.theme): item.passed for item in contrast.check(css, pairs)}
        self.assertEqual(len(results), 4)
        self.assertTrue(results["--ink", "light"])
        self.assertFalse(results["--grey", "light"])  # 4,48:1
        self.assertTrue(results["--grey", "dark"])

    def test_a_missing_token_fails_its_pair_instead_of_being_skipped(self):
        results = contrast.check(MINIMAL, (("--nowhere", "--bg", 3, "absent"), ("--ink", "--nowhere", 3, "absent")))
        self.assertEqual(len(results), 4)
        self.assertEqual([item.passed for item in results], [False] * 4)
        self.assertEqual([item.ratio for item in results], [None] * 4)

    def test_a_ratio_is_not_rounded_up_into_passing(self):
        # D16: --due on --bg, 4,49:1 in the light theme, is why error text has its own token.
        css = """:root { --due: #D2312F; --bg: #F5F3EF; }
                 @media (prefers-color-scheme: dark) { :root { --bg: #000000; } }"""
        light = contrast.check(css, (("--due", "--bg", 4.5, "error text"),))[0]
        self.assertEqual(round(light.ratio, 2), 4.49)
        self.assertFalse(light.passed)

    def test_every_literal_form_is_found_outside_the_blocks(self):
        for value in ("#abc", "#ABCDEF", "#abcdef80", "rgb(0, 0, 0)", "rgba(0, 0, 0, .5)", "RGB(0,0,0)", "hsl(0 0% 0%)",
                      "hsla(0, 0%, 0%, 1)", "oklch(50% .1 200)", "white", "Black",
                      "0 1px 2px #000", "linear-gradient(to bottom, transparent, #fff 32%)"):
            with self.subTest(value=value):
                self.assertTrue(contrast.literal_colors(f"{MINIMAL} .x {{ color: {value}; }}"))

    def test_a_literal_inside_an_at_rule_is_found_and_named(self):
        found = contrast.literal_colors(MINIMAL + "@media (min-width: 900px) { .x { background: #123456; } }")
        self.assertEqual(found, [".x { background: #123456 }"])

    def test_tokens_and_keywords_are_not_literals(self):
        css = MINIMAL + """/* #abcdef in a comment */
            .a#fab { white-space: nowrap; color: var(--ink); fill: currentColor; border-color: transparent; }
            .b { background: color-mix(in oklab, var(--ink) 10%, var(--bg)); box-shadow: var(--shadow); }"""
        self.assertEqual(contrast.literal_colors(css), [])

    def test_the_theme_blocks_are_the_only_place_for_literals(self):
        self.assertEqual(contrast.literal_colors(MINIMAL + ':root[data-theme="dark"] { --bg: #000000; }'), [])

    def test_a_state_var_without_fallback_is_found(self):
        for value in ("var(--c)", "var(--soft)", "var( --c )", "var(--c,)", "color-mix(in oklab, var(--c) 20%, var(--bg))"):
            with self.subTest(value=value):
                self.assertTrue(contrast.state_vars_without_fallback(f".x {{ stroke: {value}; }}"))

    def test_a_state_var_with_fallback_and_its_lookalikes_are_fine(self):
        for value in ("var(--c, var(--primary))", "var(--soft, var(--surface-2))", "var(--card-border)", "var(--soft-x)"):
            with self.subTest(value=value):
                self.assertEqual(contrast.state_vars_without_fallback(f".x {{ stroke: {value}; }}"), [])

    def test_text_in_a_state_color_is_found(self):
        for value in ("var(--c)", "var(--c, var(--ink-2))", "var(--due)", "var(--due-150)", "var(--soon)", "var(--ok)", "var(--nodata)"):
            with self.subTest(value=value):
                self.assertEqual(contrast.state_colored_text(f".x {{ color: {value}; }}"), [".x"])

    def test_icons_and_everything_else_may_use_a_state_color(self):
        css = """.chip .ic, .ring-ic { color: var(--c, var(--ink-2)); }
                 .x { background: var(--c, var(--primary)); stroke: var(--due); color: var(--danger-ink); }
                 .y { color: var(--card-border); }"""
        self.assertEqual(contrast.state_colored_text(css), [])

    def test_a_token_used_and_never_declared_is_found(self):
        css = ":root { --a: 1px; } .x { --b: 2px; margin: var(--a) var(--b) var(--ghost) var(--tile, var(--a)); }"
        self.assertEqual(contrast.undefined_tokens(css), ["--ghost", "--tile"])

    def test_declared_finds_a_selector_alone_or_in_a_list_and_nothing_else(self):
        css = """.a, .b:not(.x, .y) { --c: 1; } .a { --soft: 2; } .a.b { --c: 3; }
                 @media print { .a { --c: 4; } }"""
        self.assertEqual(contrast.declared(css, ".a"), {"--c": "1", "--soft": "2"})
        self.assertEqual(contrast.declared(css, ".b:not(.x, .y)"), {"--c": "1"})
        self.assertEqual(contrast.declared(css, ".x"), {})


class CommandTests(SimpleTestCase):
    def run_on(self, css):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sheet.css")
            with open(path, "w", encoding="utf-8") as sheet:
                sheet.write(css)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = contrast.main([path])
        return status, output.getvalue(), errors.getvalue()

    def test_the_real_stylesheet_passes_and_prints_every_pair(self):
        status, output, _ = self.run_on(stylesheet())
        self.assertEqual(status, 0, output)
        self.assertIn("44 pares, 88 comprobaciones, 0 fallos", output)
        self.assertEqual(sum(" / " in line for line in output.splitlines()), 44)

    def test_failures_set_the_exit_status_and_are_marked(self):
        status, output, _ = self.run_on(MINIMAL)
        self.assertEqual(status, 1)
        self.assertIn("FALLA", output)
        self.assertIn("falta", output)

    def test_a_stylesheet_it_cannot_read_is_a_different_status(self):
        status, output, errors = self.run_on("")
        self.assertEqual(status, 2)
        self.assertEqual(output, "")
        self.assertIn("no light block", errors)

    def test_it_asks_for_exactly_one_path(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(contrast.main([]), 2)
            self.assertEqual(contrast.main(["a", "b"]), 2)


class StylesheetTests(SimpleTestCase):
    def setUp(self):
        self.css = stylesheet()

    def rule(self, selector):
        found = contrast.declared(self.css, selector)
        self.assertTrue(found, f"No rule for {selector}")
        return found

    def test_pairs_meet_wcag(self):
        checks = contrast.check(self.css)
        self.assertEqual(len(checks), 88)
        for item in checks:
            with self.subTest(pair=f"{item.number}: {item.foreground} / {item.background}", theme=item.theme):
                self.assertTrue(item.passed, f"{item.ratio} < {item.minimum} ({item.use})")

    def test_no_literal_colors_outside_tokens(self):
        self.assertEqual(contrast.literal_colors(self.css), [])

    def test_state_classes(self):
        # What ties the table of pairs to the pages: with another token here, the 88 checks would say nothing.
        for selector, color, soft in ((".st-due", "--due", "--due-soft"),
                                      (".st-due.over-150", "--due-150", "--due-150-soft"),
                                      (".st-due.over-200", "--due-200", "--due-200-soft"),
                                      (".st-soon", "--soon", "--soon-soft"),
                                      (".st-review", "--soon", "--soon-soft"),
                                      (".st-progress", "--primary", "--primary-soft"),
                                      (".st-current", "--ok", "--ok-soft"),
                                      (".st-ok", "--ok", "--ok-soft"),
                                      (".st-nodata", "--nodata", "--nodata-soft"),
                                      (".st-snoozed", "--nodata", "--nodata-soft")):
            with self.subTest(selector=selector):
                state = self.rule(selector)
                self.assertEqual(state.get("--c"), f"var({color})")
                self.assertEqual(state.get("--soft"), f"var({soft})")

    def test_state_vars_have_fallback(self):
        self.assertEqual(contrast.state_vars_without_fallback(self.css), [])

    def test_every_token_used_is_declared(self):
        # Also what catches an old name left behind (--tile, --ink2, --accent, --bar, --ci, --due-i...).
        self.assertEqual(contrast.undefined_tokens(self.css), [])

    def test_no_text_uses_a_state_color(self):
        self.assertEqual(contrast.state_colored_text(self.css), [])

    def test_the_browser_mixes_no_colors(self):
        # A mixed color is out of the table of pairs and out of reach of the audit in the browser (§3.3).
        self.assertNotIn("color-mix", self.css)

    def test_the_dark_block_leaves_room_for_a_forced_light_theme(self):
        self.assertEqual(contrast.dark_block_selector(self.css), ':root:not([data-theme="light"])')

    def test_dark_blocks_are_identical(self):
        # Spec §3.3: two copies of the dark theme, one for the system's choice and one for the person's.
        blocks = contrast.token_blocks(self.css)
        self.assertEqual(blocks["forced"], blocks["dark"])
        colors = [value for value in blocks["forced"].values() if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value)]
        self.assertGreaterEqual(len(colors), 25)
        self.assertEqual(blocks["forced"]["color-scheme"], "dark")

    def test_a_difference_between_the_dark_blocks_would_show(self):
        # The control of the test above: it reads the two blocks apart.
        forced, _, rest = self.css.partition(contrast.FORCED_SELECTOR)
        changed = forced + contrast.FORCED_SELECTOR + rest.replace("--bg: #131118", "--bg: #131119", 1)
        blocks = contrast.token_blocks(changed)
        self.assertEqual((blocks["dark"]["--bg"], blocks["forced"]["--bg"]), ("#131118", "#131119"))

    def test_the_segmented_choice_paints_with_the_pairs_that_were_checked(self):
        # Spec §4.8 and pairs 3, 15 and 16; the radio is out of sight, so its label carries the focus.
        self.assertEqual(self.rule(".seg").get("background"), "var(--surface-2)")
        self.assertEqual(self.rule(".seg label").get("color"), "var(--ink)")
        self.assertEqual(self.rule(".seg input:checked + label").get("background"), "var(--primary)")
        self.assertEqual(self.rule(".seg input:checked + label").get("color"), "var(--on-primary)")
        self.assertEqual(self.rule(".seg input:checked + label").get("font-weight"), "700")
        self.assertEqual(self.rule(".seg input:focus-visible + label").get("outline"), "3px solid var(--focus)")

    def test_each_radio_of_the_segmented_choice_covers_its_own_label(self):
        # Out of sight, but it is what a screen reader outlines and what the browser brings into view on focusing it.
        # The rule has to outweigh `.page input[type="radio"]`, which comes later and sets 20 px.
        self.assertEqual(self.rule(".seg .tile").get("position"), "relative")
        radio = self.rule('.seg .tile input[type="radio"]')
        self.assertEqual({name: radio.get(name) for name in ("inset", "width", "height", "margin")},
                         {"inset": "0", "width": "100%", "height": "100%", "margin": "0"})

    def test_the_switch_paints_with_the_pairs_that_were_checked(self):
        # Spec §3.2: pairs 13, 15, 25 and 36, the four contrasts of the switch.
        self.assertEqual(self.rule(".sw").get("background"), "var(--field)")
        self.assertEqual(self.rule(".sw::before").get("background"), "var(--knob)")
        self.assertEqual(self.rule(".sw::before").get("box-shadow"), "var(--knob-shadow)")
        self.assertEqual(self.rule(".sw:checked").get("background"), "var(--primary)")
        self.assertEqual(self.rule(".sw:checked::before").get("background"), "var(--on-primary)")

    def test_every_variant_of_the_switch_paints_its_knob_with_the_pair_that_was_checked(self):
        # Pair 36 is --knob on --field. A variant for one system in another color leaves the 3:1 of §3.2 true only on some phones.
        knobs = {rule.selector: dict(contrast.declarations(rule.body))["background"] for rule in contrast.rules(self.css)
                 if not rule.conditions and rule.selector.endswith(".sw::before") and "background" in rule.body}
        self.assertIn(".sw::before", knobs)
        self.assertEqual({selector: knob for selector, knob in knobs.items() if knob != "var(--knob)"}, {})

    def forced_colors_rules(self):
        return [rule for rule in contrast.rules(self.css) if rule.conditions == ("@media (forced-colors: active)",)]

    def test_forced_colors_turn_every_color_token_into_a_system_color_inside_an_svg(self):
        # The browser forces HTML, but neither an SVG's fill and stroke nor an icon's own color. With a theme chosen against the
        # system's palette those kept the theme's color on the wrong canvas: 1,12:1 on a gauge's figure.
        rules = [rule for rule in self.forced_colors_rules() if rule.selector == "svg"]
        self.assertEqual(len(rules), 1, "No rule for the tokens in forced colors")
        forced = dict(contrast.declarations(rules[0].body))
        themed = {name for block in contrast.token_blocks(self.css).values() for name, value in block.items()
                  if re.fullmatch(r"#[0-9a-fA-F]{3,8}|transparent", value)}
        self.assertGreaterEqual(len(themed), 25)
        self.assertEqual((themed | {"--c", "--soft"}) - set(forced), set())
        self.assertLessEqual(set(forced.values()), {"Canvas", "CanvasText"})
        for token in ("--ink", "--ink-2", "--primary", "--c", "--due", "--focus"):
            self.assertEqual(forced[token], "CanvasText", token)
        for token in ("--surface", "--soft"):  # What paints a chart's halo and a ring's track: no paint at all on that canvas.
            self.assertEqual(forced[token], "Canvas", token)

    def test_forced_colors_leave_html_to_the_browser(self):
        # It paints a Canvas plate behind HTML text: on :root, --on-primary in Canvas left a filled button's text invisible on it.
        for rule in self.forced_colors_rules():
            with self.subTest(selector=rule.selector):
                self.assertNotIn(":root", rule.selector)
                self.assertNotIn("html", rule.selector)

    def test_the_chosen_icon_shows_in_forced_colors(self):
        # Its only mark is a box-shadow, which they remove; the radio is out of sight and an icon tile has no tick.
        selector = ".choice.icons input:checked + label"
        found = [rule for rule in self.forced_colors_rules() if rule.selector == selector]
        self.assertEqual(len(found), 1, f"No rule for {selector} in forced colors")
        chosen = dict(contrast.declarations(found[0].body))
        self.assertEqual(chosen.get("border-width"), "3px")
        # The 1,5 px it adds on each side come off the padding: choosing must not rewrap the tile's name.
        self.assertEqual(self.rule(".choice.icons label").get("padding"), "10px 4px")
        self.assertEqual(self.rule(".choice label").get("border"), "1.5px solid var(--line)")
        self.assertEqual(chosen.get("padding"), "8.5px 2.5px")
        # Same weight as the rule that paints it in normal colors: it has to come later.
        order = contrast.rules(self.css)
        normal = max(position for position, rule in enumerate(order) if rule.selector == selector and not rule.conditions)
        self.assertGreater(order.index(found[0]), normal)

    def test_the_action_bar_and_the_buttons_keep_their_shape_in_forced_colors(self):
        # They remove a gradient and a filled background: what scrolls under the bar would show through it, and «Guardar» and
        # «Cancelar» would be bare text.
        forced = {name: rule for rule in self.forced_colors_rules() for name in rule.selector.split(", ")}
        self.assertEqual(dict(contrast.declarations(forced[".actionbar"].body)).get("background"), "Canvas")
        for name in (".btn", ".button", ".fab"):
            with self.subTest(selector=name):
                self.assertEqual(dict(contrast.declarations(forced[name].body)).get("border"), "1px solid")
        # A delete button already has its border, and it stays: `.btn.danger` outweighs `.btn`.
        self.assertEqual(self.rule(".btn.danger").get("border"), "1.5px solid var(--danger-ink)")

    def test_a_long_word_in_a_name_wraps_instead_of_widening_the_page(self):
        # Names admit 150 characters. With 20 or more and no space or hyphen, 19 of 69 routes overflowed at 320 px.
        for selector in (".page h1", ".page h2", ".page h3", ".page h4", ".page p", ".page summary", ".page .help", ".page .field label",
                         ".checks label", ".timeline", ".gauge-title", ".chip-link"):
            with self.subTest(selector=selector):
                self.assertEqual(self.rule(selector).get("overflow-wrap"), "anywhere")
        self.assertEqual(self.rule(".chip-link").get("min-width"), "0")  # A flex item: without it, it stops at its longest word.

    def test_ordinary_words_are_not_broken_where_they_have_little_room(self):
        # `anywhere` also lowers an element's minimum width. On the whole page, it left «desconocid/a» on a 390 px phone in a
        # ride's bike choice and squeezed the figures' captions at 320 px; `break-word` broke that same word.
        self.assertNotIn("overflow-wrap", self.rule(".page"))
        for selector in (".stats", ".stats span", ".choice label"):
            with self.subTest(selector=selector):
                self.assertNotIn("overflow-wrap", self.rule(selector))

    def test_a_link_keeps_its_icon_off_its_text(self):
        # «Posponer aviso» and, from F3b on, «Añadir foto» (spec §4.6): no space between icon and text in their markup.
        self.assertEqual(self.rule(".link .ic").get("margin-right"), "6px")
        self.assertNotIn("display", self.rule(".link"))  # Some links sit in the middle of a sentence and have to wrap with it.

    def test_a_chart_figure_keeps_clear_of_the_line_it_sits_on(self):
        # The last month's label falls on its own dashed stretch when the month in progress drops far below the one before.
        figure = self.rule(".chart .val")
        self.assertEqual(figure.get("paint-order"), "stroke")  # Under the figure, not over it.
        self.assertEqual(figure.get("stroke"), "var(--surface)")  # What a chart sits on: every one of them is in a .panel.
        self.assertEqual(figure.get("stroke-linejoin"), "round")  # A mitered halo pokes out of the corners of the digits.

    def test_the_chart_table_for_screen_readers_does_not_widen_the_page(self):
        # `.page table` is more specific than `.sr-only`: at 100 % from where it sits, it overflows every page with a chart.
        self.assertEqual(self.rule(".page table").get("width"), "100%")
        self.assertEqual(self.rule(".page table.sr-only").get("width"), "1px")
        self.assertNotIn("display", self.rule(".page table.sr-only"))  # As a block it may stop being a table for some screen readers.

    def test_placeholders_paint_with_a_pair_that_was_checked(self):
        # It is the only visible name of the search boxes, and the browser's own gray gives 3,72:1 on a dark field (pairs 9 to 11).
        self.assertEqual(self.rule("::placeholder").get("color"), "var(--ink-2)")
        self.assertEqual(self.rule("::placeholder").get("opacity"), "1")  # Some browsers lower it by default, and the pair would not hold.

    def test_error_text_and_delete_buttons_have_their_own_token(self):
        # D16: --due as text gives 4,49:1 on --bg.
        self.assertEqual(self.rule(".page .errorlist").get("color"), "var(--danger-ink)")
        self.assertEqual(self.rule(".btn.danger").get("color"), "var(--danger-ink)")
        self.assertEqual(self.rule(".link-btn.danger").get("color"), "var(--danger-ink)")

    def test_a_field_with_an_error_says_so_on_every_kind_of_control(self):
        # The rule that gives a text box its border carries three :not(). Without them, the error's color lost to it, and only
        # select and textarea came out red: the same error looked different depending on the field.
        box = '.page input:not([type="checkbox"]):not([type="radio"]):not(.sw)'
        self.assertIn("border", self.rule(box))
        for selector in (box.replace(".page ", ".page .field.has-error "), ".page .field.has-error select", ".page .field.has-error textarea"):
            with self.subTest(selector=selector):
                self.assertEqual(self.rule(selector).get("border-color"), "var(--danger-ink)")

    def test_elevated_things_use_the_shadow_made_for_them(self):
        # --shadow is now a whole shadow list: inside another box-shadow it would be invalid.
        self.assertEqual(self.rule(".fab").get("box-shadow"), "var(--shadow-float)")
        for rule in contrast.rules(self.css):
            for name, value in contrast.declarations(rule.body):
                if "var(--shadow)" in value:
                    with self.subTest(selector=rule.selector):
                        self.assertEqual(value, "var(--shadow)")

    def test_font_stacks_fall_back_on_the_system(self):
        tokens = contrast.token_blocks(self.css)["light"]
        for token, family in (("--font-display", '"Outfit"'), ("--font-body", '"Figtree"')):
            with self.subTest(token=token):
                self.assertTrue(tokens[token].startswith(family))
                self.assertIn("system-ui", tokens[token])
                self.assertTrue(tokens[token].endswith("sans-serif"))
        self.assertEqual(tokens["--num"], "var(--font-display)")

    def test_text_and_titles_use_their_font(self):
        self.assertIn("var(--font-body)", self.rule("body").get("font"))
        self.assertEqual(self.rule("h1").get("font-family"), "var(--font-display)")
        self.assertEqual(self.rule("h3").get("font-family"), "var(--font-display)")

    def test_figures_stay_aligned_now_that_their_font_is_not_monospaced(self):
        figures = [rule for rule in contrast.rules(self.css) if "var(--num)" in rule.body]
        self.assertGreaterEqual(len(figures), 8)
        for rule in figures:
            with self.subTest(selector=rule.selector):
                names = [name for name, _ in contrast.declarations(rule.body)]
                self.assertIn("font-variant-numeric", names)
                self.assertEqual(dict(contrast.declarations(rule.body))["font-variant-numeric"], "tabular-nums")
                if "font" in names:  # The shorthand resets it: it has to come after.
                    self.assertGreater(names.index("font-variant-numeric"), names.index("font"))

    def test_figures_are_not_tightened_now_that_their_font_is_not_monospaced(self):
        # Outfit's digits are close together as they are: pulled closer, «00», «40» and «44» join into a single stroke, in the
        # most visible figures of Garaje, Taller, Bici and Pieza. Neither the mockup nor the spec tightens them.
        figures = [rule for rule in contrast.rules(self.css) if "var(--num)" in rule.body or rule.selector == ".stats.four b"]
        self.assertGreaterEqual(len(figures), 9)
        for rule in figures:
            with self.subTest(selector=rule.selector):
                self.assertFalse(dict(contrast.declarations(rule.body)).get("letter-spacing", "0").startswith("-"))

    def test_titles_are_spaced_as_in_the_mockup(self):
        # What the old font needed: in Outfit some letters touch, as in «Lectura de Pastillas traseras» and «Cobertura observada».
        self.assertEqual(self.rule(".page h1").get("letter-spacing"), "-.01em")
        self.assertNotIn("letter-spacing", self.rule(".page h2"))

    def test_the_smallest_figures_get_a_little_air(self):
        # Measured at scale 3: at 17 px «00» touches even with no spacing, and with .01em it no longer does.
        for selector in (".trio b", ".stats.four b"):
            with self.subTest(selector=selector):
                self.assertEqual(self.rule(selector).get("letter-spacing"), ".01em")

    def test_shape_tokens_for_the_next_phases_exist(self):
        tokens = contrast.token_blocks(self.css)["light"]
        for token, value in (("--r-sm", "10px"), ("--r-md", "16px"), ("--r-lg", "22px"), ("--r-xl", "28px"), ("--r-pill", "999px"),
                             ("--s1", "4px"), ("--s2", "8px"), ("--s3", "12px"), ("--s4", "16px"), ("--s5", "20px"), ("--s6", "24px"),
                             ("--s7", "32px"), ("--s8", "40px"), ("--nav-h", "72px"), ("--nav-gap", "10px"),
                             ("--nav-space", "calc(var(--nav-h) + var(--nav-gap) + env(safe-area-inset-bottom, 0px))")):
            with self.subTest(token=token):
                self.assertEqual(tokens.get(token), value)


class ThemeColorTests(SimpleTestCase):
    """The browser's and the installed app's chrome match the screen they surround."""

    def setUp(self):
        blocks = contrast.token_blocks(stylesheet())
        self.light_bg = contrast.theme_tokens(blocks, "light")["--bg"].lower()
        self.dark_bg = contrast.theme_tokens(blocks, "dark")["--bg"].lower()

    def theme_color(self, html, media):
        metas = find_all(parse(html), "meta", name="theme-color", media=media)
        self.assertEqual(len(metas), 1)
        return metas[0].attrs["content"].lower()

    def test_theme_color_matches_bg(self):
        html = self.client.get(reverse("garage:offline")).content.decode()
        self.assertEqual(self.theme_color(html, "(prefers-color-scheme: light)"), self.light_bg)
        self.assertEqual(self.theme_color(html, "(prefers-color-scheme: dark)"), self.dark_bg)
        manifest = json.loads(self.client.get(reverse("garage:manifest")).content)
        self.assertEqual(manifest["background_color"].lower(), self.light_bg)
        self.assertEqual(manifest["theme_color"].lower(), self.light_bg)

    def test_a_forced_theme_changes_the_bar_to_the_same_colors_from_the_script(self):
        # garage.js writes these metas without reloading (spec §4.8).
        with open(finders.find("garage/garage.js"), encoding="utf-8") as script:
            source = script.read().lower()
        self.assertIn(f"light: '{self.light_bg}'", source)
        self.assertIn(f"dark: '{self.dark_bg}'", source)

    def test_the_old_palette_is_gone_from_what_the_browser_reads(self):
        html = self.client.get(reverse("garage:offline")).content.decode().lower()
        manifest = self.client.get(reverse("garage:manifest")).content.decode().lower()
        for old in ("#f1f2f5", "#0a0c11"):
            with self.subTest(old=old):
                self.assertNotIn(old, html)
                self.assertNotIn(old, manifest)
