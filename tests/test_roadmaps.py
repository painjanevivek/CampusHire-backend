import pytest

from app.modules.roadmaps.graph import AI_ENGINEER, RoadmapNode, next_nodes, validate_dag


def test_curated_roadmap_is_acyclic_and_returns_small_next_move() -> None:
    validate_dag(AI_ENGINEER)
    assert [node.key for node in next_nodes(AI_ENGINEER, {"python", "math"})] == ["ml"]


def test_cycles_are_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        validate_dag([RoadmapNode("a", "A", "Do A", ("b",)), RoadmapNode("b", "B", "Do B", ("a",))])
