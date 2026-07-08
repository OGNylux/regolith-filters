# export_addon

A local [Regolith](https://bedrock-oss.github.io/regolith/) filter that packages
the built addon into ready-to-share artifacts. It runs after the build, reads the
freshly compiled behavior and resource packs, and writes the output files to
`dist/` (configurable).

## Outputs

| Format    | File                  | Contents |
|-----------|-----------------------|----------|
| `zip`     | `<name>.zip`          | The behavior + resource pack, each in its own folder. |
| `mcaddon` | `<name>.mcaddon`      | A byte-for-byte copy of `<name>.zip`, just renamed — double-click to import. |
| `mcworld` | `<name>.mcworld`      | A world (from a bundled template) with both packs installed and registered. |
| `package` | `<name> Package.zip`  | Full marketplace-submission bundle: `Content/{behavior,resource}_packs` plus the `Marketing Art` and `Store Art` folders. |

`<name>` defaults to the project `name` in `config.json` (e.g. `Magic Spells`).

## Install

This filter is published in the shared filter repo
`github.com/ognylux/regolith-filters` (in the `export_addon` subfolder). Add it to
a project with:

```sh
regolith install github.com/ognylux/regolith-filters/export_addon
```

That adds it to `filterDefinitions` in `config.json`:

```jsonc
"filterDefinitions": {
    "export_addon": {
        "url": "github.com/ognylux/regolith-filters",
        "version": "1.0.0"
    }
}
```

To upgrade later: `regolith install --force github.com/ognylux/regolith-filters/export_addon`.

## Usage

Add a profile that runs the build then this filter (see the example settings
below), then:

```sh
regolith install-all   # fetches the filter + its Python deps (first time / CI)
regolith run package   # builds the artifacts into dist/
```

## Configuration

The filter is configured through its `settings` block in `config.json`. Every
setting is optional:

```jsonc
{
    "filter": "export_addon",
    "settings": {
        "outputDir": "dist",
        "obfuscateJson": true,
        "obfuscateScripts": true,
        "obfuscatorArgs": [],
        "formats": ["package", "mcaddon", "zip", "mcworld"]
    }
}
```

| Setting         | Default                          | Description |
|-----------------|----------------------------------|-------------|
| `name`          | `config.json` → `name`           | Base file name for the artifacts. |
| `outputDir`     | `"dist"`                         | Output folder, relative to the project root. |
| `formats`       | `["mcworld", "zip", "mcaddon"]` | Which artifacts to emit: `package`, `mcaddon`, `zip`, `mcworld`. |
| `obfuscateJson` | `false`                          | Minify JSON files (strip whitespace + comments). |
| `obfuscateScripts` | `false`                       | Obfuscate `.js` files with `javascript-obfuscator` (needs Node). |
| `obfuscatorArgs` | conservative MC-safe set        | CLI args passed to `javascript-obfuscator`. |
| `marketingArt`  | `"Marketing Art"`                | Source folder (rel to root) placed into `Marketing Art` in the `package`. Missing → skipped. |
| `storeArt`      | `"Store Art"`                    | Source folder (rel to root) placed into `Store Art` in the `package`. Missing → skipped. |
| `bpName`        | behavior pack folder name        | Folder name used for the BP inside archives. |
| `rpName`        | resource pack folder name        | Folder name used for the RP inside archives. |
| `template`      | bundled `template.mcworld`       | Path to the template world used for `mcworld`, relative to the project root. |
| `worldName`     | versioned file name              | `LevelName` written into the `.mcworld`. |
| `randomizeSeed` | `true`                          | Randomize the world seed when building the `.mcworld`. |
| `appendVersion` | `true`                          | Append the version to the artifact file names (and default world name). |
| `version`       | BP manifest version              | Static version string to pin. Defaults to the behavior pack's `header.version`. |
| `autoVersion`   | `false`                          | Auto-increment the version on every run (see [Versioning](#versioning)). |
| `versionFile`   | `".export_version.json"`         | Where the auto-incrementing version is stored (relative to root). |
| `versionSubfolder` | `true`                        | Write each version's artifacts into its own `dist/<version>/` subfolder. |
| `versionPrefix` | `""`                            | Text placed before the version, e.g. `"v"` → `Magic Spells v1.1.9.mcworld`. |
| `newUuids`      | `false`                          | Give the artifacts fresh BP/RP manifest UUIDs (see [New UUIDs](#new-uuids)). |
| `obfuscatorVersion` | `"4"`                       | `javascript-obfuscator` version run via `npx`. |

### New UUIDs

`"newUuids": true` regenerates the `header` and `module` UUIDs in the BP and RP
`manifest.json` **for the shipped artifacts only** — your `com.mojang` dev
install keeps its original ids. This is useful when the marketplace/dev copy must
not collide with the distributed one.

It's done consistently: the new ids are deterministic (`uuid5` of the original,
so rebuilds and version updates keep the same ids), cross-pack **dependency**
references (BP depending on RP's uuid) are updated to match, `@minecraft/server`
module dependencies are left alone, and the `.mcworld` pack registration uses the
new ids.

### Versioning

With `appendVersion` on (the default), the version is read from the behavior
pack's `manifest.json` (`header.version`) and appended to every artifact:

```
dist/1.1.9/Magic Spells 1.1.9.mcworld
dist/1.1.9/Magic Spells 1.1.9.zip
dist/1.1.9/Magic Spells 1.1.9.mcaddon
dist/1.1.9/Magic Spells 1.1.9 Package.zip
```

Each version's artifacts land in their own `dist/<version>/` subfolder so builds
don't overwrite each other. Set `"versionSubfolder": false` to write them flat
into `dist/` instead.

Set `"versionPrefix": "v"` for `Magic Spells v1.1.9.…`, override the detected
value with `"version": "2.0.0-beta"`, or disable stamping with
`"appendVersion": false`.

The version is resolved in this priority order:

1. **Static pin** — the `version` setting.
2. **Auto-increment** — `autoVersion` (below).
3. **Manifest** — the behavior pack's `header.version` (the default).

#### Auto-incrementing version

Set `"autoVersion": true` and the version's last numeric segment is bumped on
every run (`0.0.1 → 0.0.2 → 0.0.3 …`):

```jsonc
{ "filter": "export_addon", "settings": { "autoVersion": true } }
```

The current value is stored in `.export_version.json` at the project root (path
configurable via `versionFile`); commit it so the counter is shared across
machines/CI. The first run seeds it from the `version` setting if present,
otherwise from the BP manifest. To reset or jump to a specific number, edit that
file (or set `version` for one run).

### Obfuscation

Enable with `"obfuscateJson": true` and/or `"obfuscateScripts": true`.
Obfuscation is applied **only to the bytes written into the distributed
artifacts** — your `com.mojang` dev install stays readable and debuggable.

- **JSON** is minified (whitespace and `//` / `/* */` comments removed). Files
  that can't be parsed are shipped untouched. Key names are kept (the game
  requires them), so this is minification rather than true obfuscation.
- **Scripts** (`.js`) are processed with
  [`javascript-obfuscator`](https://github.com/javascript-obfuscator/javascript-obfuscator)
  via `npx`. The default args are conservative to stay compatible with
  Minecraft's QuickJS runtime (no control-flow-flattening, dead-code-injection,
  or self-defending). `renameGlobals` is left off, so exported/imported names —
  and `@minecraft/server` imports — keep working across files.

```jsonc
{
    "filter": "export_addon",
    "settings": { "obfuscateJson": true, "obfuscateScripts": true }
}
```

> Script obfuscation requires **Node.js** on PATH (already present locally if you
> use esbuild, and provided by `Bedrock-OSS/regolith-action` in CI). If it's
> enabled but `npx` isn't found, the build fails loudly rather than shipping
> readable code.

### Aggressive renaming (identifiers & files)

Beyond minifying, the filter can rename identifiers and files across the whole
addon and rewrite every reference (in BP, RP **and** scripts) so the pack still
works. **`obfuscateJson` is the master switch** (like `obfuscateScripts` is for
JS): turn it on and every pass below defaults to on. Disable a pass with
`"renameTextures": false`, or list several to deactivate in **`jsonObfuscatorArgs`**
(the JSON analogue of `obfuscatorArgs`) using short names:

```jsonc
"obfuscateJson": true,
"jsonObfuscatorArgs": [ "textures", "structures", "lootTables" ]  // these OFF, rest ON
```

Each pass:

| Setting | Renames | References updated |
|---------|---------|--------------------|
| `renameAnimations` ⚠️ | `animation.*` ids | client entities, animate scripts, controllers |
| `renameAnimationControllers` | `controller.animation.*` ids **+ state names** | client entities; states' `initial_state` + `transitions` |
| `renameParticles` ⚠️ | particle `ns:name` ids | client entities, animations, `.js`, `.mcfunction` |
| `renameComponentGroups` | BP entity `component_groups` | the entity's own `events` |
| `renameAnimationKeys` ⚠️ | RP client-entity animation short-keys | `scripts.animate` + animation controllers |
| `renameGeometry` | `geometry.*` ids | client entities, attachables, block `minecraft:geometry` |
| `renameRenderControllers` | `controller.render.*` ids | client-entity `render_controllers` |
| `renameSounds` | `.ogg`/`.fsb` **files** (not event ids) | `sound_definitions.json` paths |

> ⚠️ **`renameAnimations`, `renameParticles`, and `renameAnimationKeys` are OFF
> by default** — even with `obfuscateJson: true`. These ids/keys are commonly
> referenced from scripts (`spawnParticle` / `playAnimation`, often by the
> client-entity short-key name), sometimes built dynamically (`"cyd_ab.mob." +
> type`), which a text rewriter can't follow. Opt in with an explicit
> `"renameAnimationKeys": true` only if you're sure your scripts use literal
> names. `renameSounds` renames only the `.ogg` **files** (their paths live only in
> `sound_definitions.json`, never scripts), so it's reliable and stays on — sound
> *event ids* are never touched.
| `renameFiles` | content-loaded definition files (entities, blocks, items, recipes, models, particles, feature_rules, block_culling, …) get short random names + flattened | n/a — the game loads these by identifier, not path |
| `renameTextures` | texture files + their texture_set (detected by content, incl. plain-`.json`) | `terrain_texture` / `item_texture` / `flipbook`, client entities, attachables, particles, and the texture_set's `color`/`mer`/`normal` |
| `renameStructures` | `.mcstructure` files | the derived `ns:path` identifiers in features / functions / scripts |
| `renameLootTables` | `loot_tables/*.json` | every `"loot_tables/…"` reference |

**Folder handling.** By default files **keep their existing folder** — only the
filename is randomized. No config needed, and paths stay short because the long
part was always the filename:

```
textures/cyd/ab/blocks/regular/dim/shattered_abyss_floor_tile_0.png   (80)
  -> textures/cyd/ab/blocks/regular/dim/a3f2.png                       (56)
```

If you'd rather also hide your folder layout, set `"flatten": true`. Then files
keep their top folder plus any leading **namespace** segments and drop everything
after; a path with no namespace collapses to just its top folder. The namespace
is **auto-detected** from the pack's identifiers (`cyd_ab:…` → keeps `cyd`, `ab`,
`cyd_ab`), so no config is needed — override with `namespaceDirs` if you must:

`textures` and `models` (`categoryDirs`) keep **one extra level** — the category
(`blocks`/`entity`/`items`) — then flatten deeper. `keepStructureDirs` (default
none) keep their full structure instead.

```
(flatten)  sounds/cyd/ab/all_biomes/foo.ogg            -> sounds/cyd/ab/9790.ogg
(flatten)  structures/cyd_ab/boneyard/foo.mcstructure  -> structures/cyd_ab/2b01.mcstructure
(flatten)  entity/boss/foo.json                        -> entity/54f5.json
(category) textures/cyd/ab/blocks/regular/dim/foo.png  -> textures/cyd/ab/blocks/a3f2.png
(category) models/blocks/boneyard/foo.geo.json         -> models/blocks/c4b2.json
```

Either way, each `.texture_set.json` keeps its texture's new name in the same
folder, structure identifiers stay valid, and folders no pass targets (e.g.
`worldgen`) are left untouched.

Extra knobs: `maxPathLength` (default `80`, the pack-relative path budget Bedrock
enforces) and `strictPaths` (default `false` — set `true` to **fail the build**
if any path exceeds the budget instead of just warning).

```jsonc
{
    "filter": "export_addon",
    "settings": {
        "obfuscateJson": true,
        "renameAnimations": true,
        "renameAnimationControllers": true,
        "renameParticles": true,
        "renameComponentGroups": true,
        "renameAnimationKeys": true,
        "renameFiles": true
    }
}
```

**Safety model:**

- Only identifiers **defined inside the pack** are renamed; references to vanilla
  or dependency ids (e.g. `textures/misc/enchanted_item_glint`,
  `loot_tables/entities/skeleton.json`, `animation.humanoid.*`) are left
  untouched. The build log reports how many external refs it skipped.
- Renames are **deterministic** (hash-based), so rebuilds are stable and diffs
  stay small.
- Renaming also **shortens paths**, which helps stay under the 80-char limit.

> ⚠️ The three path-referenced passes — `renameTextures`, `renameStructures`,
> `renameLootTables` — are the highest-risk (they move assets and rewrite paths
> across many reference systems). They are **not** required to satisfy the path
> limit. Enable them one at a time and **test the built pack in-game** before
> shipping. The build prints a coverage report and, with `strictPaths`, refuses
> to emit an over-length path. You can preview the whole plan without building
> (run from the filter directory so `obfuscate` and `jsonc` are importable):
>
> ```sh
> cd .regolith/cache/filters/export_addon
> python -m obfuscate <BP_dir> <RP_dir> --all
> ```

## How it works

- `zip` / `mcaddon` archive the built `BP` and `RP` folders directly.
- `mcworld` opens the bundled `template.mcworld`, sets the level name (and seed),
  copies the packs into `behavior_packs/` and `resource_packs/`, and regenerates
  `world_behavior_packs.json` / `world_resource_packs.json` from the live manifest
  UUIDs and versions.
- `package` rebuilds the `Content/` tree from the built packs and appends the art
  folders for marketplace submission. The destinations are always `Marketing Art`
  and `Store Art`; only the *source* folders are configurable (`marketingArt` /
  `storeArt`).

## Dependencies

- Python (provided via Regolith's `python` runner).
- [`amulet-nbt`](https://pypi.org/project/amulet-nbt/) — used to edit
  `level.dat`. Listed in `requirements.txt` and installed automatically by
  Regolith. If it is ever unavailable, the export still succeeds and the world
  name falls back to `levelname.txt`.
- Node.js + `npx` — **only** when `obfuscateScripts` is enabled (for
  `javascript-obfuscator`). Not needed otherwise.
