"""Artifact version resolution (static pin / auto-increment / manifest)."""

import json

import config


def version_string(version):
    return ".".join(str(v) for v in version) if isinstance(version, list) else str(version)


def bump_version(v):
    """Increment the last numeric segment of a dotted version, e.g. 1.1.9 -> 1.1.10."""
    parts = v.split(".")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].isdigit():
            parts[i] = str(int(parts[i]) + 1)
            return ".".join(parts)
    return v  # nothing numeric to bump; leave unchanged


def read_stored_version():
    """The last version written to VERSION_FILE, or None if absent/unreadable."""
    try:
        with open(config.VERSION_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


def write_stored_version(v):
    with open(config.VERSION_FILE, "w", encoding="utf-8") as fh:
        json.dump({"version": v}, fh, indent=2)


def resolve_version(bp_info):
    """Work out the artifact version and where it came from, in priority order:

      1. static `version` setting
      2. autoVersion: bump the stored version each run (first run seeds from the
         manifest, or from `version` if you set one)
      3. the behavior pack manifest version (the original default)
    """
    manifest_version = version_string(bp_info["version"])

    if config.VERSION_OVERRIDE:
        return config.VERSION_OVERRIDE, "version setting"

    if config.AUTO_VERSION:
        stored = read_stored_version()
        if stored:
            new = bump_version(stored)
            note = f"auto (bumped from {stored})"
        else:
            new = manifest_version
            note = "auto (seeded)"
        write_stored_version(new)
        return new, note

    return manifest_version, "manifest"
