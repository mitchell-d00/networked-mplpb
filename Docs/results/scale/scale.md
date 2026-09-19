# Scale probe (FM-N15)

| nodes | create_nodes_s | register_all_s | register_per_node_ms | registry_bytes | hub_files | learn_s | route_ms | routing_correct |
|---|---|---|---|---|---|---|---|---|
| 10 | 0.243 | 0.334 | 33.4 | 14609 | 44 | 0.081 | 1.02 | 10/10 |
| 40 | 1.075 | 1.914 | 47.8 | 58439 | 104 | 0.303 | 3.56 | 10/10 |
| 160 | 4.124 | 19.235 | 120.2 | 234299 | 344 | 1.525 | 13.98 | 10/10 |

Nodes grew 16x. Per-node registration cost grew 3.6x; routing cost grew 13.7x; registry size grew 16.0x.
