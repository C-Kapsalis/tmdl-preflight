# Bookmark visual references

*Rule [B002](../reference/rules.md#b002--bookmark-visual-refs).*

## The pitfall

A bookmark captures the state of specific visuals, and it addresses them by
name — the identifier that is also the visual's folder name under
`pages/<page>/visuals/<name>/`. The bookmark file and the visual folder are
separate artifacts, which sets up the same drift problem as
[relationships vs tables](relationship-integrity.md): delete or rebuild a
visual (rebuilding assigns a *new* name), and every bookmark that captured
it now points at nothing.

What makes this pitfall distinctive is that the failure is **silent**. A
dangling relationship blocks an import; a dangling bookmark reference
mostly doesn't. The bookmark still loads, still appears in the bookmarks
pane, still plays in the story sequence. It just quietly fails to do part —
or all — of what it was authored to do: the visual it was meant to
spotlight, hide, or filter is not addressed by anything. The person who
notices is not the developer but a report consumer, weeks later, observing
that "the presentation view stopped highlighting the chart" — a bug report
that is miserable to trace back to a visual rebuilt in some earlier sprint.

## How the rule detects it

For each `*.Report` folder, the rule builds the set of actual visual
folder names under `pages/*/visuals/`, then walks every bookmark's
references — `explorationState.visualContainers` (both the keyed-object
and the list forms) and `options.targetVisualNames` — and reports every
name with no matching folder, per bookmark, per reference.

## Why there is no auto-fix

A dangling reference has three legitimate resolutions, and they point in
different directions:

1. the visual was deleted **on purpose** → delete or re-author the
   bookmark;
2. the visual was rebuilt → retarget the reference to the new name;
3. the deletion was the mistake → restore the visual.

Choosing requires knowing why the visual disappeared — intent the files do
not record. An auto-fix that, say, pruned dangling references would
convert option 3 from "restore and everything works again" into "restore
and the bookmark still ignores it", actively destroying information. So
the rule reports and fails; the resolution stays human.
