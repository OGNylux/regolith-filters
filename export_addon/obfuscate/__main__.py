"""Standalone dry-run: prints the rename plan + coverage without writing anything.

    python -m obfuscate <BP_dir> <RP_dir> [--all]

(run from the filter directory so ``obfuscate`` and ``jsonc`` are importable).
"""

import os
import sys

from .options import Options
from .plan import Plan


def _dry_run(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    bp, rp = (args + [None, None])[:2]
    packs = []
    if bp and os.path.isdir(bp):
        packs.append(("BP", bp))
    if rp and os.path.isdir(rp):
        packs.append(("RP", rp))
    if not packs:
        print("usage: python -m obfuscate <BP_dir> <RP_dir> [--all]")
        return 2

    on = {k: True for k in Options.KEYS} if "--all" in flags else {}
    opt = Options(on)
    plan = Plan(packs, opt)

    print("== rename plan ==")
    for k, v in plan.summary().items():
        print("  %-22s %d" % (k, v))

    problems = plan.validate()
    over = [p for p in problems if p.startswith("path >")]
    refs = [p for p in problems if not p.startswith("path >")]
    print("\n== pack-relative path budget (<= %d) ==" % opt.max_path)
    print("  paths over limit: %d" % len(over))
    for p in over[:12]:
        print("   ", p)
    print("\n== reference coverage ==")
    print("  unresolved references: %d" % len(refs))
    for p in refs[:12]:
        print("   ", p)

    # sample a few renames
    for kind, _ in packs:
        items = list(plan.paths[kind].items())[:4]
        if items:
            print("\n== sample %s file renames ==" % kind)
            for o, n in items:
                print("  %s\n    -> %s" % (o, n))
    return 0


if __name__ == "__main__":
    sys.exit(_dry_run(sys.argv[1:]))
