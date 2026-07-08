"""Settings parsing and derived configuration for the export_addon filter.

Regolith passes the filter's ``settings`` block as a JSON string in argv[1].
Every value below is resolved once at import time and shared by the other
modules. ``PLAN`` is the exception: it is filled in at runtime by
``main.build_rename_plan()``.
"""

import json
import os
import sys

import obfuscate

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

# Aggressive, reference-safe identifier/file renaming (see obfuscate.py). PLAN is
# built once at runtime by main.build_rename_plan(); modules read config.PLAN.
OBF_OPTIONS = obfuscate.Options(settings)
PLAN = None

# Regenerate the BP + RP manifest UUIDs (header + modules) for the artifacts, so
# the shipped addon has different ids from the dev install. UUID_MAP (old -> new)
# is built once at runtime by main(); modules read config.UUID_MAP.
NEW_UUIDS = settings.get("newUuids", False)
UUID_MAP = {}

BP_SRC = os.path.join(os.getcwd(), "BP")
RP_SRC = os.path.join(os.getcwd(), "RP")
