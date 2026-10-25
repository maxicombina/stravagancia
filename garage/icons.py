"""Icons of categories and items (garage-041).

Each key is a symbol of the sprite (templates/garage/_icons.html, ``#i-<key>``).
Keywords are matched as whole words of the name, without accents or case and
allowing a plural («Cadenas», «Pedales», «discs»; never «Recambios» for «cambio» nor
«Chubasquero» for «hub»). The keyword written first wins, because Spanish puts the
head noun first («Llave de cadena» is a tool, «Bolsa de sillín» a bag); at the same
position the longest wins («Horquilla de suspensión», «Manetas de cambio»). Keywords
are unique across keys, so the order below never decides.
Changing this list needs no migration: the database CHECK only fixes the shape
of a key, and Category.clean() validates it against ICON_KEYS.
"""
import re
import unicodedata

ICON_CHOICES = (
    # Transmission (shifter before derailleur: «manetas de cambio» also says «cambio»)
    ("chain", "Cadena", ("cadena", "chain")),
    ("cassette", "Casete", ("casete", "cassette", "pinon")),
    ("chainring", "Platos", ("plato", "chainring")),
    ("crank", "Bielas", ("biela", "crank")),
    ("bottom_bracket", "Pedalier", ("pedalier", "bottom bracket")),
    ("shifter", "Maneta de cambio", ("maneta de cambio", "manetas de cambio", "mando de cambio", "mandos de cambio", "mando",
                                            "shifter", "palanca de cambio")),
    ("derailleur", "Desviador", ("desviador", "cambio", "derailleur")),
    ("cable", "Cables", ("cable", "cable de cambio", "cables de cambio", "funda de cambio", "fundas de cambio",
                         "funda de freno", "fundas de freno", "funda de cable", "fundas de cable")),  # a bare «funda» is any cover
    # Wheels
    ("wheel", "Rueda", ("rueda", "wheel")),
    ("tire", "Cubierta", ("cubierta", "neumatico", "tubular", "tire", "tyre")),
    ("tube", "Cámara", ("camara", "inner tube")),
    ("hub", "Buje", ("buje", "hub")),
    ("rim", "Llanta", ("llanta",)),
    ("spoke", "Radios", ("radio", "spoke", "cabecilla")),
    ("sealant", "Sellante", ("sellante", "tubeless", "latex", "sealant")),
    # Brakes
    ("brake", "Pastillas", ("pastilla", "freno", "brake", "zapata")),
    ("disc", "Disco", ("disco", "disco de freno", "discos de freno", "rotor", "disc")),
    ("caliper", "Pinza", ("pinza", "pinza de freno", "pinzas de freno", "caliper")),
    ("brake_lever", "Maneta de freno", ("maneta de freno", "manetas de freno", "maneta", "brake lever", "leva de freno")),
    # Suspension (before the fork: «horquilla de suspensión» also says «horquilla»)
    ("suspension_fork", "Horquilla de suspensión", ("horquilla de suspension", "suspension")),
    ("shock", "Amortiguador", ("amortiguador", "shock", "suspension trasera")),
    # Steering and contact points
    ("fork", "Horquilla", ("horquilla", "fork")),
    ("headset", "Dirección", ("direccion", "headset")),
    ("stem", "Potencia", ("potencia",)),
    ("handlebar", "Manillar", ("manillar", "handlebar", "acople")),
    ("grips", "Puños o cinta", ("puno", "cinta", "cinta de manillar", "grip", "bar tape")),
    ("seatpost", "Tija", ("tija", "seatpost", "dropper")),
    ("saddle", "Sillín", ("sillin", "saddle")),
    ("pedal", "Pedales", ("pedal",)),
    ("cleat", "Calas", ("cala", "cleat")),
    # Gear
    ("helmet", "Casco", ("casco", "helmet")),
    ("shoe", "Zapatillas", ("zapatilla", "shoe")),
    ("glasses", "Gafas", ("gafa", "glasses")),
    ("gloves", "Guantes", ("guante", "glove")),
    ("light", "Luces", ("luz", "luces", "light", "faro")),
    ("computer", "Ciclocomputador", ("ciclocomputador", "cuentakilometros", "gps", "computer")),
    ("sensor", "Sensor", ("sensor", "pulsometro", "cadencia", "potenciometro", "medidor de potencia", "hrm")),
    ("battery", "Batería", ("bateria", "battery")),
    ("bottle", "Bidón", ("bidon", "portabidon", "botella", "bottle")),
    ("bag", "Bolsa", ("bolsa", "alforja", "mochila", "bag")),
    ("tool", "Herramienta", ("herramienta", "tool", "bomba", "inflador", "llave", "desmontable")),
    # Generic
    ("part", "Pieza", ()),
    ("bike", "Bici", ()),
)
ICON_KEYS = frozenset(key for key, _, _ in ICON_CHOICES)
ICON_LABELS = {key: label for key, label, _ in ICON_CHOICES}
DEFAULT_ITEM_ICON = "part"
DEFAULT_CATEGORY_ICON = "tag"


def _plain(text):
    """'Cámara de Piñón' -> 'camara de pinon': lower case without diacritics."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _pattern(word):
    """Whole word(s), with an optional plural: «disc» matches «discs», not «disco» nor «discreto»."""
    return re.compile(r"(?<![a-z])" + re.escape(word) + r"(?:s|es)?(?![a-z])")


_KEYWORDS = tuple((_plain(word), key, _pattern(_plain(word))) for key, _, words in ICON_CHOICES for word in words)
assert len({word for word, _, _ in _KEYWORDS}) == len(_KEYWORDS), "a keyword must name a single icon"


def match_icon(text):
    """The icon a name suggests, or '' when no keyword appears in it.

    Earliest keyword first (the head noun: «Llave de cadena» -> tool, «Bolsa de sillín» -> bag);
    at the same position, the longest («Horquilla de suspensión» -> suspension_fork).
    """
    plain = _plain(text)
    found = []
    for word, key, pattern in _KEYWORDS:
        hit = pattern.search(plain)
        if hit:
            found.append((hit.start(), -len(word), key))
    return min(found)[2] if found else ""


def item_icon_key(item):
    """The category's icon first; else the item's name, then the category's; else the generic part."""
    category = getattr(item, "category", None)
    chosen = getattr(category, "icon", "")
    if chosen in ICON_KEYS:
        return chosen
    return (match_icon(getattr(item, "name", "")) or match_icon(getattr(category, "name", ""))
            or DEFAULT_ITEM_ICON)


def category_icon_key(category):
    """A category's own icon, else what its name suggests, else the generic tag."""
    chosen = getattr(category, "icon", "")
    return chosen if chosen in ICON_KEYS else match_icon(getattr(category, "name", "")) or DEFAULT_CATEGORY_ICON
