# PrivateLabBench Project Scope

PrivateLabBench is an open-source, local-first evaluation framework for scientific machine learning on private or restricted datasets.

Its core job is simple: run evaluation where the data already lives, then produce reproducible artifacts that can be inspected or shared without requiring the raw dataset to move.

## Problems the project should solve

- Does a model work on this local scientific distribution?
- Where does performance degrade across batches, sites, groups, targets, or time?
- How does a candidate compare with a baseline?
- What privacy risks are visible from the outputs we plan to release?
- Can another researcher verify the reported artifact hashes and configuration?
- Can a new scientific domain reuse the same evaluation protocol without modifying the central runner?

## Design principles

- **Local first:** raw samples remain in the user's controlled environment.
- **Model agnostic:** prediction tables are the primary interoperability boundary.
- **Domain extensible:** molecules are an initial domain, not the architecture.
- **Reproducible:** runs produce verifiable configs/artifacts.
- **Precise privacy claims:** privacy audits, perturbation, and formal mechanisms are distinct.
- **No hosted-service dependency:** core evaluation remains fully local.

## What belongs in core

- task/plugin registry;
- local config runner;
- prediction-table evaluation;
- metrics and diagnostics;
- privacy audits;
- scientific task packs;
- report/manifest integrity;
- comparison tooling;
- extension interfaces and documentation.

PrivateLabBench should interoperate with dataset hubs, experiment trackers, model registries, and other research tools rather than replace them.
