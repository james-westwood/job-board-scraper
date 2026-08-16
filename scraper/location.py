"""Work out whether a posting is in the UK.

The hard part is that a lot of UK city names are also US city names --
Birmingham, Manchester, Cambridge, Bristol, Boston, Durham, Worcester. So an
explicit country or state signal is always checked *first*, and a bare city name
only counts as UK when nothing contradicts it.

Anything genuinely ambiguous comes back "unknown" and is kept, not dropped:
better a job James has to glance at than one silently binned.
"""

from __future__ import annotations

import re

UK = "uk"
NON_UK = "non_uk"
UNKNOWN = "unknown"

# Checked before anything else -- "Northern Ireland" is UK, plain "Ireland" is not.
_UK_STRONG = re.compile(
    r"\bunited kingdom\b|\bu\.?k\.?\b|\bgreat britain\b|\bengland\b|\bscotland\b|"
    r"\bwales\b|\bnorthern ireland\b|\bbritain\b|\bgb\b",
    re.I,
)

_NON_UK_COUNTRIES = re.compile(
    r"\bunited states\b|\bu\.?s\.?a\.?\b|\bus\b|\bcanada\b|\bbrazil\b|\bbrasil\b|"
    r"\bmexico\b|\bargentina\b|\bchile\b|\bcolombia\b|\bmalaysia\b|\bsingapore\b|"
    r"\bphilippines\b|\bindia\b|\bchina\b|\bjapan\b|\bkorea\b|\bvietnam\b|"
    r"\bthailand\b|\bindonesia\b|\baustralia\b|\bnew zealand\b|\bgermany\b|"
    r"\bfrance\b|\bspain\b|\bportugal\b|\bitaly\b|\bnetherlands\b|\bbelgium\b|"
    r"\bpoland\b|\bromania\b|\bhungary\b|\bczech\b|\baustria\b|\bswitzerland\b|"
    r"\bsweden\b|\bnorway\b|\bdenmark\b|\bfinland\b|\bireland\b|\bisrael\b|"
    r"\buae\b|\bemirates\b|\bsaudi\b|\bqatar\b|\begypt\b|\bsouth africa\b|"
    r"\bkenya\b|\bnigeria\b|\bturkey\b|\bgreece\b|\bbulgaria\b|\bukraine\b|"
    # Eligibility requirements that only one country can satisfy.
    r"\bus citizenship\b|\bu\.s\. citizenship\b|\bmust be a us citizen\b|"
    r"\bgreen card\b|\bwork authorization in the (?:us|united states)\b",
    re.I,
)

# Non-UK cities that turn up in these particular job feeds.
_NON_UK_CITIES = re.compile(
    r"\bmadrid\b|\bbarcelona\b|\bmanila\b|\bkuala lumpur\b|\bsao paulo\b|"
    r"\bs[aã]o paulo\b|\bamsterdam\b|\bberlin\b|\bmunich\b|\bparis\b|"
    r"\bmilan\b|\brome\b|\bwarsaw\b|\bkrakow\b|\bprague\b|\bbudapest\b|"
    r"\bbucharest\b|\bstockholm\b|\boslo\b|\bcopenhagen\b|\bhelsinki\b|"
    r"\bdublin\b|\bzurich\b|\bgeneva\b|\bvienna\b|\bbrussels\b|\blisbon\b|"
    r"\btoronto\b|\bvancouver\b|\bmontreal\b|\bnew york\b|\bsan francisco\b|"
    r"\bseattle\b|\baustin\b|\bchicago\b|\bdenver\b|\batlanta\b|\bdallas\b|"
    r"\bhouston\b|\blos angeles\b|\bsan diego\b|\bphoenix\b|\bportland\b|"
    r"\bminneapolis\b|\bames\b|\bsault ste\b|\brancho cordova\b|\bbangalore\b|"
    r"\bbengaluru\b|\bmumbai\b|\bhyderabad\b|\bpune\b|\bchennai\b|\bdelhi\b|"
    r"\btokyo\b|\bsydney\b|\bmelbourne\b|\bauckland\b|\bdubai\b|\btel aviv\b",
    re.I,
)

# US/Canadian state and province codes, but only in "City, CA" position --
# matching bare two-letter tokens would catch far too much.
_STATE_CODE = re.compile(
    r",\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|MA|MD|ME|MI|"
    r"MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|"
    r"WA|WI|WV|WY|DC|ON|QC|BC|AB|MB|SK|NS|NB|NL|PE)\b"
)

# Workday-style prefixes: "US - Rancho Cordova, CA", "BR: Sao Paulo".
_COUNTRY_PREFIX = re.compile(
    r"^\s*(?:US|USA|CA|BR|MY|PH|IN|DE|FR|ES|IT|NL|PL|SE|NO|DK|FI|IE|AU|NZ|SG|"
    r"JP|CN|KR|ZA|AE|MX|AR|CL|CO|RO|HU|CZ|AT|CH|BE|PT|GR|TR|IL)\s*[-:–]",
    re.I,
)

_UK_CITIES = re.compile(
    r"\blondon\b|\bmanchester\b|\bbirmingham\b|\bbristol\b|\bleeds\b|\bglasgow\b|"
    r"\bedinburgh\b|\bcardiff\b|\bbelfast\b|\bliverpool\b|\bsheffield\b|"
    r"\bnewcastle\b|\bnottingham\b|\boxford\b|\bcambridge\b|\breading\b|"
    r"\bbrighton\b|\bsouthampton\b|\bportsmouth\b|\baberdeen\b|\bswindon\b|"
    r"\bmilton keynes\b|\bwarwick\b|\bcoventry\b|\bderby\b|\bleicester\b|"
    r"\bbath\b|\bexeter\b|\bplymouth\b|\bnorwich\b|\bipswich\b|\bpeterborough\b|"
    r"\bstevenage\b|\bslough\b|\bbasingstoke\b|\bguildford\b|\bwoking\b|"
    r"\bcrawley\b|\bmaidenhead\b|\bwatford\b|\bchelmsford\b|\bcolchester\b|"
    r"\bhull\b|\bmiddlesbrough\b|\bsunderland\b|\bdurham\b|\bpreston\b|"
    r"\bblackburn\b|\bbolton\b|\bstockport\b|\bwigan\b|\bwarrington\b|"
    r"\bchester\b|\bshrewsbury\b|\btelford\b|\bworcester\b|\bgloucester\b|"
    r"\bcheltenham\b|\bswansea\b|\bnewport\b|\bwrexham\b|\bdundee\b|"
    r"\binverness\b|\bstirling\b|\bfalkirk\b|\blivingston\b|\bsalford\b|"
    r"\bcroydon\b|\bkingston upon thames\b|\bhampshire\b|\bsurrey\b|\bkent\b|"
    r"\bessex\b|\bberkshire\b|\bhertfordshire\b|\byorkshire\b|\blancashire\b|"
    r"\bmidlands\b|\bdevon\b|\bcornwall\b|\bsomerset\b|\bwiltshire\b|"
    r"\bhome counties\b",
    re.I,
)


def classify_location(location: str | None, body: str | None = None) -> str:
    """Return "uk", "non_uk" or "unknown" for a posting.

    ``location`` is the structured field and is trusted. ``body`` is only
    consulted when the location field says nothing useful, since a job
    description can mention any number of offices it is not based in.
    """
    loc = (location or "").strip()

    if loc:
        verdict = _classify_field(loc)
        if verdict != UNKNOWN:
            return verdict

    # Nothing decisive in the location field -- try the body, but only trust a
    # clear country statement, not a passing city mention.
    #
    # The window is deliberately limited to the top of the page. That is where
    # the location header sits ("Remote: United States | Canada"), whereas
    # further down these pages routinely list every country the company has an
    # entity in -- Overstory's US-and-Canada-only role names ten countries
    # including the UK in its benefits boilerplate. Reading the whole body would
    # turn that into a false UK match.
    text = (body or "")[:4000]
    if text:
        if _UK_STRONG.search(text) and not _NON_UK_COUNTRIES.search(text):
            return UK
        if _NON_UK_COUNTRIES.search(text) and not _UK_STRONG.search(text):
            return NON_UK

    return UNKNOWN


def _classify_field(loc: str) -> str:
    # "Northern Ireland" must beat the "ireland" non-UK token.
    if re.search(r"\bnorthern ireland\b", loc, re.I):
        return UK

    non_uk_signal = bool(
        _NON_UK_COUNTRIES.search(loc)
        or _NON_UK_CITIES.search(loc)
        or _STATE_CODE.search(loc)
        or _COUNTRY_PREFIX.search(loc)
    )
    uk_signal = bool(_UK_STRONG.search(loc))

    # An explicit UK token wins over a stray match such as "UK - London, US team".
    if uk_signal and not non_uk_signal:
        return UK
    if non_uk_signal and not uk_signal:
        return NON_UK
    if uk_signal and non_uk_signal:
        return UNKNOWN

    # No country signal either way -- now a bare city name is safe to use.
    if _UK_CITIES.search(loc):
        return UK

    return UNKNOWN
