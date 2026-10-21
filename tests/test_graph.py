from backend.app.services.relationship_graph_service import RelationshipGraphService
from backend.app.services.relationship_group_service import (build_reportable_groups,
    build_reportable_groups_as_of, merge_report_groups_by_customer)
from types import SimpleNamespace


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


def test_report_components_follow_only_reportable_image_links():
    images = [SimpleNamespace(id=id, original_filename="unknown.jpg", source_job_number=customer,
                              source_checkin_date=date, source_technician_id=None)
              for id, customer, date in [("a", "C1", "20261001"), ("b", "C2", "20261002"),
                                          ("c", "C3", "20261003"), ("d", "C1", "20261004"),
                                          ("e", "C4", "20261004")]]
    def pair(a, b, classification, score=0.9):
        return SimpleNamespace(image_a_id=a, image_b_id=b, relationship_level=classification, relationship_score=score)
    pairs = [pair("a", "b", "same_image"), pair("b", "c", "edited_or_cropped"),
             pair("d", "e", "exact_file"), pair("c", "d", "similar_person"),
             pair("c", "d", "same_image", 0.1)]
    components = build_reportable_groups(images, pairs, 0.5, merge_by_customer=False)
    selected = [group for group in components if any(image.source_checkin_date == "20261001" for image in group)]
    assert [{image.id for image in group} for group in selected] == [{"a", "b", "c"}]
    assert len(build_reportable_groups(images, pairs, 0.5)) == 1  # Legacy customer-based presentation.


def test_selected_components_with_same_customer_are_combined_without_adding_other_images():
    def image(id, customer):
        return SimpleNamespace(id=id, original_filename="unknown.jpg", source_job_number=customer,
                               source_checkin_date="20261001", source_technician_id=None)
    selected = [[image("a", "C1"), image("b", "C2")],
                [image("c", "C1"), image("d", "C3")],
                [image("e", "C3"), image("f", "C4")]]
    merged = merge_report_groups_by_customer(selected)
    assert len(merged) == 1
    assert {image.id for image in merged[0]} == {"a", "b", "c", "d", "e", "f"}
    assert {image.id for group in merge_report_groups_by_customer(selected[:2]) for image in group} == {"a", "b", "c", "d"}


def test_as_of_report_graph_excludes_future_images_and_future_bridges():
    images = [SimpleNamespace(
        id=id, original_filename="unknown.jpg", source_job_number=f"C{id}",
        source_checkin_date=date, source_technician_id=None,
    ) for id, date in [("anchor", "20261001"), ("past", "20260813"),
                       ("future", "20261006"), ("past-only-through-future", "20260920")]]
    def pair(a, b):
        return SimpleNamespace(image_a_id=a, image_b_id=b, relationship_level="same_image",
                               relationship_score=.9)
    groups = build_reportable_groups_as_of(
        images,
        [pair("anchor", "past"), pair("anchor", "future"),
         pair("future", "past-only-through-future")],
        .5,
        "20261001",
    )

    assert [{image.id for image in group} for group in groups] == [{"anchor", "past"}]

