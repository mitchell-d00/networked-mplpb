# Seed-to-Network run (http transport)

> Mechanical rehearsal. Corpora, queries, and code share one author; nodes share one machine. This does not test stranger recovery, retrieval quality against a flat baseline, adversarial peers, or scale.

| Metric | Value |
|---|---|
| routing_accuracy | 1.000 |
| ambiguity_preservation | 1.000 |
| absent_reported | 1.000 |
| provenance_retention | 1.000 |
| depth_policy_respected | True |
| laundering_probe_withheld | True |
| supersession_propagated | True |
| history_kept_in_cache | True |
| offline_retention | 1.000 |
| offline_remote_reported_unavailable | True |
| after_hub_loss_answered | 1.000 |
| origin_independence | 1.000 |
| recovery_rate | 1.000 |
| new_generation_routing | 1.000 |
| replication_integrity | 1.000 |

## Queries

| Phase | Query | Expected | Got | Owner ok | Provenance ok |
|---|---|---|---|---|---|
| E | how do I validate a copy of the seed corpus? | local | local | True |  |
| E | what does the provenance envelope contain on the network? | local | local | True |  |
| E | bisque firing schedule for a kiln | remote | remote | True | True |
| E | why is my glaze crawling on the ceramic? | remote | remote | True | True |
| E | my bike brakes squeal | remote | remote | True | True |
| E | when should I replace a bicycle chain? | remote | remote | True | True |
| E | pottery furnace temperature | remote | remote | True | True |
| E | hive inspection checklist for honey bees | ambiguous | ambiguous | True |  |
| E | when to harvest honey from the hive | ambiguous | ambiguous | True |  |
| E | rooftop hive placement and wind | remote | remote | True | True |
| E | sourdough starter hydration | not_found | not_found | True |  |
| E | tax rules for selling a house | not_found | not_found | True |  |
| F | how do I validate a copy of the seed corpus? | local | local | True |  |
| F | what does the provenance envelope contain on the network? | local | local | True |  |
| F | bisque firing schedule for a kiln | remote | remote | True | True |
| F | why is my glaze crawling on the ceramic? | remote | remote | True | True |
| F | my bike brakes squeal | remote | remote | True | True |
| F | when should I replace a bicycle chain? | remote | remote | True | True |
| F | pottery furnace temperature | remote | remote | True | True |
| F | rooftop hive placement and wind | remote | remote | True | True |
| H | bisque firing schedule for a kiln | remote | remote | True | True |
| H | why is my glaze crawling on the ceramic? | remote | remote | True | True |
| H | my bike brakes squeal | remote | remote | True | True |
| H | when should I replace a bicycle chain? | remote | remote | True | True |
| H | pottery furnace temperature | remote | remote | True | True |
| H | rooftop hive placement and wind | remote | remote | True | True |

## Infrastructure burden

- **stdlib_only**: True
- **non_stdlib_imports**: []
- **persistent_services**: one static file server per node (optional)
- **administrative_actions**: 21
- **wall_seconds**: 2.93
- **cpu_seconds**: 2.43
- **storage_bytes**: {'B': 131455, 'C': 128615, 'D': 200163, 'E': 104127, 'E-descendant': 53360, 'E-incoming': 52288, 'H2': 115524, 'offline-copy-B-off': 52288, 'offline-copy-B-on': 52288, 'offline-desc-B-off': 56025, 'offline-desc-B-on': 56025, 'sneakernet': 22523}
- **peak_rss_kb**: 30364

## New-generation recovery (Condition H)

- corpus_id_preserved: True
- fingerprint_preserved: True
- scope_readable: True
- boot_block_present: True
- validation_rules_in_prose: True
- current_vs_retired: True
- supersession_traceable: True
- lineage_chain_verifies: True
- instantiation_guide_present: True
- can_seed_next_generation: True
