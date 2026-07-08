"""Aggressive, reference-safe obfuscation for a built Bedrock addon.

Operates on the two *built* pack folders (BP and RP) and produces, for every
file, a (possibly new) archive-relative path plus (possibly rewritten) bytes.
Driven entirely by :class:`Options`.

Modules:
    options   the Options object (which passes run, flatten behaviour)
    classify  which folders/files may be renamed/moved
    names     deterministic short-name generation + token replacement
    plan      the Plan engine (scan -> maps -> transform)
    __main__  a standalone dry-run (python -m obfuscate <BP> <RP> [--all])

Safety principles:
  * Only identifiers *defined inside the pack* are ever renamed; references to
    vanilla / dependency ids are left untouched.
  * Renames are deterministic (hash-based) so rebuilds are stable.
  * Path budget + reference coverage are validated; ``strictPaths`` turns an
    over-length path into a hard build error.

Note: particle / animation *identifier* renaming is off by default (they are
commonly referenced from scripts, sometimes dynamically). Sound renaming touches
only the .ogg *files* (whose paths live in sound_definitions.json), so it is
reliable and stays on.
"""

from jsonc import strip_jsonc, try_load_json  # noqa: F401  (re-exported)

from .options import Options  # noqa: F401
from .plan import Plan  # noqa: F401
