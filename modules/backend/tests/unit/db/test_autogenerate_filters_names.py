"""The core autogenerate filter names exactly the constraints the module attaches.

``backend/app/db/autogenerate_filters.py`` keeps the two ``workspace_id``
foreign keys out of the core migration chain by *name*;
``modules/backend/app/models/workspace.py`` is what attaches them.  The two
lists must agree, and only a test that can read both sides can say so --
which makes it a modules test (a core file may not import the workspace
model).
"""

from __future__ import annotations

from backend.app.db.autogenerate_filters import MODULE_MANAGED_CONSTRAINTS
from modules.backend.app.models import workspace


def test_the_names_match_what_the_module_model_attaches():
    source = open(workspace.__file__, encoding="utf-8").read()
    for name in MODULE_MANAGED_CONSTRAINTS:
        assert name in source, (
            f"{name} is not attached by modules/backend/app/models/workspace.py"
        )


def test_the_table_list_names_every_table_the_modules_map():
    """And the table list names exactly the tables the modules' models declare.

    ``MODULE_TABLES`` is what keeps a core autogenerate from proposing
    ``op.drop_table`` for a table the modules own, and it is spelled out in core
    code because a core build has no modules package to ask (and no
    ``modules-manifest.txt`` inside the image).  The core-side test pins it
    against the manifest; only a test that can import the modules' models can
    say the manifest itself is complete.

    A new module model whose table is in neither list is the failure this
    catches: nothing else would notice until a core autogenerate proposed
    dropping it.
    """
    from backend.app.db.autogenerate_filters import MODULE_TABLES
    from backend.app.models import register_core_models
    from backend.app.modules_loader import require_modules_or_absent

    Base = register_core_models()
    require_modules_or_absent()
    mapped = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.class_.__module__.startswith("modules.")
        and mapper.local_table is not None
    }

    assert mapped, "no module model is registered; this test proves nothing"
    assert mapped == set(MODULE_TABLES), (
        "MODULE_TABLES and the modules' models disagree; update both it and the "
        "MODULE TABLES section of modules-manifest.txt.\n"
        f"  mapped but not listed: {sorted(mapped - set(MODULE_TABLES))}\n"
        f"  listed but not mapped: {sorted(set(MODULE_TABLES) - mapped)}"
    )
