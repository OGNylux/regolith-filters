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
| `obfuscatorVersion` | `"4"`                       | `javascript-obfuscator` version run via `npx`. |

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
