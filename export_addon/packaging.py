"""Build the distributable artifacts (.zip / .mcaddon / .mcworld / package).

Reads the built BP/RP folders and writes archives, applying (when enabled) the
identifier/file rename plan, JSON minification and JS obfuscation to the bytes
that go into the artifacts only -- the com.mojang dev install stays readable.
"""

import io
import json
import os
import random
import shutil
import struct
import subprocess
import tempfile
import uuid
import zipfile

import config
import jsonc


def _load_manifest(pack_dir):
    with open(os.path.join(pack_dir, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def read_manifest(pack_dir):
    manifest_path = os.path.join(pack_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"manifest.json not found in {pack_dir}")
    header = _load_manifest(pack_dir)["header"]
    return {"pack_id": header["uuid"], "version": header["version"]}


def _owned_uuids(manifest):
    """UUIDs a pack *owns* (header + modules) -- the ones safe to regenerate.
    Dependency uuids are left out here: cross-pack deps point at another owned
    uuid (so they get remapped by string replacement) and external deps must
    stay untouched."""
    ids = []
    header = manifest.get("header", {}) if isinstance(manifest, dict) else {}
    if isinstance(header.get("uuid"), str):
        ids.append(header["uuid"])
    for m in manifest.get("modules", []) or []:
        if isinstance(m, dict) and isinstance(m.get("uuid"), str):
            ids.append(m["uuid"])
    return ids


def build_uuid_map(pack_dirs):
    """Map every owned uuid in the given packs to a fresh, deterministic uuid
    (uuid5 of the original, so rebuilds and marketplace updates stay stable)."""
    mapping = {}
    for pack_dir in pack_dirs:
        try:
            manifest = _load_manifest(pack_dir)
        except (OSError, ValueError):
            continue
        for old in _owned_uuids(manifest):
            if old not in mapping:
                mapping[old] = str(uuid.uuid5(uuid.NAMESPACE_OID, "export_addon:" + old))
    return mapping


# --- JavaScript obfuscation -------------------------------------------------

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


def obfuscate_js_source(src):
    """Obfuscate JavaScript source bytes with javascript-obfuscator."""
    npx = _find_npx()
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.js")
        out_path = os.path.join(tmp, "out.js")
        with open(in_path, "wb") as fh:
            fh.write(src)
        cmd = [
            npx, "--yes", f"javascript-obfuscator@{config.OBFUSCATOR_VERSION}",
            in_path, "--output", out_path, *config.OBFUSCATOR_ARGS,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        with open(out_path, "rb") as fh:
            return fh.read()


# --- per-file processing + archive assembly ---------------------------------

def add_dir(zf, src_dir, arc_prefix, processor=None):
    """Recursively add a directory to an open ZipFile under ``arc_prefix``.

    If ``processor`` is given it is called with (full_path, rel) and returns
    ``(new_rel, data)``: ``new_rel`` renames the file within the archive and
    ``data`` (bytes, or ``None`` to copy the file verbatim) replaces its
    contents. Without a processor the tree is copied unchanged."""
    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            if processor is not None:
                new_rel, data = processor(full, rel)
            else:
                new_rel, data = rel, None
            arc = f"{arc_prefix}/{new_rel}"
            if data is not None:
                zf.writestr(arc, data)
            else:
                zf.write(full, arc)


def _read_bytes(full_path):
    with open(full_path, "rb") as fh:
        return fh.read()


def _process_bytes(kind, full_path, rel):
    """Content transform for a BP/RP file: identifier/file renaming (PLAN),
    then JSON minification and/or JS obfuscation. Returns bytes, or ``None`` to
    copy the file verbatim."""
    low = rel.lower()
    data = None
    if config.PLAN is not None:
        data = config.PLAN.transform(kind, rel, _read_bytes(full_path))
    if config.OBFUSCATE_JSON and low.endswith(".json"):
        src = data if data is not None else _read_bytes(full_path)
        minified = jsonc.minify_json(src)
        data = minified if minified is not None else src
    elif config.OBFUSCATE_SCRIPTS and low.endswith(".js"):
        src = data if data is not None else _read_bytes(full_path)
        data = obfuscate_js_source(src)
    # Regenerate manifest UUIDs (owned uuids + the cross-pack dependency refs to
    # them). Applied last, after minify, on the final text.
    if config.UUID_MAP and low.endswith("manifest.json"):
        src = data if data is not None else _read_bytes(full_path)
        text = src.decode("utf-8-sig", "replace")
        for old, new in config.UUID_MAP.items():
            text = text.replace(old, new)
        data = text.encode("utf-8")
    return data


def make_processor(kind):
    """An ``add_dir`` processor for pack ``kind`` ('BP'/'RP'): renames the
    archive path (PLAN) and rewrites the bytes. ``None`` when nothing is on."""
    if (config.PLAN is None and not config.UUID_MAP
            and not (config.OBFUSCATE_JSON or config.OBFUSCATE_SCRIPTS)):
        return None

    def processor(full_path, rel):
        new_rel = config.PLAN.out_rel(kind, rel) if config.PLAN is not None else rel
        return new_rel, _process_bytes(kind, full_path, rel)

    return processor


def build_addon_zip():
    """Build the BP + RP archive (used for both .zip and .mcaddon)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_dir(zf, config.BP_SRC, config.BP_NAME, make_processor("BP"))
        add_dir(zf, config.RP_SRC, config.RP_NAME, make_processor("RP"))
    return buffer.getvalue()


def build_package_zip():
    """Build the full marketplace-submission archive: built Content (BP + RP)
    plus the Marketing Art / Store Art folders."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_dir(zf, config.BP_SRC, f"Content/behavior_packs/{config.BP_NAME}", make_processor("BP"))
        add_dir(zf, config.RP_SRC, f"Content/resource_packs/{config.RP_NAME}", make_processor("RP"))
        for src_rel, dest in config.PACKAGE_ART:
            src = os.path.join(config.ROOT_DIR, src_rel)
            if os.path.isdir(src):
                add_dir(zf, src, dest)
            else:
                print(f"[export_addon] skipping missing art folder: {src_rel} -> {dest}")
    return buffer.getvalue()


# --- .mcworld (template + level.dat) ----------------------------------------

def _level_dat_nbt_start(raw):
    """Offset of the NBT payload inside a Bedrock ``level.dat``.

    The file normally starts with an 8-byte header (storage-version int +
    payload-length int). It can't be sniffed by the first byte alone: the
    storage version is commonly 10, whose low byte (``0x0a``) collides with the
    NBT ``TAG_Compound`` id, so a first-byte check misfires and parses the
    header as NBT (yielding an empty compound). Trust the header only when its
    declared length matches the remaining bytes."""
    if len(raw) >= config.HEADER_SIZE:
        declared = struct.unpack_from("<i", raw, 4)[0]
        if declared == len(raw) - config.HEADER_SIZE:
            return config.HEADER_SIZE
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
    storage_version = struct.unpack_from("<i", raw, 0)[0] if nbt_start == config.HEADER_SIZE else 9
    named_tag = amulet_nbt.load(raw[nbt_start:], compressed=False, little_endian=True)
    tag = named_tag.compound

    tag["LevelName"] = amulet_nbt.StringTag(world_name)
    if config.RANDOMIZE_SEED:
        tag["RandomSeed"] = amulet_nbt.LongTag(random.getrandbits(64) - (1 << 63))

    payload = named_tag.save_to(compressed=False, little_endian=True)
    header = struct.pack("<ii", storage_version, len(payload))
    return header + payload


def build_world(bp_info, rp_info, world_name):
    """Build a .mcworld from the template with both packs installed."""
    if not os.path.isfile(config.TEMPLATE):
        raise FileNotFoundError(f"Template world not found: {config.TEMPLATE}")

    with zipfile.ZipFile(config.TEMPLATE, "r") as src:
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

            add_dir(world, config.BP_SRC, f"behavior_packs/{config.BP_NAME}", make_processor("BP"))
            add_dir(world, config.RP_SRC, f"resource_packs/{config.RP_NAME}", make_processor("RP"))
            world.writestr("world_behavior_packs.json", json.dumps([bp_info], indent=4))
            world.writestr("world_resource_packs.json", json.dumps([rp_info], indent=4))

    return out.getvalue()
