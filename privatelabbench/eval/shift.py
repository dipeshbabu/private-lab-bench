from __future__ import annotations

import numpy as np


def feature_shift_summary(x_train: np.ndarray, x_test: np.ndarray) -> dict[str, float]:
    train_mean = x_train.mean(axis=0)
    test_mean = x_test.mean(axis=0)
    return {
        "mean_feature_l2_shift": float(np.linalg.norm(train_mean - test_mean)),
        "train_density": float((x_train > 0).mean()),
        "test_density": float((x_test > 0).mean()),
    }
