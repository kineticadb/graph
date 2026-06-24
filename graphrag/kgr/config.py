"""Runtime configuration knobs read from the environment."""
from __future__ import annotations

import os

_TRUTHY = {"1", "on", "true", "yes"}

# The default label axis (LABEL_KEY). A node's *primary* structural type
# (Person, Organization, Location, …) lives on this axis and is always element 0
# of kgr.nodes.LABEL. Facet labels (e.g. AI, LLM) live on other axes (Industry,
# Technology, …) and are appended after the primary. See ontology.axis_map().
DEFAULT_AXIS = "EntityType"

# The default axis (LABEL_KEY) for relation types — the semantic category an
# action/verb falls under (e.g. EXPLOITS/AFFECTS -> Offensive). Mirrors node axes
# for the EDGES component; unseeded verbs fall here. See ontology.rebuild_edge_label_keys().
DEFAULT_RELATION_AXIS = "Action"


def compound_edges_enabled() -> bool:
    """Whether kgr.edges.LABEL is stored in compound `<srcLabel>_<baseLabel>_<dstLabel>` form.

    Default **off**: edges carry the bare base relation label (e.g. `WORKS_AT`),
    which keeps the meta-graph schema DOT readable (no node-label prefixes
    crowding every edge).

    Turn **on** with `KGR_COMPOUND_EDGES=on` to make the
    `(srcLabel, baseLabel, dstLabel)` triple unique per edge LABEL, so Kinetica
    can derive the schema graph from metadata alone — no traversal — which is
    worth the visual density on very large graphs.

    Switching the flag and re-running `kgr init` (or `kgr recompose-edges` /
    `kgr recompose-edges --base`) rewrites existing rows to match.
    """
    return os.environ.get("KGR_COMPOUND_EDGES", "").strip().lower() in _TRUTHY
