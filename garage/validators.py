"""ISO 4217 alphabetic currency codes from the SIX current list.

Source: https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml
Published 2026-09-17; retrieved 2026-10-04. Kept locally for deterministic validation.
"""
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation, localcontext


CURRENCY_CODES = frozenset(
    'AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BOV '
    'BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP '
    'CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF '
    'GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR '
    'KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT '
    'MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN '
    'PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE '
    'SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX '
    'USD USN UYI UYU UYW UZS VED VES VND VUV WST XAD XAF XAG XAU XBA XBB XBC '
    'XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG '
    .split()
)


def validate_currency(value):
    if value not in CURRENCY_CODES:
        raise ValidationError("Enter an uppercase ISO 4217 currency code.", code="invalid_currency")


MAX_USAGE_VALUE = Decimal("99999999999999999.999")


def exact_usage_value(value, *, metric=None):
    """Normalize exact millimetres/milliseconds; never round or accept floats."""
    if isinstance(value, (float, bool)) or value is None:
        raise ValidationError("Use an explicit decimal value.", code="invalid_value")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Enter a decimal value.", code="invalid_value") from None
    if not number.is_finite() or number < 0 or number > MAX_USAGE_VALUE:
        raise ValidationError("Enter a finite nonnegative value within the supported range.", code="invalid_value")
    with localcontext() as context:
        context.prec = 28
        normalized = number.quantize(Decimal("0.001"))
    if normalized != number:
        raise ValidationError("The value must be exactly representable with three decimal places.", code="invalid_precision")
    if metric == "ride_count" and number != number.to_integral_value():
        raise ValidationError("The number of rides must be an integer.", code="invalid_ride_count")
    return normalized
