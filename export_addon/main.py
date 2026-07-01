"""Regolith filter: export the built addon as .mcworld, .zip, .mcaddon and package.

Runs after the build, from inside ``.regolith/tmp`` (which contains ``BP/``,
``RP/`` and ``data/``). It reads the freshly built packs and writes the
packaged artifacts to ``<ROOT_DIR>/<outputDir>``.

    zip       -> "<name>.zip": the behavior + resource pack (each in its own folder)
    mcaddon   -> "<name>.mcaddon": a byte-for-byte copy of the .zip, just renamed
    mcworld   -> "<name>.mcworld": a world (from a template) with the packs installed
    package   -> "<name> Package.zip": the full marketplace-submission bundle
                 (Content/{behavior,resource}_packs + Marketing Art + Store Art)

Settings (all optional, passed as a JSON string argument by Regolith):
    name             base file name                (default: config.json "name")
    outputDir        output folder (rel to root)   (default: "dist")
    formats          list of formats to emit       (default: mcworld, zip, mcaddon)
    obfuscateJson    minify JSON in artifacts      (default: False)
    obfuscateScripts obfuscate JS in artifacts     (default: False; needs Node)
    obfuscatorArgs   extra obfuscator CLI args     (default: MC-safe conservative set)
    marketingArt     source folder -> "Marketing Art" in package  (default: "Marketing Art")
    storeArt         source folder -> "Store Art" in package      (default: "Store Art")
    bpName           BP folder name in archives    (default: config pack folder name)
    rpName           RP folder name in archives    (default: config pack folder name)
    template         path to template .mcworld     (default: bundled template)
    worldName        LevelName for the .mcworld    (default: versioned file name)
    randomizeSeed    randomize the world seed      (default: True)
    appendVersion    append the version to names   (default: True)
    version          static version string to pin  (default: BP manifest version)
    autoVersion      auto-increment each run        (default: False)
    versionFile      where the auto version is kept (default: ".export_version.json")
    versionSubfolder artifacts go in dist/<version> (default: True)
    versionPrefix    text before the version       (default: "", e.g. "v")
    obfuscatorVersion javascript-obfuscator ver    (default: "4")

Version resolution (highest priority first): the static `version` setting,
autoVersion (bump the stored version), then the BP manifest version.

Obfuscation is applied only to the bytes written into the artifacts; the build
output exported to com.mojang is left readable.
"""

import io
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

# Bedrock level.dat: 8-byte header (version + payload length) before the NBT.
HEADER_SIZE = 8

settings = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}

# cwd is `.regolith/tmp`; ROOT_DIR is set by Regolith but fall back to it.
ROOT_DIR = os.environ.get("ROOT_DIR") or os.path.abspath(os.path.join(os.getcwd(), "..", ".."))
FILTER_DIR = os.path.dirname(os.path.abspath(__file__))



def load_config():
    """The Regolith config (config.json) from the project root."""
    try:
        with open(os.path.join(ROOT_DIR, "config.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


CONFIG = load_config()


def pack_folder_name(key, default):
    """Folder name (archive name) for a pack, taken from config's pack path."""
    path = CONFIG.get("packs", {}).get(key)
    return os.path.basename(path.rstrip("/\\")) if path else default


NAME = settings.get("name") or CONFIG.get("name") or "addon"
OUTPUT_DIR = os.path.join(ROOT_DIR, settings.get("outputDir", "dist"))
FORMATS = settings.get("formats", ["mcworld", "zip", "mcaddon"])
BP_NAME = settings.get("bpName") or pack_folder_name("behaviorPack", "BP")
RP_NAME = settings.get("rpName") or pack_folder_name("resourcePack", "RP")
TEMPLATE = (
    os.path.join(ROOT_DIR, settings["template"])
    if settings.get("template")
    else os.path.join(FILTER_DIR, "template.mcworld")
)
RANDOMIZE_SEED = settings.get("randomizeSeed", True)
APPEND_VERSION = settings.get("appendVersion", True)
VERSION_OVERRIDE = settings.get("version")
VERSION_PREFIX = settings.get("versionPrefix", "")
# Auto-increment: bump a stored version each run. Persisted to a small JSON file
# at the project root so it survives across runs (commit it to share/CI).
AUTO_VERSION = settings.get("autoVersion", False)
VERSION_FILE = os.path.join(ROOT_DIR, settings.get("versionFile", ".export_version.json"))
# Write each version's artifacts into its own subfolder of outputDir.
VERSION_SUBFOLDER = settings.get("versionSubfolder", True)

# The "package" bundle always uses the fixed marketplace folder names as the
# destination; only the *source* folder is configurable (it may be named
# differently, or live in a subfolder). Missing sources are skipped.
PACKAGE_ART = [
    (settings.get("marketingArt", "Marketing Art"), "Marketing Art"),
    (settings.get("storeArt", "Store Art"), "Store Art"),
]

# Obfuscation only affects the bytes written into the distributed artifacts; the
# build output exported to com.mojang is left untouched.
OBFUSCATE_JSON = settings.get("obfuscateJson", False)
OBFUSCATE_SCRIPTS = settings.get("obfuscateScripts", False)
OBFUSCATOR_VERSION = settings.get("obfuscatorVersion", "4")
# Conservative options that keep Minecraft's QuickJS runtime happy.
OBFUSCATOR_ARGS = settings.get(
    "obfuscatorArgs",
    [
        "--compact", "true",
        "--self-defending", "false",
        "--control-flow-flattening", "false",
        "--dead-code-injection", "false",
    ],
)

BP_SRC = os.path.join(os.getcwd(), "BP")
RP_SRC = os.path.join(os.getcwd(), "RP")


def read_manifest(pack_dir):
    manifest_path = os.path.join(pack_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"manifest.json not found in {pack_dir}")
    with open(manifest_path, encoding="utf-8") as fh:
        header = json.load(fh)["header"]
    return {"pack_id": header["uuid"], "version": header["version"]}


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
        with open(VERSION_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


def write_stored_version(v):
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        json.dump({"version": v}, fh, indent=2)


def resolve_version(bp_info):
    """Work out the artifact version and where it came from, in priority order:

      1. static `version` setting
      2. autoVersion: bump the stored version each run (first run seeds from the
         manifest, or from `version` if you set one)
      3. the behavior pack manifest version (the original default)
    """
    manifest_version = version_string(bp_info["version"])

    if VERSION_OVERRIDE:
        return VERSION_OVERRIDE, "version setting"

    if AUTO_VERSION:
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


def add_dir(zf, src_dir, arc_prefix, transform=None):
    """Recursively add a directory to an open ZipFile under ``arc_prefix``.

    If ``transform`` is given it is called with each file path and may return
    replacement bytes (e.g. obfuscated content); returning ``None`` keeps the
    file as-is."""
    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            arc = f"{arc_prefix}/{rel}"
            data = transform(full) if transform else None
            if data is not None:
                zf.writestr(arc, data)
            else:
                zf.write(full, arc)


def _strip_jsonc(text):
    """Remove // and /* */ comments from JSON text (string-aware)."""
    out = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def minify_json(raw):
    """Return minified JSON bytes, or None if the file can't be parsed."""
    text = raw.decode("utf-8-sig")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            obj = json.loads(_strip_jsonc(text))
        except json.JSONDecodeError:
            return None
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


_npx = None


def _find_npx():
    """Locate the npx executable (cached). Raises if scripts must be obfuscated
    but Node is unavailable."""
    global _npx
    if _npx is None:
        _npx = shutil.which("npx") or ""
        if not _npx:
            raise RuntimeError(
                "obfuscateScripts is enabled but 'npx' (Node.js) was not found on PATH."
            )
    return _npx


def obfuscate_js(full_path):
    """Obfuscate a JavaScript file with javascript-obfuscator, returning bytes."""
    npx = _find_npx()
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.js")
        cmd = [
            npx, "--yes", f"javascript-obfuscator@{OBFUSCATOR_VERSION}",
            full_path, "--output", out_path, *OBFUSCATOR_ARGS,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        with open(out_path, "rb") as fh:
            return fh.read()


def pack_transform(full_path):
    """Per-file transform applied to BP/RP contents in the distributed
    artifacts: minify JSON and/or obfuscate JavaScript when enabled."""
    lower = full_path.lower()
    if OBFUSCATE_JSON and lower.endswith(".json"):
        with open(full_path, "rb") as fh:
            return minify_json(fh.read())
    if OBFUSCATE_SCRIPTS and lower.endswith(".js"):
        return obfuscate_js(full_path)
    return None


# Transform passed to add_dir for pack content; None when nothing is enabled.
PACK_TRANSFORM = pack_transform if (OBFUSCATE_JSON or OBFUSCATE_SCRIPTS) else None


def build_addon_zip():
    """Build the BP + RP archive (used for both .zip and .mcaddon)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_dir(zf, BP_SRC, BP_NAME, PACK_TRANSFORM)
        add_dir(zf, RP_SRC, RP_NAME, PACK_TRANSFORM)
    return buffer.getvalue()


def build_package_zip():
    """Build the full marketplace-submission archive: built Content (BP + RP)
    plus the Marketing Art / Store Art folders."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_dir(zf, BP_SRC, f"Content/behavior_packs/{BP_NAME}", PACK_TRANSFORM)
        add_dir(zf, RP_SRC, f"Content/resource_packs/{RP_NAME}", PACK_TRANSFORM)
        for src_rel, dest in PACKAGE_ART:
            src = os.path.join(ROOT_DIR, src_rel)
            if os.path.isdir(src):
                add_dir(zf, src, dest)
            else:
                print(f"[export_addon] skipping missing art folder: {src_rel} -> {dest}")
    return buffer.getvalue()


def _level_dat_nbt_start(raw):
    """Offset of the NBT payload inside a Bedrock ``level.dat``.

    The file normally starts with an 8-byte header (storage-version int +
    payload-length int). It can't be sniffed by the first byte alone: the
    storage version is commonly 10, whose low byte (``0x0a``) collides with the
    NBT ``TAG_Compound`` id, so a first-byte check misfires and parses the
    header as NBT (yielding an empty compound). Trust the header only when its
    declared length matches the remaining bytes."""
    if len(raw) >= HEADER_SIZE:
        declared = struct.unpack_from("<i", raw, 4)[0]
        if declared == len(raw) - HEADER_SIZE:
            return HEADER_SIZE
    return 0


def patch_level_dat(raw, world_name):
    """Best-effort: set LevelName and (optionally) randomize the seed.

    Uses amulet-nbt if available; otherwise returns the data unchanged (the
    world name is still applied via levelname.txt). All other tags in the
    template's level.dat (notably ``lastOpenedWithVersion``, which gates
    features like custom biomes) are preserved untouched."""
    try:
        import amulet_nbt
    except ImportError:
        print("[export_addon] amulet-nbt unavailable; leaving level.dat as-is")
        return raw

    nbt_start = _level_dat_nbt_start(raw)
    # Preserve the template's storage-version header rather than forcing one.
    storage_version = struct.unpack_from("<i", raw, 0)[0] if nbt_start == HEADER_SIZE else 9
    named_tag = amulet_nbt.load(raw[nbt_start:], compressed=False, little_endian=True)
    tag = named_tag.compound

    tag["LevelName"] = amulet_nbt.StringTag(world_name)
    if RANDOMIZE_SEED:
        tag["RandomSeed"] = amulet_nbt.LongTag(random.getrandbits(64) - (1 << 63))

    payload = named_tag.save_to(compressed=False, little_endian=True)
    header = struct.pack("<ii", storage_version, len(payload))
    return header + payload


def build_world(bp_info, rp_info, world_name):
    """Build a .mcworld from the template with both packs installed."""
    if not os.path.isfile(TEMPLATE):
        raise FileNotFoundError(f"Template world not found: {TEMPLATE}")

    with zipfile.ZipFile(TEMPLATE, "r") as src:
        names = src.namelist()
        level_dat = next(
            (n for n in names if n.endswith("level.dat") and not n.startswith("__MACOSX")),
            None,
        )
        if level_dat is None:
            raise ValueError("level.dat not found in template!")
        root_folder = level_dat[: -len("level.dat")] if level_dat != "level.dat" else ""

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as world:
            for info in src.infolist():
                name = info.filename
                if (
                    "LOG" in name
                    or name.startswith("__MACOSX")
                    or "/db/" in name
                    or name.startswith("db/")
                    or name.endswith("/")
                ):
                    continue
                rel = name[len(root_folder):] if root_folder and name.startswith(root_folder) else name
                if not rel or rel in ("world_behavior_packs.json", "world_resource_packs.json"):
                    continue
                data = src.read(name)
                if rel == "level.dat":
                    data = patch_level_dat(data, world_name)
                elif rel == "levelname.txt":
                    data = world_name.encode("utf-8")
                world.writestr(rel, data)

            add_dir(world, BP_SRC, f"behavior_packs/{BP_NAME}", PACK_TRANSFORM)
            add_dir(world, RP_SRC, f"resource_packs/{RP_NAME}", PACK_TRANSFORM)
            world.writestr("world_behavior_packs.json", json.dumps([bp_info], indent=4))
            world.writestr("world_resource_packs.json", json.dumps([rp_info], indent=4))

    return out.getvalue()


def main():
    if not os.path.isdir(BP_SRC) or not os.path.isdir(RP_SRC):
        raise FileNotFoundError("BP and/or RP folder not found in the build output.")

    bp_info = read_manifest(BP_SRC)
    rp_info = read_manifest(RP_SRC)

    version, version_source = resolve_version(bp_info)
    stem = f"{NAME} {VERSION_PREFIX}{version}" if APPEND_VERSION else NAME
    world_name = settings.get("worldName", stem)

    obfuscating = [
        kind
        for kind, on in (("JSON", OBFUSCATE_JSON), ("scripts", OBFUSCATE_SCRIPTS))
        if on
    ]
    if obfuscating:
        print(f"[export_addon] obfuscating {' + '.join(obfuscating)}")

    # Each version's artifacts go in their own subfolder of the output dir,
    # e.g. dist/1.1.9/... (disable with "versionSubfolder": false).
    out_dir = os.path.join(OUTPUT_DIR, f"{VERSION_PREFIX}{version}") if VERSION_SUBFOLDER else OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    outputs = []

    if "zip" in FORMATS or "mcaddon" in FORMATS:
        addon_bytes = build_addon_zip()
        if "zip" in FORMATS:
            path = os.path.join(out_dir, f"{stem}.zip")
            with open(path, "wb") as fh:
                fh.write(addon_bytes)
            outputs.append(path)
        if "mcaddon" in FORMATS:
            path = os.path.join(out_dir, f"{stem}.mcaddon")
            with open(path, "wb") as fh:
                fh.write(addon_bytes)
            outputs.append(path)

    if "mcworld" in FORMATS:
        path = os.path.join(out_dir, f"{stem}.mcworld")
        with open(path, "wb") as fh:
            fh.write(build_world(bp_info, rp_info, world_name))
        outputs.append(path)

    if "package" in FORMATS:
        path = os.path.join(out_dir, f"{stem} Package.zip")
        with open(path, "wb") as fh:
            fh.write(build_package_zip())
        outputs.append(path)

    print(
        f"[export_addon] {NAME} {version} [{version_source}] "
        f"(BP {version_string(bp_info['version'])} / RP {version_string(rp_info['version'])})"
    )
    for out in outputs:
        print(f"[export_addon] wrote {os.path.relpath(out, ROOT_DIR)}")


if __name__ == "__main__":
    main()
