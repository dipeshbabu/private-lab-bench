import numpy as np
import pytest
from sklearn.metrics import log_loss

from privatelabbench.eval.metrics import multiclass_metrics


@pytest.mark.parametrize("labels", [[10, 20], [20, 10], [30, 10, 20]])
def test_metrics_follow_the_declared_probability_column_labels(labels):
    truth = np.array(labels * 3)
    matrix = np.full((len(truth), len(labels)), 0.1 / (len(labels) - 1))
    for row in range(len(truth)):
        matrix[row, row % len(labels)] = 0.9
    result = multiclass_metrics(truth, matrix, labels=labels)
    assert result["accuracy"] == result["macro_f1"] == result["weighted_f1"] == 1.0
    assert result["macro_auroc_ovr"] == 1.0
    assert result["log_loss"] == pytest.approx(-np.log(0.9))


def test_permuting_columns_and_labels_together_preserves_all_metrics():
    truth = np.array([10, 20, 30, 10, 20, 30])
    probabilities = np.array([[0.6, 0.3, 0.1], [0.2, 0.5, 0.3], [0.1, 0.3, 0.6]] * 2)
    original = multiclass_metrics(truth, probabilities, labels=[10, 20, 30])
    permuted = multiclass_metrics(
        truth, probabilities[:, [2, 0, 1]], labels=[30, 10, 20]
    )
    assert original == pytest.approx(permuted)
    assert original["log_loss"] == pytest.approx(
        log_loss(truth, probabilities, labels=[10, 20, 30])
    )


@pytest.mark.parametrize(
    "truth,matrix,labels",
    [
        ([0, 1], [[0.2, 0.8], [0.8, 0.2]], [0, 0]),
        ([0, 1], [[0.2, 0.8], [0.8, 0.2]], [0]),
        ([0, 2], [[0.2, 0.8], [0.8, 0.2]], [0, 1]),
        ([0], [[0.2, 0.8], [0.8, 0.2]], [0, 1]),
        ([0, 1], [[0.2, float("nan")], [0.8, 0.2]], [0, 1]),
        ([0, 1], [[-0.2, 1.2], [0.8, 0.2]], [0, 1]),
        ([0, 1], [[0.2, 0.7], [0.8, 0.2]], [0, 1]),
    ],
)
def test_multiclass_metrics_reject_invalid_alignment_or_probabilities(
    truth, matrix, labels
):
    with pytest.raises(ValueError):
        multiclass_metrics(np.asarray(truth), np.asarray(matrix), labels=labels)
