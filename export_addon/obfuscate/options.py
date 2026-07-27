"""The Options object: which rename passes run, and how flattening behaves."""


class Options:
    KEYS = (
        "renameAnimations", "renameAnimationControllers", "renameParticles",
        "renameComponentGroups", "renameAnimationKeys", "renameGeometry",
        "renameRenderControllers", "renameSounds", "renameFiles",
        "renameTextures", "renameStructures", "renameLootTables",
    )

    def __init__(self, settings=None, max_path=80, strict=False):
        settings = settings or {}
        # "obfuscateJson" is the master switch (like "obfuscateScripts" for JS):
        # when on, every rename pass defaults to on. Turn passes off either with
        # renameX:false, or by listing them in "jsonObfuscatorArgs" (the JSON
        # analogue of obfuscatorArgs), e.g. ["textures", "structures"].
        master = bool(settings.get("obfuscateJson", False))
        disabled = set()
        for name in settings.get("jsonObfuscatorArgs", []) or []:
            key = self._pass_key(name)
            if key:
                disabled.add(key)
        # Particle / animation identifiers and client-entity animation short-keys
        # are frequently referenced from scripts (spawnParticle / playAnimation),
        # sometimes built dynamically, which no rewriter can follow -- so renaming
        # them is unreliable. They stay OFF even under the master switch; opt in
        # with an explicit renameX:true if you know your scripts use only literal
        # names. (renameSounds only renames the .ogg files now, which is reliable,
        # so it stays on.)
        SCRIPT_REFERENCED = {"renameParticles", "renameAnimations", "renameAnimationKeys"}
        for k in self.KEYS:
            default = master and k not in disabled and k not in SCRIPT_REFERENCED
            setattr(self, k, bool(settings.get(k, default)))
        self.max_path = int(settings.get("maxPathLength", max_path))
        self.strict = bool(settings.get("strictPaths", strict))
        # By default renamed files keep their existing folder (only the filename
        # is randomized) -- no config needed, and short names keep paths short.
        # Set "flatten": true to collapse folders: keep the top folder + any
        # leading namespace segments (studio/project, e.g. cyd/ab/cyd_ab) and
        # drop everything after. Paths with no namespace flatten to the top folder.
        self.flatten = bool(settings.get("flatten", False))
        self.namespace_dirs = set(settings.get("namespaceDirs", []))
        # keepStructureDirs: top folders that keep their FULL structure when
        # flattening (default none). categoryDirs: top folders that keep ONE more
        # level after the namespace -- the category (blocks/entity/items) -- then
        # flatten deeper. Handy for textures and models.
        self.keep_structure_dirs = set(settings.get("keepStructureDirs", []))
        self.category_dirs = set(settings.get("categoryDirs", ["textures", "models"]))
        # Pack-relative path prefixes to leave completely untouched -- for assets
        # referenced dynamically in scripts (e.g. "textures/.../spells/" + id),
        # which no text rewriter can follow. Files under these keep their names,
        # so the runtime-built reference still resolves.
        self.keep_paths = [p.strip("/") for p in settings.get("keepPaths", [])]

    @classmethod
    def _pass_key(cls, name):
        """Map a jsonObfuscatorArgs entry to a rename pass key. Accepts the short
        form ("textures"), the full key ("renameTextures"), or a flag
        ("--textures"). Returns None for anything unrecognised."""
        if not isinstance(name, str):
            return None
        n = name.strip().lstrip("-")
        if n in cls.KEYS:
            return n
        cand = "rename" + n[:1].upper() + n[1:]
        return cand if cand in cls.KEYS else None

    @property
    def any_ids(self):
        return (self.renameAnimations or self.renameAnimationControllers
                or self.renameParticles or self.renameComponentGroups
                or self.renameAnimationKeys or self.renameGeometry
                or self.renameRenderControllers)

    @property
    def any_files(self):
        return (self.renameFiles or self.renameTextures
                or self.renameStructures or self.renameLootTables
                or self.renameSounds)

    @property
    def enabled(self):
        return self.any_ids or self.any_files
