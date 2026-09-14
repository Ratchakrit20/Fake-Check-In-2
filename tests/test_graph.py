from backend.app.services.relationship_graph_service import RelationshipGraphService


def test_connected_components_include_standalone_nodes():
    result = RelationshipGraphService.connected_components(["a", "b", "c", "d"], [("a", "b"), ("b", "c")])
    assert sorted(result) == [["a", "b", "c"], ["d"]]


def test_low_confidence_bridge_does_not_merge_independent_groups():
    scored_edges = [
        ("a", "b", .90),
        ("b", "c", .80),
        ("c", "d", .40),
        ("d", "e", .85),
    ]

    edges = RelationshipGraphService.qualified_edges(scored_edges, minimum_score=.65)
    result = RelationshipGraphService.connected_components(["a", "b", "c", "d", "e"], edges)

    assert sorted(result) == [["a", "b", "c"], ["d", "e"]]

