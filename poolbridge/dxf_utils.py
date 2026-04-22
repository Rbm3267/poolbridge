"""Utility functions for inspecting output DXF files."""

from collections import defaultdict

import pandas as pd


def layer_stats(dxf_path: str) -> pd.DataFrame:
    """Return a DataFrame summarising entity counts per layer in a DXF file.

    Args:
        dxf_path: Path to the DXF file to inspect.

    Returns:
        DataFrame with columns: Layer, Entities, Contents.
    """
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    counts: dict = defaultdict(lambda: defaultdict(int))
    for ent in msp:
        counts[ent.dxf.layer][ent.dxftype()] += 1
    rows = []
    for layer in sorted(counts):
        total = sum(counts[layer].values())
        types = "  ".join(
            f"{t} ×{n}"
            for t, n in sorted(counts[layer].items(), key=lambda x: -x[1])
        )
        rows.append({"Layer": layer, "Entities": total, "Contents": types})
    return pd.DataFrame(rows)
