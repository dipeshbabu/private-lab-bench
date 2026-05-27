from privatelabbench.privacy.release import AggregateReleasePolicy, evaluate_aggregate_release


def test_aggregate_release_policy_passes_when_thresholds_are_met():
    result = evaluate_aggregate_release(
        n_clients=3,
        total_samples=120,
        client_sample_counts=[40, 35, 45],
        policy=AggregateReleasePolicy(min_clients=3, min_total_samples=100, min_client_samples=20),
    )

    assert result["status"] == "pass"
    assert result["publishable"] is True
    assert result["violations"] == []


def test_aggregate_release_policy_reports_threshold_violations():
    result = evaluate_aggregate_release(
        n_clients=2,
        total_samples=70,
        client_sample_counts=[60, 10],
        policy=AggregateReleasePolicy(min_clients=3, min_total_samples=100, min_client_samples=20),
    )

    assert result["status"] == "fail"
    assert result["publishable"] is False
    assert result["violations"] == [
        "min_clients_not_met",
        "min_total_samples_not_met",
        "min_client_samples_not_met",
    ]
