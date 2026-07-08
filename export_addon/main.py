"""Regolith filter: export the built addon as .mcworld, .zip, .mcaddon and package.

Runs after the build, from inside ``.regolith/tmp`` (which contains ``BP/``,
``RP/`` and ``data/``). It reads the freshly built packs and writes the
packaged artifacts to ``<ROOT_DIR>/<outputDir>``.

    zip       -> "<name>.zip": the behavior + resource pack (each in its own folder)
    mcaddon   -> "<name>.mcaddon": a byte-for-byte copy of the .zip, just renamed
    mcworld   -> "<name>.mcworld": a world (from a template) with the packs installed
    package   -> "<name> Package.zip": the full marketplace-submission bundle
                 (Content/{behavior,resource}_packs + Marketing Art + Store Art)

This file is the entry point / orchestration. The rest lives in sibling modules:
    config.py      settings parsing + derived constants
    versioning.py  version resolution
    packaging.py   archive assembly (.zip/.mcaddon/.mcworld/package) + level.dat
    obfuscate.py   identifier/file renaming engine
    jsonc.py       JSON-with-comments helpers

Settings (all optional, passed as a JSON string argument by Regolith):
    name             base file name                (default: config.json "name")
    outputDir        output folder (rel to root)   (default: "dist")
    formats          list of formats to emit       (default: mcworld, zip, mcaddon)
    obfuscateJson    minify JSON + enable all rename passes (default: False)
    jsonObfuscatorArgs rename passes to DISABLE, e.g. ["textures","structures"]
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
    newUuids         regenerate BP/RP manifest UUIDs (default: False)
    version          static version string to pin  (default: BP manifest version)
    autoVersion      auto-increment each run        (default: False)
    versionFile      where the auto version is kept (default: ".export_version.json")
    versionSubfolder artifacts go in dist/<version> (default: True)
    versionPrefix    text before the version       (default: "", e.g. "v")
    obfuscatorVersion javascript-obfuscator ver    (default: "4")

Aggressive renaming (each an independent on/off arg that DEFAULTS to the value
of "obfuscateJson" -- so obfuscateJson:true turns them all on. Disable a pass
with renameX:false, or list several in "jsonObfuscatorArgs" (short names like
"textures", "structures"). Only identifiers *defined in the pack* are ever
renamed, and every reference in BP, RP and scripts is rewritten to match -- see
obfuscate.py):
    renameAnimations            animation.* ids  (OFF by default -- see note)
    renameAnimationControllers  controller.animation.* ids + AC state names
    renameParticles             particle "ns:name" ids  (OFF by default)
    renameComponentGroups       BP entity component_groups (+ event refs)
    renameAnimationKeys         RP client-entity animation short-keys  (OFF by default)
    renameGeometry              geometry.* ids (+ client entity / block refs)
    renameRenderControllers     controller.render.* ids
    renameSounds                .ogg files + sound_definitions paths (event ids
                                are NOT touched -- reliable, on by default)

renameAnimations / renameParticles / renameAnimationKeys are OFF even when
obfuscateJson is on: those ids/keys are commonly referenced from scripts
(playAnimation / spawnParticle), sometimes built dynamically, so renaming them
can't be done reliably. Opt in with an explicit renameX:true only if your scripts
use literal names. renameSounds renames only the .ogg files (whose paths live in
sound_definitions.json), which is reliable, so it stays on.
    renameFiles                 flatten + rename content-loaded definition files
    renameTextures              textures + .texture_set.json + all texture refs
    renameStructures            .mcstructure files + their derived identifiers
    renameLootTables            loot_tables/*.json + all "loot_tables/..." refs
    flatten          collapse folders instead of keeping   (default: False)
    namespaceDirs    (flatten) segments to keep; auto-detected if omitted
    categoryDirs     (flatten) top folders that keep one category level
                     (default: ["textures", "models"])
    keepStructureDirs (flatten) top folders that keep FULL structure (default: none)
    maxPathLength    pack-relative path budget             (default: 80)
    strictPaths      fail build if a path is over          (default: False)

By default renamed files keep their existing folder and only the filename is
randomized (short names keep paths short with no config). Set flatten:true to
keep the top folder + any leading namespace segments and drop everything after
(paths with no namespace collapse to their top folder). The namespace is
auto-detected from the pack's identifiers ("cyd_ab" -> keeps cyd/ab/cyd_ab)
unless namespaceDirs is set. Top folders in categoryDirs (textures, models) keep
one extra level -- the category (blocks/entity/items) -- then flatten deeper;
keepStructureDirs keep their full structure. Folders no pass targets (e.g.
worldgen) are left untouched either way.

Version resolution (highest priority first): the static `version` setting,
autoVersion (bump the stored version), then the BP manifest version.

Obfuscation is applied only to the bytes written into the artifacts; the build
output exported to com.mojang is left readable.
"""

import os

import config
import obfuscate
import packaging
from versioning import resolve_version, version_string


def build_rename_plan():
    """Scan BP + RP, build the identifier/file rename plan, and report it.

    Sets ``config.PLAN``. Path lengths are validated pack-relative (what Bedrock
    enforces); with "strictPaths" a path over the limit fails the build instead
    of just warning."""
    opt = config.OBF_OPTIONS
    if not opt.enabled:
        return
    config.PLAN = obfuscate.Plan([("BP", config.BP_SRC), ("RP", config.RP_SRC)], opt)
    plan = config.PLAN

    if opt.flatten and plan.namespace:
        print(f"[export_addon] flatten keeping namespace '{plan.namespace}' "
              f"(folders: {', '.join(sorted(opt.namespace_dirs))})")

    s = plan.summary()
    print(
        "[export_addon] renaming "
        f"{s['animations']} anim / {s['animation_controllers']} ac / "
        f"{s['particles']} particle / {s['geometry']} geo / "
        f"{s['render_controllers']} rc / {s['sound_files']} sound-file / "
        f"{s['short_keys']} anim-key / {s['structure_ids']} structure ids, "
        f"{s['files_moved']} files"
    )

    problems = plan.validate()
    over = [p for p in problems if p.startswith("path >")]
    external = [p for p in problems if not p.startswith("path >")]
    if external:
        print(f"[export_addon] {len(external)} external refs left as-is "
              "(assumed vanilla / dependency)")
    for p in over[:10]:
        print(f"[export_addon] WARNING {p}")
    if over and opt.strict:
        raise RuntimeError(
            f"{len(over)} path(s) exceed {opt.max_path} chars (strictPaths is on)"
        )


def main():
    if not os.path.isdir(config.BP_SRC) or not os.path.isdir(config.RP_SRC):
        raise FileNotFoundError("BP and/or RP folder not found in the build output.")

    bp_info = packaging.read_manifest(config.BP_SRC)
    rp_info = packaging.read_manifest(config.RP_SRC)

    if config.NEW_UUIDS:
        config.UUID_MAP = packaging.build_uuid_map([config.BP_SRC, config.RP_SRC])
        # the .mcworld registers packs by header uuid -- use the new ones
        bp_info["pack_id"] = config.UUID_MAP.get(bp_info["pack_id"], bp_info["pack_id"])
        rp_info["pack_id"] = config.UUID_MAP.get(rp_info["pack_id"], rp_info["pack_id"])
        print(f"[export_addon] regenerating {len(config.UUID_MAP)} manifest UUID(s)")

    version, version_source = resolve_version(bp_info)
    stem = f"{config.NAME} {config.VERSION_PREFIX}{version}" if config.APPEND_VERSION else config.NAME
    world_name = config.settings.get("worldName", stem)

    obfuscating = [
        kind
        for kind, on in (("JSON", config.OBFUSCATE_JSON), ("scripts", config.OBFUSCATE_SCRIPTS))
        if on
    ]
    if obfuscating:
        print(f"[export_addon] obfuscating {' + '.join(obfuscating)}")

    build_rename_plan()

    # Each version's artifacts go in their own subfolder of the output dir,
    # e.g. dist/1.1.9/... (disable with "versionSubfolder": false).
    out_dir = (os.path.join(config.OUTPUT_DIR, f"{config.VERSION_PREFIX}{version}")
               if config.VERSION_SUBFOLDER else config.OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    outputs = []

    if "zip" in config.FORMATS or "mcaddon" in config.FORMATS:
        addon_bytes = packaging.build_addon_zip()
        if "zip" in config.FORMATS:
            path = os.path.join(out_dir, f"{stem}.zip")
            with open(path, "wb") as fh:
                fh.write(addon_bytes)
            outputs.append(path)
        if "mcaddon" in config.FORMATS:
            path = os.path.join(out_dir, f"{stem}.mcaddon")
            with open(path, "wb") as fh:
                fh.write(addon_bytes)
            outputs.append(path)

    if "mcworld" in config.FORMATS:
        path = os.path.join(out_dir, f"{stem}.mcworld")
        with open(path, "wb") as fh:
            fh.write(packaging.build_world(bp_info, rp_info, world_name))
        outputs.append(path)

    if "package" in config.FORMATS:
        path = os.path.join(out_dir, f"{stem} Package.zip")
        with open(path, "wb") as fh:
            fh.write(packaging.build_package_zip())
        outputs.append(path)

    print(
        f"[export_addon] {config.NAME} {version} [{version_source}] "
        f"(BP {version_string(bp_info['version'])} / RP {version_string(rp_info['version'])})"
    )
    for out in outputs:
        print(f"[export_addon] wrote {os.path.relpath(out, config.ROOT_DIR)}")


if __name__ == "__main__":
    main()
