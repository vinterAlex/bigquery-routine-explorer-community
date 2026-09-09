from pydantic import BaseModel
from typing import Optional


class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # "routine" or "table"
    routine_type: Optional[str] = None
    language: Optional[str] = None
    dataset: Optional[str] = None
    project: Optional[str] = None
    has_dynamic_sql: bool = False
    operation_types: list[str] = []


class GraphEdge(BaseModel):
    from_: str
    to: str
    operation: str  # call, create, insert, merge, delete, read
    sequence: int
    label: str


class RoutineDetail(BaseModel):
    fqn: str
    name: str
    routine_type: str
    language: Optional[str] = None
    definition: Optional[str] = None
    creation_time: Optional[str] = None
    last_modified_time: Optional[str] = None
    dataset: str
    project: str
    has_dynamic_sql: bool = False
    operation_types: list[str] = []
    detected_operations: list[dict] = []


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    routines_metadata: dict = {}
