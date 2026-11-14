"""Names in Spanish alphabetical order (garage-047 F10).

The database sorts them with PostgreSQL's ICU Spanish collation: accents and case do not lead, «ñ» comes after «n»,
and names that differ only in case, accents or punctuation are still told apart («camara < Camara < Cámara»).
Model `Meta.ordering` stays as it is (changing it is a migration); a query that is shown sorted by name uses `by_name`.

What is ordered in Python keeps the database's order: it comes from a query sorted with `by_name` and is only
re-sorted stably by other keys, or by its position in that query (`positions`), without new queries. ICU is not
re-implemented in Python. `name_key` is for the few places with no such query, and it is an approximation.

The collation must exist in the database, or every page that sorts by name fails: `garage.checks` says so.
"""
import unicodedata

from django.db.models.functions import Collate

COLLATION = "es-x-icu"
_AFTER_N = "n\U0010ffff"  # «ñ»: after «n» followed by any letter, before «o»


def collated(field="name"):
    """`field` (a name or an expression) with the Spanish collation, for an order_by() of several keys."""
    return Collate(field, COLLATION)


def by_name(queryset, field="name"):
    """`queryset` sorted by `field` as in Spanish; equal names keep a stable order by the queryset's own id."""
    return queryset.order_by(collated(field), "pk")


def positions(objects):
    """{pk: position} of objects already sorted, to sort something else by them without comparing names."""
    return {obj.pk: index for index, obj in enumerate(objects)}


def name_key(text):
    """A sort key that approximates `by_name` where no sorted query can be reused: case and accents do not count and
    «ñ» goes after «n».

    It agrees with the database on names whose base letters differ, if every letter is a plain one (a to z, «ñ») or
    one that Unicode writes as a plain letter plus accents («á», «ç», «ü»). Where it does not:
    - names that differ only in case, accents or punctuation: ICU still orders them («camara < Camara < Cámara»), this
      gives them the same key, so the caller adds its own tie-break (the id, or the order of a sorted query);
    - punctuation and digits sort by code point, not as ICU sorts them;
    - other letters (ø, ł, æ, œ, ı...) sort by code point, after «z»; ICU puts most of them with a plain letter
      («Æro < Bici», «Øyvind < Peter»).
    """
    folded = unicodedata.normalize("NFC", text).casefold().replace("ñ", _AFTER_N)
    return "".join(char for char in unicodedata.normalize("NFD", folded) if not unicodedata.combining(char))
