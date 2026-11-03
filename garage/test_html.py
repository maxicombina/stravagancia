"""Read rendered pages in tests by their structure and text, not by the exact markup.

Tolerant, not a validator: a stray end tag is ignored, an end tag also closes whatever is
still open inside it, and the end of the input closes the rest. It does not imply the end
tags HTML lets you omit: `<li>a<li>b` nests the second item in the first. The only CSS it
knows is `.sr-only`, so `.only-ios` and `.only-android` both count as text. Tag and attribute
names come lowercased, as `html.parser` gives them: `viewbox`, not `viewBox`.
"""
from html.parser import HTMLParser

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
NEVER_TEXT_TAGS = {"head", "script", "style", "template"}


class Node:
    """An element: `tag`, `attrs` (unescaped; "" for an attribute without a value) and `children`, nodes and strings."""

    def __init__(self, tag=None, attrs=()):
        self.tag = tag
        self.attrs = {name: value or "" for name, value in attrs}
        self.children = []

    def __repr__(self):
        return f"<{self.tag} {self.attrs}>"


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.open_nodes = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.open_nodes[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.open_nodes.append(node)

    def handle_startendtag(self, tag, attrs):
        self.open_nodes[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.open_nodes) - 1, 0, -1):
            if self.open_nodes[index].tag == tag:
                del self.open_nodes[index:]
                return

    def handle_data(self, data):
        self.open_nodes[-1].children.append(data)


def parse(html):
    """The root node of a page or a fragment."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _descendants(node):
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from _descendants(child)


def find_all(node, tag=None, cls=None, **attrs):
    """The descendants of `node`, in document order, that match everything given.

    `cls` is one or more space-separated classes: all are required, others are allowed.
    An underscore in an attribute name stands for a hyphen (`aria_current="page"`), and
    the value `True` means that the attribute is present, with any value.
    """
    wanted_classes = set(cls.split()) if cls else set()
    wanted_attrs = {name.replace("_", "-"): value for name, value in attrs.items()}

    def matches(candidate):
        return ((tag is None or candidate.tag == tag)
                and wanted_classes <= set(candidate.attrs.get("class", "").split())
                and all(name in candidate.attrs if value is True else candidate.attrs.get(name) == value
                        for name, value in wanted_attrs.items()))

    return [candidate for candidate in _descendants(node) if matches(candidate)]


def row_by_href(html, href):
    """The row (`a.entry`) that links to exactly `href`. Fails unless there is exactly one."""
    rows = find_all(parse(html), "a", cls="entry", href=href)
    assert len(rows) == 1, f"{len(rows)} rows link to {href!r}"
    return rows[0]


def _is_hidden_from_everyone(node):
    return node.tag in NEVER_TEXT_TAGS or "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true"


def _is_screen_reader_only(node):
    return "sr-only" in node.attrs.get("class", "").split()


def _pieces(node, skip):
    if skip(node):
        return
    for child in node.children:
        if isinstance(child, Node):
            yield from _pieces(child, skip)
        else:
            yield child


def _text(node, skip):
    # Adjacent elements stay together, as inline elements do on the screen.
    return " ".join("".join(_pieces(node, skip)).split())


def accessible_text(node):
    """What a screen reader reads as text: leaves out what is `aria-hidden` and keeps what is `sr-only`."""
    return _text(node, _is_hidden_from_everyone)


def visible_text(node):
    """What the eye reads: leaves out what is `aria-hidden` and what is `sr-only`."""
    return _text(node, lambda candidate: _is_hidden_from_everyone(candidate) or _is_screen_reader_only(candidate))
