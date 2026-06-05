from __future__ import annotations

import pandas as pd

from experiments_v2.fusion.fusion_labeling import TripleBarrierConfig, generate_triple_barrier_targets


def generate_labels(
    df: pd.DataFrame,
    config: TripleBarrierConfig = TripleBarrierConfig(),
) -> pd.DataFrame:
    return generate_triple_barrier_targets(df=df, config=config)
