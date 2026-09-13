from backend.app.services.relationship_graph_service import RelationshipGraphService


def test_connected_components_include_standalone_nodes():
    result = RelationshipGraphService.connected_components(["a", "b", "c", "d"], [("a", "b"), ("b", "c")])
    assert sorted(result) == [["a", "b", "c"], ["d"]]

