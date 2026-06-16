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
| `project` | `<name> Project.zip`  | Full marketplace-submission bundle: `Content/{behavior,resource}_packs` plus the `Marketing Art` and `Store Art` folders. |

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
        "randomizeSeed": true,
        "formats": ["mcworld", "zip", "mcaddon", "project"]
    }
}
```

| Setting         | Default                          | Description |
|-----------------|----------------------------------|-------------|
| `name`          | `config.json` → `name`           | Base file name for the artifacts. |
| `outputDir`     | `"dist"`                         | Output folder, relative to the project root. |
| `formats`       | `["mcworld", "zip", "mcaddon"]` | Which artifacts to emit. |
| `bpName`        | behavior pack folder name        | Folder name used for the BP inside archives. |
| `rpName`        | resource pack folder name        | Folder name used for the RP inside archives. |
| `projectDirs`   | `["Marketing Art", "Store Art"]`| Extra top-level folders added to the `project` bundle (missing ones are skipped). |
| `template`      | bundled `template.mcworld`       | Path to the template world used for `mcworld`, relative to the project root. |
| `worldName`     | `name`                          | `LevelName` written into the `.mcworld`. |
| `randomizeSeed` | `true`                          | Randomize the world seed when building the `.mcworld`. |

## How it works

- `zip` / `mcaddon` archive the built `BP` and `RP` folders directly.
- `mcworld` opens the bundled `template.mcworld`, sets the level name (and seed),
  copies the packs into `behavior_packs/` and `resource_packs/`, and regenerates
  `world_behavior_packs.json` / `world_resource_packs.json` from the live manifest
  UUIDs and versions.
- `project` rebuilds the `Content/` tree from the built packs and appends the art
  folders for marketplace submission.

## Dependencies

- Python (provided via Regolith's `python` runner).
- [`amulet-nbt`](https://pypi.org/project/amulet-nbt/) — used to edit
  `level.dat`. Listed in `requirements.txt` and installed automatically by
  Regolith. If it is ever unavailable, the export still succeeds and the world
  name falls back to `levelname.txt`.
