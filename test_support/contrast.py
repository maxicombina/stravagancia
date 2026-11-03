"""WCAG 2.x contrast of Garage's theme tokens, read from the stylesheet itself.

Pure Python on purpose. From the repository root it prints the table of pairs:

    python -m test_support.contrast garage/static/garage/garage.css

and garage/tests_theme_tokens.py uses the same code inside the suite. It looks at the tokens,
not at the pages: what a page really paints is audited apart, in a browser.
"""
from collections import namedtuple
import re
import sys

LIGHT, DARK, FORCED = "light", "dark", "forced"
THEMES = (LIGHT, DARK)
DARK_MEDIA = "@media (prefers-color-scheme: dark)"
FORCED_SELECTOR = ':root[data-theme="dark"]'
GROUPING_AT_RULES = ("@media", "@supports", "@layer", "@container")

TEXT, GRAPHIC = 4.5, 3.0  # Minimum ratios: text; borders, icons and arcs.

# (foreground, background, minimum, use), the pairs of the table in spec §3.2 and in the same order.
PAIRS = (
    ("--ink", "--bg", TEXT, "texto de pantalla"),
    ("--ink", "--surface", TEXT, "texto en tarjeta"),
    ("--ink", "--surface-2", TEXT, "cifras, chips neutros"),
    ("--ink", "--primary-soft", TEXT, "mensajes, Sin estrenar"),
    ("--ink", "--due-soft", TEXT, "texto del chip Vencido"),
    ("--ink", "--soon-soft", TEXT, "texto del chip Próximo y Revisar"),
    ("--ink", "--ok-soft", TEXT, "texto del chip Al día"),
    ("--ink", "--nodata-soft", TEXT, "texto del chip Sin datos y Pospuesto"),
    ("--ink-2", "--bg", TEXT, "entradillas, notas"),
    ("--ink-2", "--surface", TEXT, "secundario en tarjeta"),
    ("--ink-2", "--surface-2", TEXT, "etiquetas de cifras"),
    ("--primary", "--bg", TEXT, "atrás, enlaces"),
    ("--primary", "--surface", TEXT, "enlaces en tarjeta; carril encendido del interruptor"),
    ("--primary", "--primary-soft", TEXT, "arco En curso sobre su pista"),
    ("--on-primary", "--primary", TEXT, "botón, pestaña activa, filtro elegido, botón encendido del interruptor"),
    ("--primary", "--surface-2", GRAPHIC, "segmento elegido, barra de reparto"),
    ("--due", "--surface", GRAPHIC, "arco e icono Vencido"),
    ("--due", "--due-soft", GRAPHIC, "arco e icono Vencido, sobre su pista"),
    ("--soon", "--surface", GRAPHIC, "Próximo y Revisar"),
    ("--soon", "--soon-soft", GRAPHIC, "Próximo y Revisar, sobre su pista"),
    ("--ok", "--surface", GRAPHIC, "Al día"),
    ("--ok", "--ok-soft", GRAPHIC, "Al día, sobre su pista"),
    ("--nodata", "--surface", GRAPHIC, "Sin datos y Pospuesto"),
    ("--nodata", "--nodata-soft", GRAPHIC, "Sin datos y Pospuesto, sobre su pista"),
    ("--field", "--surface", GRAPHIC, "borde de campos; carril apagado del interruptor"),
    ("--focus", "--bg", GRAPHIC, "foco"),
    ("--focus", "--surface", GRAPHIC, "foco"),
    ("--focus", "--surface-2", GRAPHIC, "foco"),
    ("--danger-ink", "--bg", TEXT, "error de formulario sobre el fondo"),
    ("--danger-ink", "--surface", TEXT, "error dentro de una tarjeta"),
    ("--due", "--bg", GRAPHIC, "anillos y chips fuera de tarjeta"),
    ("--soon", "--bg", GRAPHIC, "anillos y chips fuera de tarjeta"),
    ("--ok", "--bg", GRAPHIC, "anillos y chips fuera de tarjeta"),
    ("--nodata", "--bg", GRAPHIC, "anillos y chips fuera de tarjeta"),
    ("--ink-2", "--primary-soft", TEXT, "secundario en mensajes y aviso de instalación"),
    ("--knob", "--field", GRAPHIC, "botón apagado del interruptor sobre su carril"),
    ("--due-150", "--surface", GRAPHIC, "arco e icono de 150 a 199 %"),
    ("--due-150", "--bg", GRAPHIC, "arco e icono de 150 a 199 %"),
    ("--due-150", "--due-150-soft", GRAPHIC, "arco e icono de 150 a 199 %, sobre su pista"),
    ("--ink", "--due-150-soft", TEXT, "texto de su chip"),
    ("--due-200", "--surface", GRAPHIC, "arco e icono desde 200 %"),
    ("--due-200", "--bg", GRAPHIC, "arco e icono desde 200 %"),
    ("--due-200", "--due-200-soft", GRAPHIC, "arco e icono desde 200 %, sobre su pista"),
    ("--ink", "--due-200-soft", TEXT, "texto de su chip"),
)

Rule = namedtuple("Rule", "conditions selector body")
Check = namedtuple("Check", "number foreground background minimum use theme ratio passed")

_LITERAL_COLOR = re.compile(
    r"#[0-9a-f]{3,8}\b"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\("
    r"|(?<![-\w])(?:white|black|red|green|blue|yellow|orange|purple|pink|brown|gray|grey|silver|navy)(?![-\w])",
    re.IGNORECASE)
_STATE_VAR_WITHOUT_FALLBACK = re.compile(r"var\(\s*--(?:c|soft)\s*,?\s*\)")
_VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")
_STATE_COLOR = re.compile(r"var\(\s*--(?:c|due|soon|ok|nodata)\b")
_ICON_SELECTOR = re.compile(r"(?:^|\s)\.(?:ic|ring-ic)$")
_HEX_COLOR = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})", re.IGNORECASE)


class TokenError(ValueError):
    """The stylesheet cannot be read as the spec describes. Never treated as a pass."""


def _split_top_level(text, separator):
    pieces, depth, start = [], 0, 0
    for position, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == separator and depth == 0:
            pieces.append(text[start:position])
            start = position + 1
    pieces.append(text[start:])
    return pieces


def _squeeze(text):
    return " ".join(text.split())


def _closing_brace(css, opening):
    depth = 0
    for position in range(opening, len(css)):
        if css[position] == "{":
            depth += 1
        elif css[position] == "}":
            depth -= 1
            if depth == 0:
                return position
    raise TokenError(f"Unbalanced braces after {css[max(0, opening - 40):opening]!r}")


def _walk(css, conditions):
    position = 0
    while (opening := css.find("{", position)) >= 0:
        closing = _closing_brace(css, opening)
        prelude = _squeeze(css[position:opening].rsplit(";", 1)[-1])
        inner = css[opening + 1:closing]
        if prelude.startswith(GROUPING_AT_RULES):
            yield from _walk(inner, conditions + (prelude,))
        else:
            yield Rule(conditions, prelude, inner)
        position = closing + 1


def rules(css):
    """Every rule of the stylesheet, with the at-rules around it, comments left out."""
    return list(_walk(re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL), ()))


def declarations(body):
    """The (property, value) pairs of a rule, in order, repeats included."""
    pairs = []
    for piece in _split_top_level(body, ";"):
        name, colon, value = piece.partition(":")
        if colon:
            pairs.append((name.strip(), _squeeze(value)))
    return pairs


def _block_name(rule):
    if rule.conditions == () and rule.selector == ":root":
        return LIGHT
    if rule.conditions == () and rule.selector == FORCED_SELECTOR:
        return FORCED
    if rule.conditions == (DARK_MEDIA,) and rule.selector.startswith(":root"):
        return DARK
    return None


def token_blocks(css):
    """What each theme block declares: `light`, `dark` and, once it exists, `forced`."""
    blocks = {}
    for rule in rules(css):
        name = _block_name(rule)
        if name:
            blocks.setdefault(name, {}).update(declarations(rule.body))
    for name in THEMES:
        if not blocks.get(name):
            raise TokenError(f"The stylesheet has no {name} block of tokens")
    return blocks


def dark_block_selector(css):
    """The selector of the dark media block, as written."""
    return next((rule.selector for rule in rules(css) if _block_name(rule) == DARK), None)


def theme_tokens(blocks, theme):
    """The tokens a theme ends up with: dark overrides light on `:root` and inherits the rest."""
    return dict(blocks[LIGHT]) if theme == LIGHT else {**blocks[LIGHT], **blocks[DARK]}


def _rgb(color):
    if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
        raise TokenError(f"Not a hexadecimal color: {color!r}")
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return tuple(int(digits[start:start + 2], 16) for start in (0, 2, 4))


def luminance(color):
    """Relative luminance, as WCAG 2.x defines it."""
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in _rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def ratio(one, other):
    """Contrast ratio of two colors, from 1 to 21; which one is the foreground does not matter."""
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def check(css, pairs=PAIRS):
    """Every pair in every theme. A missing token fails its pair; the unrounded ratio decides."""
    blocks = token_blocks(css)
    checks = []
    for number, (foreground, background, minimum, use) in enumerate(pairs, start=1):
        for theme in THEMES:
            tokens = theme_tokens(blocks, theme)
            measured = None
            if foreground in tokens and background in tokens:
                measured = ratio(tokens[foreground], tokens[background])
            checks.append(Check(number, foreground, background, minimum, use, theme, measured,
                                measured is not None and measured >= minimum))
    return checks


def literal_colors(css):
    """The colors written by hand outside the theme blocks, as `selector { property: color }`."""
    found = []
    for rule in rules(css):
        if _block_name(rule):
            continue
        for name, value in declarations(rule.body):
            found.extend(f"{rule.selector} {{ {name}: {match.group()} }}" for match in _LITERAL_COLOR.finditer(value))
    return found


def state_vars_without_fallback(css):
    """Uses of `--c` and `--soft` that would be invalid under an element without a state class."""
    found = []
    for rule in rules(css):
        for name, value in declarations(rule.body):
            found.extend(f"{rule.selector} {{ {name}: {match.group()} }}"
                         for match in _STATE_VAR_WITHOUT_FALLBACK.finditer(value))
    return found


def state_colored_text(css):
    """The selectors that write text in a state's color: that color is for icons and arcs, text stays in --ink or --ink-2."""
    found = []
    for rule in rules(css):
        if any(name == "color" and _STATE_COLOR.search(value) for name, value in declarations(rule.body)):
            found.extend(selector for selector in map(_squeeze, _split_top_level(rule.selector, ","))
                         if not _ICON_SELECTOR.search(selector))
    return found


def undefined_tokens(css):
    """The custom properties used somewhere and declared nowhere, which paint nothing."""
    all_rules = rules(css)
    defined = {name for rule in all_rules for name, _ in declarations(rule.body) if name.startswith("--")}
    used = {token for rule in all_rules for _, value in declarations(rule.body) for token in _VAR_USE.findall(value)}
    return sorted(used - defined)


def declared(css, selector):
    """What the unconditional rules naming exactly `selector`, alone or in a list, declare; the last one wins."""
    found = {}
    for rule in rules(css):
        if rule.conditions == () and selector in map(_squeeze, _split_top_level(rule.selector, ",")):
            found.update(declarations(rule.body))
    return found


def _decimal(value):
    return f"{value:.2f}".replace(".", ",")


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) != 1:
        print("Usage: python -m test_support.contrast garage/static/garage/garage.css", file=sys.stderr)
        return 2
    with open(arguments[0], encoding="utf-8") as sheet:
        css = sheet.read()
    try:
        checks = check(css)
    except TokenError as error:
        print(error, file=sys.stderr)
        return 2
    print(f"{'#':>2}  {'par':<30} {'mín.':>4}  {'claro':>6}  {'oscuro':>6}  uso")
    for number in range(1, len(PAIRS) + 1):
        row = {item.theme: item for item in checks if item.number == number}
        first = row[LIGHT]
        cells = [_decimal(row[theme].ratio) if row[theme].ratio is not None else "falta" for theme in THEMES]
        failed = "" if all(row[theme].passed for theme in THEMES) else "  FALLA"
        pair = f"{first.foreground[2:]} / {first.background[2:]}"
        print(f"{number:>2}  {pair:<30} {_decimal(first.minimum)[:3]:>4}  {cells[0]:>6}  {cells[1]:>6}  {first.use}{failed}")
    failures = sum(not item.passed for item in checks)
    print(f"{len(PAIRS)} pares, {len(checks)} comprobaciones, {failures} fallos")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
