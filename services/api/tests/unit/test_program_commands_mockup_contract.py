"""Design check for PGD-04 (AF-02): the API satisfies the Program Detail mockup's contract.

`docs/config/project-commands.yaml`'s `design_check:` key is empty -- no a11y / console-scan
tool is wired, and one would not help here anyway: PGD-04 ships no rendered page for a browser
to visit (backend endpoint + a server-only Next.js proxy, per REQUIREMENTS.md Scope). The
design obligation that DOES apply to a backend story is the one CLAUDE.md § Design system
states: an API story must "supply exactly what the mockup's bindings consume -- the set of
fields, their pre-formatted values, and the empty/loading states the `hint-placeholder-count`
attributes imply."

This module discharges that obligation as an executable check against
`docs/design/mockups/Program Detail.html` § COMMANDS, decoded per `docs/design/README.md`.
Each test names the mockup binding it protects, so a future change to either side breaks here
rather than silently drifting from the design.

Mockup ground truth (decoded markup L507-539; mock-data generator L740-758):

    <sc-for list="{{ commands }}" as="c" hint-placeholder-count="6">
      <code>{{ c.cmd }}</code>  <span>{{ c.count }} runs</span>
      <div style="{{ c.barStyle }}"></div>
    ...header: {{ cmdTotal }} "total runs", subtitle "... {{ cmdRangeLabel }}"

    commands = cmdMix.map((c, i) => ({
      cmd: '/' + c.cmd, count: cmdCounts[i],
      barStyle: `...width:${Math.round((cmdCounts[i] / cmax) * 100)}%...`,
    }));
"""

from app.schemas.personal_usage import CommandEntry, CommandsPanel
from app.utils.format import bar_style_for_share, format_number


def test_panel_supplies_every_field_the_mockup_binds() -> None:
    """Mockup binds exactly `cmdTotal`, and per row `c.cmd`, `c.count`, `c.barStyle`.

    `total_runs` carries `cmdTotal`; `command`/`count`/`barStyle` carry the row bindings.
    A field the mockup binds but the API omits would render blank in the panel.
    """
    panel = CommandsPanel(
        total_runs=format_number(12),
        items=[
            CommandEntry(command="/arh-implement", count=12, barStyle=bar_style_for_share(12, 12))
        ],
    )
    wire = panel.model_dump(by_alias=True)

    assert set(wire) == {"total_runs", "items"}
    assert set(wire["items"][0]) == {"command", "count", "barStyle"}


def test_row_bar_uses_max_of_range_matching_the_generator() -> None:
    """Generator: `width:${Math.round((cmdCounts[i] / cmax) * 100)}%` -- cmax, NOT the total.

    The tallest bar is always 100%. Share-of-total would make it 30% for the mockup's own
    top entry (w=0.30), visibly wrong against the design.
    """
    counts = [30, 23, 18, 12, 9, 8]  # the mockup's own cmdMix weights, x100
    max_count = max(counts)

    assert bar_style_for_share(counts[0], max_count) == "width: 100%;"
    assert bar_style_for_share(counts[1], max_count) == "width: 77%;"
    # Share-of-total would yield 30% for the leader -- assert we are NOT doing that.
    assert bar_style_for_share(counts[0], sum(counts)) != bar_style_for_share(counts[0], max_count)


def test_command_keeps_the_leading_slash_the_code_chip_renders() -> None:
    """Generator composes `'/' + c.cmd`, so the <code> chip shows `/arh-implement story`.

    Real ingest data already stores the slash (`docs/activity/activity.jsonl`:
    `"command":"/arh-init"`), so the API passes through verbatim. Synthesizing one would
    render `//arh-init`; stripping one would render a chip unlike the design.
    """
    entry = CommandEntry(command="/arh-init", count=1, barStyle=bar_style_for_share(1, 1))

    assert entry.model_dump(by_alias=True)["command"] == "/arh-init"


def test_count_is_numeric_and_total_is_preformatted_as_the_bindings_expect() -> None:
    """`{{ c.count }}` renders beside the literal "runs", so it is a bare number.

    `{{ cmdTotal }}` is the 22px headline figure and arrives display-ready -- the template
    applies no formatting of its own.
    """
    wire = CommandsPanel(
        total_runs=format_number(1500),
        items=[CommandEntry(command="/arh-init", count=1500, barStyle="width: 100%;")],
    ).model_dump(by_alias=True)

    assert isinstance(wire["items"][0]["count"], int)
    assert isinstance(wire["total_runs"], str)


def test_empty_panel_renders_the_placeholder_state_without_breaking_bindings() -> None:
    """`hint-placeholder-count="6"` is a canvas hint, not a row-count contract.

    The real empty state is an empty `commands` list plus a `cmdTotal` that still renders --
    so `total_runs` must be the string `"0"`, never null or absent, or the headline binding
    renders blank. This is D-02's `200 {total_runs: "0", items: []}` seen from the design side.
    """
    wire = CommandsPanel(total_runs="0", items=[]).model_dump(by_alias=True)

    assert wire["total_runs"] == "0"
    assert wire["items"] == []
