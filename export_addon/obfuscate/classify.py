"""File classification: which pack folders/files may be renamed, moved, or must
stay put, plus small path helpers."""

import os

# Top-level pack folders whose JSON is loaded by scanning + reading identifiers,
# so the filename/subfolder is irrelevant to the game and may be flattened.
CONTENT_LOADED_DIRS = {
    "animations", "animation_controllers", "blocks", "biomes", "entities",
    "entity", "features", "feature_rules", "items", "recipes", "spawn_rules",
    "particles", "render_controllers", "attachables", "models", "fogs",
    "dialogue", "cameras", "block_culling",
}

# Files that MUST keep their exact path (fixed-name config or index files).
FIXED_BASENAMES = {
    "manifest.json", "pack_icon.png", "pack_icon.jpeg", "contents.json",
    "terrain_texture.json", "item_texture.json", "flipbook_textures.json",
    "textures_list.json", "sound_definitions.json", "music_definitions.json",
    "sounds.json", "blocks.json", "biomes_client.json", "languages.json",
    "language_names.json", "_ui_defs.json", "_global_variables.json",
}

TEXT_EXTS = {".json", ".material", ".js", ".mjs", ".cjs", ".mcfunction",
             ".lang", ".molang", ".txt", ".map"}
IMAGE_EXTS = {".png", ".tga", ".jpg", ".jpeg"}
SOUND_EXTS = {".ogg", ".fsb", ".wav"}

TEXTURE_SET_SUFFIX = ".texture_set.json"


def top_segment(rel):
    return rel.replace("\\", "/").split("/", 1)[0]


def splitext_full(name):
    """Split a filename into (stem, ext), treating ``.texture_set.json`` and
    ``.particle.json`` style compound extensions as a single ``.json`` ext."""
    if name.endswith(TEXTURE_SET_SUFFIX):
        return name[: -len(TEXTURE_SET_SUFFIX)], TEXTURE_SET_SUFFIX
    stem, ext = os.path.splitext(name)
    return stem, ext
