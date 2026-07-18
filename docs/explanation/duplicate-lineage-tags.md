# Duplicate and malformed lineage tags

*Rules [M003](../reference/rules.md#m003--lineage-duplicates) and
[M004](../reference/rules.md#m004--lineage-format).*

## The pitfall

Every object in a TMDL model — table, column, measure, partition,
relationship — carries a `lineageTag`, a UUID that identifies the object
*across renames and moves*. Names are for humans; lineage tags are how
deployment tooling knows that the `Revenue` measure in this commit is the
same object as the `Total Revenue` measure in the last one, so it can update
rather than drop-and-recreate it.

That identity mechanism has one hard requirement: **tags must be unique
within the model**. When two objects share a tag, the deployment target
cannot tell them apart, and imports are rejected outright with a message of
the form *"an object with that lineage tag already exists in the
collection."* The model that looked perfectly healthy in your editor is
simply undeployable.

What makes this pitfall nasty is how easily duplicates appear and how
invisible they are:

- **Copy-paste is the normal way to author TMDL.** Duplicating a table
  file, or a measure block within one, duplicates every `lineageTag` inside
  it. Nothing in the file looks wrong afterwards — the tags are valid UUIDs,
  just not unique ones.
- **Merges concatenate.** A merge that keeps both sides of a conflicted
  measure block silently keeps both tags.
- **The failure is far from the cause.** The duplicate is introduced in an
  editor today and detected by a deployment pipeline days later, with an
  error message that names the tag but not the two files carrying it.

A cousin of the same problem is the **malformed tag**: a placeholder typed
by hand (`todo-fix-later`, `not-a-real-uuid`) or produced by a broken
script. The engine may tolerate some of these, but they defeat the purpose
of the mechanism — a placeholder pasted into three objects is three future
duplicates — so tmdl-preflight flags any tag that is not a canonical
hyphenated UUID (8-4-4-4-12 hex).

## How the rules detect it

The scan is deliberately blunt: every `lineageTag:` line in every `.tmdl`
file under the definition folder is collected with its file, line number
and nearest enclosing declaration (table/column/measure/partition/
relationship). M003 reports every occurrence of a tag after its first; M004
reports every tag that fails the canonical-UUID pattern. Working at the
line level rather than the object level means the check also catches tags
on objects the parser does not model deeply (hierarchies, for instance).

## Why the fix is safe

Regenerating a lineage tag is safe precisely because of what a duplicate
means: **a duplicated tag carries no usable identity anyway.** The
deployment target cannot use it to track either object, so replacing the
*second* occurrence with a fresh `uuid4` loses nothing — it simply gives
the copied object the new identity it should have had from the start. The
first occurrence, which usually belongs to the original object, is never
touched, so any deployment history attached to it is preserved.

The mechanical properties follow the fixer safety contract: the edit
rewrites exactly one value on exactly one line (preserving the file's
newline style), touches no DAX and no names, and is idempotent — once all
tags are unique, there is nothing left to rewrite. Malformed tags are
repaired the same way, for the same reason: a placeholder never carried
real identity either.

One honest caveat: if the *first* occurrence was the copy and the second
the original, the regenerated object's deployment history is the one that
survives under the old tag. The model is still correct — at worst, one
object is recreated instead of updated on the next deploy.

## See also

- [The imposition pattern](imposition-pattern.md) — the check → fix →
  re-check loop this fixer runs inside.
