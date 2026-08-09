from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopologyPolicy:
    minimum_routing_accuracy: float = 0.80
    quality_noninferiority_margin: float = 0.01
    maximum_cost_increase: float = 0.20
    maximum_latency_increase: float = 0.20
    maximum_panel_size: int = 5
    maximum_final_holdout_accesses: int = 1
    automatic_activation_enabled: bool = False


DEFAULT_TOPOLOGY_POLICY = TopologyPolicy()
