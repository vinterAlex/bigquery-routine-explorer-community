import json
import os
import logging
from .parsing import parse_routine_body
from .models import GraphNode, GraphEdge, GraphSnapshot

logger = logging.getLogger(__name__)

GRAPH_CACHE_PATH = os.environ.get("GRAPH_CACHE_PATH", "graph.json")


def build_graph(routines: list[dict]) -> GraphSnapshot:
    nodes_map = {}
    edges = []
    routines_metadata = {}
    edge_seq = 0

    for r in routines:
        fqn = r["fqn"]
        parsed = parse_routine_body(r["definition"])
        ops = parsed["operations"]
        has_dyn = parsed["has_dynamic_sql"]
        op_types = list({op["type"] for op in ops})

        routines_metadata[fqn] = {
            "definition": r["definition"],
            "operation_types": op_types,
            "has_dynamic_sql": has_dyn,
            "detected_operations": ops,
            "created": r.get("created"),
            "last_modified": r.get("last_modified"),
            "language": r.get("language"),
            "routine_type": r.get("routine_type"),
        }

        if fqn not in nodes_map:
            nodes_map[fqn] = GraphNode(
                id=fqn,
                label=r["name"],
                type="routine",
                routine_type=r.get("routine_type"),
                language=r.get("language"),
                dataset=r["dataset"],
                project=r["project"],
                has_dynamic_sql=has_dyn,
                operation_types=op_types,
            )

        for op in ops:
            target_fqn = op["target"]
            if target_fqn not in nodes_map:
                parts = target_fqn.split(".")
                if len(parts) == 3:
                    t_proj, t_ds, t_name = parts
                elif len(parts) == 2:
                    t_proj, t_ds, t_name = r["project"], parts[0], parts[1]
                else:
                    t_proj, t_ds, t_name = r["project"], r["dataset"], parts[0]

                nodes_map[target_fqn] = GraphNode(
                    id=target_fqn,
                    label=t_name,
                    type=op["target_type"],
                    dataset=t_ds,
                    project=t_proj,
                )

            edge_seq += 1
            edges.append(GraphEdge(
                from_=fqn,
                to=target_fqn,
                operation=op["type"],
                sequence=op["sequence"],
                label=f"{op['type']} (#{op['sequence']})",
            ))

    return GraphSnapshot(
        nodes=list(nodes_map.values()),
        edges=edges,
        routines_metadata=routines_metadata,
    )


def save_graph(snapshot: GraphSnapshot):
    with open(GRAPH_CACHE_PATH, "w") as f:
        f.write(snapshot.model_dump_json(indent=2))
    logger.info(f"Graph saved to {GRAPH_CACHE_PATH}")


def load_graph() -> GraphSnapshot | None:
    if not os.path.exists(GRAPH_CACHE_PATH):
        return None
    with open(GRAPH_CACHE_PATH) as f:
        data = json.load(f)
    return GraphSnapshot(**data)


def get_subgraph(snapshot: GraphSnapshot, selected_node: str = None,
                 forward_depth: int = 2, backward_depth: int = 2) -> GraphSnapshot:
    if not selected_node:
        return snapshot

    visited = set()
    visited.add(selected_node)

    # Forward: nodes that selected_node depends on (edges FROM selected_node)
    frontier = {selected_node}
    for _ in range(forward_depth):
        next_frontier = set()
        for node in frontier:
            for e in snapshot.edges:
                if e.from_ == node and e.to not in visited:
                    visited.add(e.to)
                    next_frontier.add(e.to)
        frontier = next_frontier

    # Backward: nodes that depend on selected_node (edges TO selected_node)
    frontier = {selected_node}
    for _ in range(backward_depth):
        next_frontier = set()
        for node in frontier:
            for e in snapshot.edges:
                if e.to == node and e.from_ not in visited:
                    visited.add(e.from_)
                    next_frontier.add(e.from_)
        frontier = next_frontier

    filtered_nodes = [n for n in snapshot.nodes if n.id in visited]
    filtered_edges = [e for e in snapshot.edges if e.from_ in visited and e.to in visited]

    filtered_meta = {k: v for k, v in snapshot.routines_metadata.items() if k in visited}

    return GraphSnapshot(
        nodes=filtered_nodes,
        edges=filtered_edges,
        routines_metadata=filtered_meta,
    )
