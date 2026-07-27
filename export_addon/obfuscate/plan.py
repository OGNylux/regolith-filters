"""The Plan: scans the built packs, builds the rename maps, and rewrites bytes.

A single :class:`Plan` holds every map (id renames + per-pack path renames) and
exposes :meth:`out_rel` (new archive path for a file) and :meth:`transform` (new
bytes for a file). It is built once from the ``(kind, root)`` pack list.
"""

import json
import os
import re

from jsonc import try_load_json

from .classify import (
    CONTENT_LOADED_DIRS, FIXED_BASENAMES, IMAGE_EXTS, SOUND_EXTS, TEXT_EXTS,
    TEXTURE_SET_SUFFIX, splitext_full, top_segment,
)
from .names import make_token_replacer, unique_name


class Plan:
    def __init__(self, packs, options):
        """``packs`` is a list of (kind, root_dir) where kind is 'BP' or 'RP'."""
        self.packs = packs
        self.opt = options
        self.warnings = []

        # global identifier maps (ids live in shared namespaces across BP+RP)
        self.anim = {}          # animation.* -> animation.*
        self.anim_ctrl = {}     # controller.animation.* -> ...
        self.particle = {}      # ns:name -> ns:name
        self.structure_id = {}  # ns:subpath -> ns:subpath
        self.short_key = {}     # client-entity animation short-key -> short-key
        self.geometry = {}      # geometry.* -> geometry.*
        self.render_ctrl = {}   # controller.render.* -> controller.render.*

        # per-pack path maps: (kind) -> { old_rel -> new_rel }
        self.paths = {kind: {} for kind, _ in packs}
        # texture/sound no-ext maps (refs are paths without extension):
        self.tex_noext = {kind: {} for kind, _ in packs}
        self.sound_noext = {kind: {} for kind, _ in packs}

        self._used_names = {}   # (kind, bucket) -> set
        self._all_files = {kind: [] for kind, _ in packs}  # rel paths
        self._ns_counts = {}    # identifier namespace -> count (for auto-detect)
        self.namespace = None   # auto-detected namespace, e.g. "cyd_ab"

        self._scan()
        # Detect the addon's identifier namespace (e.g. "cyd_ab"). Used to keep
        # renamed ids namespaced, and -- when flattening -- to keep the namespace
        # folders (cyd_ab -> cyd/ab/cyd_ab).
        if self._ns_counts:
            self.namespace = max(self._ns_counts, key=self._ns_counts.get)
        if self.opt.flatten and not self.opt.namespace_dirs and self.namespace:
            self.opt.namespace_dirs = ({self.namespace}
                                       | {p for p in self.namespace.split("_") if p})
        self._build_ids()
        self._build_paths()
        self._compile()

    def _note_ns(self, ident):
        if isinstance(ident, str) and ":" in ident:
            ns = ident.split(":", 1)[0]
            if ns and ns != "minecraft":
                self._ns_counts[ns] = self._ns_counts.get(ns, 0) + 1

    # -- scanning -----------------------------------------------------------

    def _iter_files(self, root):
        for base, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(base, f)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                yield rel, full

    def _scan(self):
        self._defs = {"anim": set(), "ac": set(), "particle": set(),
                      "short": set(), "geo": set(), "render": set()}
        for kind, root in self.packs:
            for rel, full in self._iter_files(root):
                self._all_files[kind].append(rel)
                top = top_segment(rel)
                if not rel.endswith(".json"):
                    continue
                if top not in ("animations", "animation_controllers",
                               "particles", "entity", "attachables", "models",
                               "render_controllers"):
                    continue
                obj = try_load_json(self._read_text(full))
                if not isinstance(obj, dict):
                    continue
                if top == "animations":
                    self._defs["anim"].update(
                        (obj.get("animations") or {}).keys())
                elif top == "animation_controllers":
                    self._defs["ac"].update(
                        (obj.get("animation_controllers") or {}).keys())
                elif top == "render_controllers":
                    self._defs["render"].update(
                        (obj.get("render_controllers") or {}).keys())
                elif top == "particles":
                    ident = (obj.get("particle_effect", {})
                             .get("description", {}).get("identifier"))
                    if ident:
                        self._defs["particle"].add(ident)
                        self._note_ns(ident)
                elif top == "models":
                    for g in (obj.get("minecraft:geometry") or []):
                        ident = (g or {}).get("description", {}).get("identifier")
                        if ident:
                            self._defs["geo"].add(ident)
                    for k in obj:  # legacy top-level "geometry.name" form
                        if isinstance(k, str) and k.startswith("geometry."):
                            self._defs["geo"].add(k)
                elif top in ("entity", "attachables") and kind == "RP":
                    desc = self._client_desc(obj)
                    if desc:
                        self._defs["short"].update(
                            (desc.get("animations") or {}).keys())
                        self._note_ns(desc.get("identifier"))

    @staticmethod
    def _client_desc(obj):
        for key in ("minecraft:client_entity", "minecraft:attachable"):
            if key in obj:
                return obj[key].get("description", {})
        return None

    @staticmethod
    def _read_text(full):
        with open(full, "rb") as fh:
            return fh.read().decode("utf-8-sig", "replace")

    # -- id maps ------------------------------------------------------------

    def _build_ids(self):
        opt = self.opt
        used = set()
        if opt.renameAnimations:
            for old in sorted(self._defs["anim"]):
                self.anim[old] = self._anim_like(old, "animation.", ".", used)
        if opt.renameAnimationControllers:
            for old in sorted(self._defs["ac"]):
                self.anim_ctrl[old] = self._anim_like(
                    old, "controller.animation.", ".", used)
        if opt.renameParticles:
            for old in sorted(self._defs["particle"]):
                self.particle[old] = self._ns_like(old, used)
        if opt.renameAnimationKeys:
            kused = set()
            for old in sorted(self._defs["short"]):
                self.short_key[old] = unique_name("sk\0" + old, kused, 3)
        if opt.renameGeometry:
            for old in sorted(self._defs["geo"]):
                self.geometry[old] = self._anim_like(old, "geometry.", "_", used)
        if opt.renameRenderControllers:
            for old in sorted(self._defs["render"]):
                self.render_ctrl[old] = self._anim_like(
                    old, "controller.render.", ".", used)

    def _anim_like(self, old, prefix, sep, used):
        """Rename to <prefix><namespace><sep><hash>, so every renamed id stays
        inside the addon's namespace (e.g. controller.animation.cyd_ab.<hash>,
        geometry.cyd_ab_<hash>) regardless of how the original was namespaced.
        Falls back to <prefix><hash> if no namespace was detected."""
        if self.namespace:
            return prefix + self.namespace + sep + unique_name(old, used, 4)
        return prefix + unique_name(old, used, 4)

    @staticmethod
    def _ns_like(old, used):
        ns = old.split(":", 1)[0] if ":" in old else "p"
        return ns + ":" + unique_name(old, used, 4)

    # -- path maps ----------------------------------------------------------

    def _new_rel(self, kind, bucket, stem_seed, ext):
        used = self._used_names.setdefault((kind, bucket), set())
        name = unique_name(kind + "\0" + bucket + "\0" + stem_seed, used, 4)
        return "%s/%s%s" % (bucket, name, ext) if bucket else name + ext

    def _bucket(self, rel):
        """Where a renamed file lands. By default it keeps its existing folder
        (only the filename changes). With ``flatten`` on, it keeps the top folder
        plus any leading namespace segments (and, for ``category_dirs``, one more
        level -- the category) and drops everything after."""
        dirs = rel.split("/")[:-1]  # drop the filename
        if not dirs:
            return ""
        if not self.opt.flatten or dirs[0] in self.opt.keep_structure_dirs:
            return "/".join(dirs)   # keep the file's existing folder
        keep = [dirs[0]]
        i = 1
        while i < len(dirs) and dirs[i] in self.opt.namespace_dirs:
            keep.append(dirs[i])
            i += 1
        if dirs[0] in self.opt.category_dirs and i < len(dirs):
            keep.append(dirs[i])   # keep the category level (e.g. textures/.../blocks)
        return "/".join(keep)

    def _build_paths(self):
        opt = self.opt
        for kind, root in self.packs:
            texture_sets = {}   # base_noext_rel -> texture_set rel
            images = []         # (rel, noext_rel, ext)
            sounds = []         # (rel, noext_rel, ext)
            for rel in self._all_files[kind]:
                top = top_segment(rel)
                base = rel.rsplit("/", 1)[-1]
                if base in FIXED_BASENAMES:
                    continue
                # dynamically-referenced assets: keep name so runtime-built refs resolve
                if any(rel.startswith(kp) for kp in opt.keep_paths):
                    continue

                # textures ------------------------------------------------
                if opt.renameTextures and top == "textures":
                    if rel.endswith(TEXTURE_SET_SUFFIX):
                        texture_sets[rel[: -len(TEXTURE_SET_SUFFIX)]] = (rel, TEXTURE_SET_SUFFIX)
                        continue
                    _, ext = splitext_full(base)
                    if ext in IMAGE_EXTS:
                        images.append((rel, rel[: -len(ext)], ext))
                    elif ext == ".json":
                        # a texture_set not named *.texture_set.json -- detect it
                        # by content so its base texture / MER / normal stay in sync
                        obj = try_load_json(self._read_text(self._full(root, rel)))
                        if isinstance(obj, dict) and "minecraft:texture_set" in obj:
                            texture_sets[rel[: -len(".json")]] = (rel, ".json")
                    continue

                # sounds (files only -- .ogg refs live in sound_definitions) -
                if opt.renameSounds and top == "sounds":
                    _, ext = splitext_full(base)
                    if ext in SOUND_EXTS:
                        sounds.append((rel, rel[: -len(ext)], ext))
                    continue

                # structures ---------------------------------------------
                if opt.renameStructures and top == "structures" and rel.endswith(".mcstructure"):
                    # Structures are referenced by their path under structures/
                    # (no extension) in two forms: "ns/sub/..." (jigsaw
                    # template-pool `location`) and "ns:sub/..." (features,
                    # /structure). Keep the namespace folder so both stay valid,
                    # and map both forms so every reference is rewritten.
                    if opt.flatten:
                        parts = rel.split("/")
                        bucket = "structures/" + parts[1] if len(parts) > 2 else "structures"
                    else:
                        bucket = self._bucket(rel)
                    new_rel = self._new_rel(kind, bucket, rel, ".mcstructure")
                    self.paths[kind][rel] = new_rel
                    old_body = rel[len("structures/"):-len(".mcstructure")]
                    new_body = new_rel[len("structures/"):-len(".mcstructure")]
                    if "/" in old_body and "/" in new_body:
                        self.structure_id[old_body] = new_body                    # ns/sub (jigsaw)
                        self.structure_id[old_body.replace("/", ":", 1)] = \
                            new_body.replace("/", ":", 1)                         # ns:sub (features)
                    continue

                # loot tables --------------------------------------------
                if opt.renameLootTables and top == "loot_tables" and rel.endswith(".json"):
                    self.paths[kind][rel] = self._new_rel(kind, self._bucket(rel), rel, ".json")
                    continue

                # content-loaded definition files ------------------------
                if opt.renameFiles and top in CONTENT_LOADED_DIRS and rel.endswith(".json"):
                    self.paths[kind][rel] = self._new_rel(kind, self._bucket(rel), rel, ".json")
                    continue

            # resolve textures together with their MER/normal + texture_set
            if opt.renameTextures:
                self._map_textures(kind, images, texture_sets)
            # relocate sound files (refs rewritten via the sound_noext map)
            for rel, noext, ext in sounds:
                new_rel = self._new_rel(kind, self._bucket(rel), rel, ext)
                self.paths[kind][rel] = new_rel
                self.sound_noext[kind][noext] = new_rel[: -len(ext)]

    def _map_textures(self, kind, images, texture_sets):
        # every image (colour, _mer, _normal, ...) gets a fresh name in its bucket
        for rel, noext, ext in images:
            new_rel = self._new_rel(kind, self._bucket(rel), rel, ext)
            self.paths[kind][rel] = new_rel
            self.tex_noext[kind][noext] = new_rel[: -len(ext)]
        # a texture_set must share its colour texture's new stem + folder; keep
        # whatever suffix it had (.texture_set.json or plain .json)
        for base_noext, (ts_rel, suffix) in texture_sets.items():
            new_noext = self.tex_noext[kind].get(base_noext)
            if new_noext is None:
                # texture_set without a matching image next to it: give it its own name
                new_noext = self._new_rel(kind, self._bucket(ts_rel), ts_rel, "")
                self.tex_noext[kind][base_noext] = new_noext
            self.paths[kind][ts_rel] = new_noext + suffix

    # -- compiled replacers -------------------------------------------------

    def _compile(self):
        idc = "A-Za-z0-9_."
        self._id_replacers = []
        for m in (self.anim, self.anim_ctrl, self.geometry, self.render_ctrl):
            if m:
                self._id_replacers.append(make_token_replacer(m, idc, idc))
        if self.particle:
            self._id_replacers.append(
                make_token_replacer(self.particle, idc + ":", idc))
        if self.structure_id:
            self._id_replacers.append(
                make_token_replacer(self.structure_id, idc + ":/", idc + "/"))
        # Global path replacer (texture + sound paths with/without ext, plus loot
        # paths -- matched as whole path tokens). It must span BOTH packs: a BP
        # script or JSON commonly references an RP texture/sound path (e.g.
        # server-ui form icons), so per-pack maps would miss those. Keys are
        # unique across packs (textures/sounds live in RP, loot_tables in BP), so
        # merging cannot collide.
        pathc = r"A-Za-z0-9_./"
        pathmap = {}
        for kind, _ in self.packs:
            pathmap.update(self.tex_noext[kind])       # "textures/x" -> "textures/y"
            pathmap.update(self.sound_noext[kind])     # "sounds/x"   -> "sounds/y"
            for o, n in self.paths[kind].items():      # add the with-extension forms
                top = top_segment(o)
                if top in ("textures", "sounds"):
                    _, ext = splitext_full(o.rsplit("/", 1)[-1])
                    if ext in IMAGE_EXTS or ext in SOUND_EXTS:
                        pathmap[o] = n
                elif top == "loot_tables":
                    pathmap[o] = n
        self._path_replacer = make_token_replacer(pathmap, pathc, pathc)

    # -- public: relocate + transform --------------------------------------

    def out_rel(self, kind, rel):
        return self.paths[kind].get(rel, rel)

    def transform(self, kind, rel, raw):
        """Return the (possibly rewritten) bytes for a file, or ``raw``."""
        low = rel.lower()
        is_json = low.endswith(".json")  # incl. compound .texture_set.json etc.
        if not (is_json or any(low.endswith(e) for e in TEXT_EXTS)):
            return raw  # binary: relocated only
        text = raw.decode("utf-8-sig", "replace")

        # structural JSON edits (component groups, short-keys, texture_set) -
        if is_json:
            obj = try_load_json(text)
            if isinstance(obj, dict) and self._structural(kind, rel, obj):
                text = json.dumps(obj, ensure_ascii=False, indent=2)

        # textual identifier + path rewrites (both global / cross-pack) ---
        for rep in self._id_replacers:
            text = rep(text)
        text = self._path_replacer(text)

        return text.encode("utf-8")

    def _structural(self, kind, rel, obj):
        changed = False
        top = top_segment(rel)
        if self.opt.renameComponentGroups and kind == "BP" and "minecraft:entity" in obj:
            changed |= self._rename_component_groups(obj["minecraft:entity"], rel)
        if top == "animation_controllers":
            if self.opt.renameAnimationControllers:
                changed |= self._rename_ac_states(obj)
            if self.opt.renameAnimationKeys and kind == "RP":
                changed |= self._remap_controller_anims(obj)
        if self.opt.renameAnimationKeys and kind == "RP" and top in ("entity", "attachables"):
            desc = self._client_desc(obj)
            if desc is not None:
                changed |= self._rename_short_keys(desc)
        if self.opt.renameTextures and top == "textures" and "minecraft:texture_set" in obj:
            changed |= self._rewrite_texture_set(kind, rel, obj)
        return changed

    # a .texture_set.json references its colour/MER/normal siblings by BARE name
    # (relative to its own folder), which the full-path replacer won't touch.
    def _rewrite_texture_set(self, kind, rel, obj):
        ts = obj.get("minecraft:texture_set")
        if not isinstance(ts, dict):
            return False
        folder = rel[: -len(rel.rsplit("/", 1)[-1])]  # keeps trailing "/"
        noext = self.tex_noext[kind]
        changed = False
        for field in ("color", "metalness_emissive_roughness", "normal", "heightmap"):
            v = ts.get(field)
            if not isinstance(v, str) or v.startswith("#") or "/" in v:
                continue  # hex colour / rgba array / already a full path
            new = noext.get(folder + v)
            if new is not None:
                ts[field] = new.rsplit("/", 1)[-1]  # new bare name
                changed = True
        return changed

    # animation-controller state names are local to their controller: rename the
    # state keys + initial_state + the target-state keys inside transitions.
    def _rename_ac_states(self, obj):
        controllers = obj.get("animation_controllers")
        if not isinstance(controllers, dict):
            return False
        changed = False
        for cid, ctrl in controllers.items():
            states = ctrl.get("states")
            if not isinstance(states, dict) or not states:
                continue
            used = set()
            local = {s: "s_" + unique_name(cid + "\0" + s, used, 3) for s in states}
            ctrl["states"] = {local[k]: v for k, v in states.items()}
            if ctrl.get("initial_state") in local:
                ctrl["initial_state"] = local[ctrl["initial_state"]]
            for st in ctrl["states"].values():
                trans = st.get("transitions")
                if isinstance(trans, list):
                    st["transitions"] = [
                        {local.get(k, k): v for k, v in t.items()}
                        if isinstance(t, dict) else t
                        for t in trans
                    ]
            changed = True
        return changed

    # component groups are entity-local: rename the keys + their event refs
    def _rename_component_groups(self, entity, rel):
        groups = entity.get("component_groups")
        if not isinstance(groups, dict) or not groups:
            return False
        used = set()
        local = {g: "g_" + unique_name(rel + "\0" + g, used, 4) for g in groups}
        entity["component_groups"] = {local[k]: v for k, v in groups.items()}

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "component_groups" and isinstance(v, list):
                        node[k] = [local.get(x, x) for x in v]
                    else:
                        walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        walk(entity.get("events", {}))
        return True

    # client-entity animation short-keys (+ their animate references)
    def _rename_short_keys(self, desc):
        anims = desc.get("animations")
        if not isinstance(anims, dict) or not anims:
            return False
        changed = False
        new = {}
        for k, v in anims.items():
            nk = self.short_key.get(k, k)
            changed |= nk != k
            new[nk] = v
        desc["animations"] = new
        scripts = desc.get("scripts", {})
        animate = scripts.get("animate")
        if isinstance(animate, list):
            out = []
            for entry in animate:
                if isinstance(entry, str):
                    nk = self.short_key.get(entry, entry)
                    changed |= nk != entry
                    out.append(nk)
                elif isinstance(entry, dict):
                    out.append({self.short_key.get(k, k): val
                                for k, val in entry.items()})
                    changed = True
                else:
                    out.append(entry)
            scripts["animate"] = out
        return changed

    # RP animation controllers reference client-entity short-keys in states
    def _remap_controller_anims(self, obj):
        controllers = obj.get("animation_controllers")
        if not isinstance(controllers, dict):
            return False
        changed = False
        for ctrl in controllers.values():
            for state in (ctrl.get("states") or {}).values():
                arr = state.get("animations")
                if not isinstance(arr, list):
                    continue
                out = []
                for entry in arr:
                    if isinstance(entry, str):
                        nk = self.short_key.get(entry, entry)
                        changed |= nk != entry
                        out.append(nk)
                    elif isinstance(entry, dict):
                        out.append({self.short_key.get(k, k): v
                                    for k, v in entry.items()})
                        changed = True
                    else:
                        out.append(entry)
                state["animations"] = out
        return changed

    # -- validation ---------------------------------------------------------

    def _full(self, root, rel):
        return os.path.join(root, rel.replace("/", os.sep))

    def _text_files(self, kind, root):
        for rel in self._all_files[kind]:
            low = rel.lower()
            if low.endswith(".json") or any(low.endswith(e) for e in TEXT_EXTS):
                yield rel, self._read_text(self._full(root, rel))

    def validate(self):
        """Return a list of problem strings. Path budget is measured
        pack-relative (e.g. ``textures/...``), which is what Bedrock checks.
        Reference coverage catches renamed files whose references were missed."""
        problems = []

        # 1) path budget: Bedrock allows <= max_path; flag anything longer.
        for kind, _ in self.packs:
            for rel in self._all_files[kind]:
                out = self.out_rel(kind, rel)
                if len(out) > self.opt.max_path:
                    problems.append(
                        "path > %d (%d): %s" % (self.opt.max_path, len(out), out))

        # 2) texture reference coverage: every "textures/..." token must map to
        #    a renamed image or a kept config path; anything else is dangling.
        if self.opt.renameTextures:
            tok = re.compile(r"textures/[A-Za-z0-9_./-]+")
            for kind, root in self.packs:
                old = self.tex_noext[kind]
                if not old:
                    continue
                for rel, text in self._text_files(kind, root):
                    if rel.rsplit("/", 1)[-1] in FIXED_BASENAMES:
                        pass  # configs legitimately hold texture paths; still check
                    for m in set(tok.findall(text)):
                        t = m
                        for e in IMAGE_EXTS:
                            if t.endswith(e):
                                t = t[: -len(e)]
                                break
                        if t in old or t.rsplit("/", 1)[-1] in FIXED_BASENAMES:
                            continue
                        # not a pack texture -> vanilla/external; left untouched
                        problems.append(
                            "external texture ref (left as-is) in %s: %s" % (rel, m))

        # 3) loot table reference coverage
        if self.opt.renameLootTables:
            tok = re.compile(r"loot_tables/[A-Za-z0-9_./-]+\.json")
            for kind, root in self.packs:
                old = {o for o in self.paths[kind] if o.startswith("loot_tables/")}
                if not old:
                    continue
                for rel, text in self._text_files(kind, root):
                    for m in set(tok.findall(text)):
                        if m not in old:
                            problems.append(
                                "external loot ref (left as-is) in %s: %s" % (rel, m))

        return problems

    # -- reporting ----------------------------------------------------------

    def summary(self):
        moved = sum(len(m) for m in self.paths.values())
        return {
            "animations": len(self.anim),
            "animation_controllers": len(self.anim_ctrl),
            "particles": len(self.particle),
            "geometry": len(self.geometry),
            "render_controllers": len(self.render_ctrl),
            "sound_files": sum(len(m) for m in self.sound_noext.values()),
            "structure_ids": len(self.structure_id),
            "short_keys": len(self.short_key),
            "files_moved": moved,
        }
