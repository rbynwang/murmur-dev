"""The words of the architecture-and-data page: the boxes of the map, the rules under it, the four kinds of source, where each
part's data comes from, and the eight steps of the recorded evening.

Four kinds of source, each a letter that is also its colour's class on the page:
  e   ENGIE's own dataset
  s   our product survey (current US products, from their makers' datasheets)
  m   public measured records (neither ENGIE's nor estimates: utility load research, a federal survey, city reports,
      measured buildings)
  o   our own estimates (set or computed by us where no record exists)

A sentence that carries a figure is written whole here, with the figure from `figures.Figures`.
"""
from __future__ import annotations

from typing import NamedTuple

from .figures import Figures


class Source(NamedTuple):
    tag: str  # the short label on the source's tag
    name: str
    what: str


class Box(NamedTuple):
    part: str  # the box's id on the map, its data-b attribute
    name: str
    role: str  # ML, CODE, AI, HARDWARE or PERSON; empty for a box that is none of these
    line: str  # one line under the name, or empty


class Row(NamedTuple):
    """One part of the architecture in the table of sources: what it does, and what it reads from each kind of source."""
    part: str
    role: str
    does: str
    reads: tuple[tuple[str, str], ...]  # (kind of source, what is read from it)


class Group(NamedTuple):
    key: str  # the section's anchor is d-<key>
    name: str
    rows: tuple[Row, ...]


class Step(NamedTuple):
    moment: str  # the replay moment the step shows
    title: str
    caption: str


SOURCES = {
    "e": Source("ENGIE", "ENGIE's own dataset", "Its 2025 records, used unchanged."),
    "s": Source("Survey", "Our product survey", "Current US products, read from their makers' datasheets."),
    "m": Source("Measured", "Public measured records", "Utility load research, a federal survey, city reports, measured buildings."),
    "o": Source("Ours", "Our own estimates", "Set or computed by us where no record exists. Each one is named."),
}
# The measured house the homes' model is checked against, described by what its records hold.
HOMES_MODEL_SOURCE = "a measured multi-story instrumented research house dataset, circuit-level heat pump, lighting, and plug loads"

# ---------------------------------------------------------------- the map: the boxes of each frame
AGGREGATOR = (Box("agg-clean", "Reading cleaner", "ML", "Takes noise out of the grid's readings"),
              Box("agg-share", "Sharing-out", "CODE", "Who is asked, and for how much"),
              Box("agg-req", "Request agent", "CODE", "Sends each its request, signed"),
              Box("agg-ref", "Referee", "CODE · AI", "Checks reports. AI reads their words"))
BUYERS = (Box("buy-u", "Buyer: utility", "", "Orders the cut, and pays for it"),
          Box("buy-g", "Buyer: grid operator", "", "Same evening, same pool"),
          Box("util", "The utility", "", "Sets the most the community may send out"))
COMMUNITY = (Box("co-forecast", "Community forecast", "ML", ""), Box("co-cover", "Promise and cover", "CODE", ""),
             Box("co-batt", "Members' batteries", "", ""), Box("co-clear", "Day-ahead clearing", "CODE", ""),
             Box("co-gap", "Gap filling", "CODE", ""), Box("co-report", "Verify and report", "CODE", ""))
HOME = (Box("h-agent", "Home agent", "CODE", ""), Box("h-model", "Small model", "AI", "Reads what the owner writes"),
        Box("h-guard", "Tool server, guard, seal, driver", "CODE", "The guard has the last word"),
        Box("h-dev", "The house and its devices", "HARDWARE", ""), Box("h-person", "Home owner", "PERSON", ""))
BUILDING = (Box("b-agent", "Building agent", "CODE", ""), Box("b-model", "Small model", "AI", "Reads what the manager writes"),
            Box("b-guard", "Tool server, guard, seal, driver", "CODE", "The guard has the last word"),
            Box("b-dev", "The building and its devices", "HARDWARE", ""), Box("b-person", "Building manager", "PERSON", ""))
PLANT = (Box("pv-agent", "Site agent", "CODE", "Holds for the peak"), Box("pv-limits", "Its own limits", "", "Rating, charge, connection"),
         Box("pv-batt", "Battery", "HARDWARE", ""), Box("pv-op", "Its operator", "PERSON", "May set a limit"))
DATA_CENTER = (Box("dc-agent", "Site agent", "CODE", "Less at the peak"), Box("dc-limits", "Its own limits", "", "Rating, charge, connection"),
               Box("dc-batt", "Battery and jobs", "HARDWARE", "Work that can wait"), Box("dc-op", "Its operator", "PERSON", "May set a limit"))
RETURN_PATH = (Box("ret-read", "Readings", "", "Signed by each node"), Box("ret-check", "Checks", "", "At every door"),
               Box("ret-settle", "Settlement", "", "On what meters show"), Box("ret-pay", "Payment", "", "By delivery, on record"))

RULES = ("The aggregator, such as ENGIE, asks for less draw from 18:00 to 21:00. It asks. It never orders.",
         "A community answers through its community agent, which turns its members' offers into one promise. A data center and a "
         "solar-and-battery plant each answer for themselves.",
         "Code decides every amount. AI has one part: reading what people write, and the words in reports.",
         "A guard checks every command before it reaches a device, and has the last word.",
         "Only amounts leave a site. Every message between owners crosses NANDA Town, signed.")

# ---------------------------------------------------------------- the map marked by source
# The kinds of source each box reads itself, in the order e s m o; a box with none is code that holds no data of its own.
# "co" is the community's frame and "town" the message network.
READS = {"agg-clean": "e", "agg-share": "eo", "agg-req": "", "agg-ref": "eo", "buy-u": "eo", "buy-g": "eo", "util": "e",
         "co": "eo", "co-forecast": "eo", "co-cover": "o", "co-batt": "e", "co-clear": "o", "co-gap": "o", "co-report": "eo",
         "h-agent": "", "h-model": "o", "h-guard": "so", "h-dev": "esmo", "h-person": "o",
         "b-agent": "", "b-model": "o", "b-guard": "s", "b-dev": "esmo", "b-person": "o",
         "pv-agent": "", "pv-limits": "e", "pv-batt": "e", "pv-op": "o", "dc-agent": "", "dc-limits": "e", "dc-batt": "eo", "dc-op": "",
         "town": "", "ret-read": "o", "ret-check": "", "ret-settle": "o", "ret-pay": "o"}
SHORT = {"h-guard": "Guard and driver", "b-guard": "Guard and driver", "h-dev": "House and devices", "b-dev": "Building and devices"}
SURVEY_TITLES = {"home": "In a home", "building": "In a building"}


def key_lines(f: Figures) -> dict[str, str]:
    """The line under each kind of source in the key: what the page draws from it."""
    return {
        "e": f"{f.participants} participants, every 15 minutes of 2025: {f.solar_and_battery_plants} solar-and-battery plants, "
             f"{f.data_centers} data centers, {f.communities} communities. A 200-bus grid, read every hour.",
        "s": f"{f.products} products of {f.brands} brands in {f.kinds} kinds of equipment. The latest generation, each with its "
             "maker's ratings.",
        "m": f"Six sources: National Grid load research, {HOMES_MODEL_SOURCE}, the federal household survey, Boston's building "
             "reports, Boston Public Library's meter, measured weather.",
        "o": "Household types and owners' limits, when cars charge, the community's solar by day, the price of a cut and how the "
             "pay is split.",
    }


def data_groups(f: Figures) -> tuple[Group, ...]:
    """Every part of the architecture, group by group, with where its data comes from."""
    return (
        Group("agg", "The aggregator and the buyers", (
            Row("Reading cleaner", "ML", "Cleans the grid's readings before any plan is made.", (
                ("e", "The loading of every transformer, hour by hour, for 2025."),
                ("e", "ENGIE's 2023 release, where the true grid state is known. The cleaning is proven on it."))),
            Row("Sharing-out", "CODE", "Works out the need by hour and shares it among all 80.", (
                ("e", "Every participant's battery: power, energy, charge and connection limit."),
                ("e", "How far a transformer's loading falls for each MW given at a site, fitted on the 2023 grid state."),
                ("o", "The line to stay under: 80% of a transformer's rating."))),
            Row("Request agent", "CODE", "Sends each participant the sharing-out's figures, signed. It holds no data of its own.", ()),
            Row("Referee", "CODE · AI", "Checks every report row. A small model reads only the words.", (
                ("e", "The report layout ENGIE's participants send: net power, charge, a quote and a note."),
                ("e", "ENGIE's own 2025 reports, with the false ones they hold. The referee was built and measured on them."),
                ("o", "Its settings: every report is held against the meter at 30 minutes and at 2 hours."),
                ("o", "The false reports planted in our own runs."))),
            Row("The buyers and their order", "", "A utility and a grid operator order the cut. In the runs they are stand-ins.", (
                ("e", "The window, 18:00 to 21:00: the three dearest hours in ENGIE's prices, in every month of 2025."),
                ("e", f"The community's connection limit, {f.host_connection_limit_kw:,.0f} kW."),
                ("o", "The price of a cut: $2.04 per kWh, our conversion of a Massachusetts programme's $275 per kW. Range $1.53 "
                      "to $3.06."),
                ("o", "The size of the order, set so that all that is offered is taken."),
                ("o", "The pay split: 70% members, 10% the community's operator, 20% the aggregator."))),
        )),
        Group("co", "The community and its agent", (
            Row("The community's own record", "", "One of ENGIE's 20 communities is the host. Our homes and buildings sit inside it.", (
                ("e", "Net power at its meter, every 15 minutes of 2025."),
                ("e", f"Its solar size, {f.host_solar_kw:,.0f} kW, and its temperature, sunlight and prices."),
                ("o", "Its solar by day, estimated from ENGIE's 35 metered solar plants (R² 0.92)."),
                ("o", "The split of its use: our 200 homes 23%, our office 3%, our shops 6%. The other 68% stays as ENGIE "
                      "recorded it."))),
            Row("Members' batteries", "", "The homes' own batteries, held for the peak. The community has none of its own.", (
                ("e", f"ENGIE's one figure for the community's home batteries: {f.host_home_batteries_kw:,.0f} kW and "
                      f"{f.host_home_batteries_kwh:,.0f} kWh, with their reported charge."),)),
            Row("Community forecast", "ML", "What its members will draw and can give tomorrow evening.", (
                ("e", "ENGIE's temperature and sunlight."),
                ("o", "Forecast models trained on our 200 homes."),
                ("o", "For a building, the last day of the same kind."))),
            Row("Promise and cover", "CODE", "Promises less than its members offered, in case they deliver less.", (
                ("o", "The cover is taken from the community's own record of earlier evenings. Until three are on record it is "
                      "a fixed 10%."),)),
            Row("Clearing, gap filling, report", "CODE", "Clears the offers, fills gaps on the day, and reports upward.", (
                ("e", "The report goes upward in ENGIE's own layout. No member is named in it."),
                ("o", "Each member's baseline: its ten most recent similar days, adjusted to the day itself."))),
        )),
        Group("home", "Homes: 200 households, eight of them on the network", (
            Row("The house, its heating and cooling", "HARDWARE", "A physics model of each house, checked against measured homes.", (
                ("m", "National Grid load research: the average Massachusetts home, hour by hour. Shape of the day r = 0.92."),
                ("m", f"{HOMES_MODEL_SOURCE.capitalize()}: one measured house, its solar and its heat pump."),
                ("o", "Each house's physics: one thermal mass, heat loss 0.15 to 0.67 kW per °C."))),
            Row("Its devices", "HARDWARE", "Battery, car and charger, thermostat, water heater, dryer, dishwasher, pool pump.", (
                ("s", f"{f.home.products} products of {f.home.brands} brands in {f.home.kinds} kinds. Each rating comes from its "
                      "maker's datasheet."),
                ("s", "Seven battery products, and cars from 19 models."),
                ("m", "Which home owns what: the federal household survey (EIA RECS 2024), Massachusetts single-family homes."),
                ("o", "A two-way car in every home at the full level. It is an ideal case: 34 of the 200 cars can power a home "
                      "today."))),
            Row("The people", "PERSON", "Who is home, what they allow, and what they write to their agent.", (
                ("o", "Six household types, with the holidays and school breaks of 2025."),
                ("o", "Each owner's limits: how much warmer the house may get, a car timer, devices that are off limits."),
                ("o", "When cars leave, return and charge. No public measured home-charging data exists."),
                ("o", "The notes the small model reads: written by us for the tests, each with its true meaning set down first."))),
            Row("The weather", "", "", (
                ("e", "ENGIE's temperature and sunlight at its site."),
                ("m", "A second version of the year adds the real day-to-day movement of measured Massachusetts weather."))),
        )),
        Group("bld", "Buildings: a small office and a strip of shops", (
            Row("Size, energy and shape of the day", "HARDWARE", "How much each building uses, and when.", (
                ("e", "ENGIE's temperature and sunlight, as for the homes."),
                ("m", "Boston's building energy reports (BERDO 2025). Our office matches 56 Boston offices, middle size 37,000 sq "
                      "ft. Our shops match 8 strip malls and stores, 50,000 sq ft."),
                ("m", "National Grid's business classes: the hourly shape of each building type."),
                ("m", "Boston Public Library's meter, every 5 minutes: real day-to-day variation, from 380 usable days."))),
            Row("Its equipment and limits", "HARDWARE", "Cooling, fans, lights and plugs, and what each may do.", (
                ("s", f"{f.building.products} products of {f.building.brands} brands in {f.building.kinds} kinds."),
                ("s", "224 control rules, checked against makers' documents and the mechanical code. The guard keeps them."))),
            Row("Who is in, and where", "PERSON", "", (
                ("o", "An occupancy plan by zone, made the day before, and the day as it truly went."),
                ("o", "How cooling, fans, lights and plugs split among zones: assigned by floor area. No public source gives it."),
                ("o", "The manager's notes the small model reads: written by us for the tests."))),
        )),
        Group("site", "Solar-and-battery plants and data centers", (
            Row("Each site's meter, battery and limits", "HARDWARE", "Each site answers the aggregator for itself.", (
                ("e", f"{f.solar_and_battery_plants} plants and {f.data_centers} data centers: net power and battery charge "
                      "every 15 minutes, with each battery's power and energy and the site's connection limit."),)),
            Row("A data center's work that can wait", "", "", (
                ("e", "ENGIE's 2023 release: 16.3% of the data centers' energy can wait, for 4.5 to 10.5 hours."),
                ("o", "Its carry-over to the same sites' 2025 load."))),
            Row("A note from a person at a plant", "PERSON", "", (
                ("o", "Three notes written by us for the test, each with its true meaning set down first."),)),
        )),
        Group("net", "The network and the payment", (
            Row("NANDA Town", "", "MIT's NANDA Town, run locally. It carries signed envelopes and reads nothing inside. It is "
                "software, and holds no data.", ()),
            Row("Readings, settlement, payment", "", "", (
                ("o", "The meters are the simulated devices' own. A twin of each home and building with no sale gives the truth."),
                ("o", "Pay follows delivery against the baseline, at the price above."))),
        )),
    )


def steps(f: Figures) -> tuple[Step, ...]:
    """The eight moments of the recorded evening the page steps through, each with the replay's own headline."""
    h = {mid: m.headline for mid, m in f.moments.items()}
    less = f.less_at_18_kw
    return (
        Step("orders", "Two buyers order the same evening",
             f"A utility and a grid operator each order a cut from 18:00 to 21:00: {h['orders']} in all, for each half hour."),
        Step("cover", "The community agent promises, with a cover",
             f"Ten members offer {h['offers-in']}. The community agent promises {h['cover']} upward and keeps the rest as cover, "
             "in case its members deliver less."),
        Step("agg-share", "The need is shared out among all the batteries",
             f"Next afternoon the aggregator plans. The grid needs {f.needed_at_19_mw:.0f} MW less at 19:00 and all 80 batteries "
             f"can give {f.all_batteries_can_give_mw:.0f}, so each is asked for all it has. This community's part is "
             f"{h['agg-share']}."),
        Step("battery-ask", "A signed request, and a signed answer",
             "The request crosses NANDA Town as a signed message, and the community agent takes it. An hour earlier a planted "
             "request, for twice the batteries' rating, was refused in writing."),
        Step("site-ask", "The single sites are asked the same way",
             "The same signed request goes to two solar-and-battery plants and a data center, with no coordinator in between. "
             f"The largest plant is asked for {h['site-ask']} at 19:00."),
        Step("window", "The sale runs",
             f"At 18:00 the community draws {h['window']} less than its twin with no sale: {less['homes']:.0f} from homes and "
             f"{less['buildings']:.0f} from buildings."),
        Step("agg-ref", "The referee checks every report",
             "Every quarter hour each participant reports upward, signed. The referee holds every row to its checks: "
             f"{h['agg-ref']} are trusted, and nothing is held back."),
        Step("settle", "Buyers pay on what the meters show",
             f"{h['settle']} for {f.settled_kwh:,} kWh, at our assumed price. {h['pay']} of it goes to the members, by what each "
             "delivered."),
    )


def evening_figures(f: Figures) -> tuple[tuple[str, str], ...]:
    """The four figures under the steps: (the figure, what it counts)."""
    return ((f"{f.messages:,}", "signed messages over NANDA Town, and no signature failed"),
            (f"{f.site_rows_as_planned} of {f.site_rows}", "report rows from the three single sites, each as the plan expected"),
            (f"{f.promised_kw:.0f} kW", f"promised on average over the evening, and {f.delivered_kw:.0f} kW delivered on the buyers' "
                                        "meters"),
            (f.moments["agg-ref"].headline, "of the community's report rows trusted by the referee"))
