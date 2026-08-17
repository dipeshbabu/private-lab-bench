# Concepts

## Local-first evaluation

PrivateLabBench reads evaluation inputs in the user's environment. The core workflow does not upload raw rows, model code, or prediction tables to a service.

## Tasks

A task defines how a local evaluation runs. Built-ins include generic prediction tables, molecules, and multi-site evaluation. Third-party packages can register tasks through Python entry points.

## Prediction tables

`prediction-table/v1` is the preferred interface for externally generated model outputs. It separates stable sample IDs, targets, predictions/probabilities, metadata, and configured slices.

## Reports and manifests

Reports contain task results. Run manifests bind concrete local files and hashes for reproducibility.

## Evaluation receipts

`evaluation-receipt/v1` provides a stable result schema. Full receipts contain a local-only section; shareable receipts omit local paths/config snapshots/exact local-only fields and are independently verifiable.

## Privacy layers

PrivateLabBench separates exact reporting, heuristic metric perturbation, empirical privacy attacks, formal bounded-query primitives, and release policies. These have different meanings; see [Privacy](privacy.md).

## Benchmark packs

`benchmark-pack/v1` bundles a versioned evaluation protocol, small/synthetic prediction fixture, provenance/license metadata, and known-good receipt. Packs demonstrate workflows without turning the project into a dataset mirror.
