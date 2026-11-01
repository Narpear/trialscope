from collections import defaultdict
from itertools import combinations

from app.aggregators import aggregate
from app.aggregators.core import (
    comparison,
    distribution,
    geographic,
    histogram,
    network,
    scatter,
    time_trend,
)


def test_time_trend_accepts_month_and_day_dates_and_cites(studies, make_plan):
    result = time_trend(studies, make_plan("time_trend"))
    assert {row["year"] for row in result.data} == {2006, 2019}
    assert result.data[0]["year_date"] == "2006-01-01"
    assert result.total_citations == 2
    assert result.data[0]["citations"][0]["field_path"].endswith("startDateStruct.date")


def test_time_trend_warns_when_start_date_is_missing(studies, make_plan):
    studies[0]["protocolSection"]["statusModule"].pop("startDateStruct")
    result = time_trend(studies, make_plan("time_trend"))
    assert sum(row["trial_count"] for row in result.data) == 1
    assert result.warnings == ["1 trials had no usable start date and were excluded."]


def test_distribution_groups_phase_and_cites(studies, make_plan):
    plan = make_plan("distribution", group_by="phase")
    result = distribution(studies, plan)
    assert result.data[0]["category"] == "Phase4"
    assert result.data[0]["trial_count"] == 2
    assert result.total_citations == 2


def test_multi_phase_study_is_counted_once_in_each_reported_phase(studies, make_plan):
    studies[0]["protocolSection"]["designModule"]["phases"] = ["PHASE1", "PHASE2"]
    result = distribution(studies, make_plan("distribution", group_by="phase"))
    counts = {row["category"]: row["trial_count"] for row in result.data}
    assert counts["Phase1"] == 1
    assert counts["Phase2"] == 1
    assert counts["Phase4"] == 1


def test_comparison_normalizes_whitespace_and_case(studies, make_plan):
    plan = make_plan(
        "comparison",
        comparison_groups=["  TIROFIBAN ", "Placebo"],
        group_by="phase",
    )
    result = comparison(studies, plan)
    assert {row["group"] for row in result.data} == {"TIROFIBAN", "Placebo"}
    assert all(row["trial_count"] == 1 for row in result.data)
    assert all(
        {citation["field_path"] for citation in row["citations"]}
        >= {
            "protocolSection.armsInterventionsModule.interventions[].name",
            "protocolSection.designModule.phases",
        }
        for row in result.data
    )
    assert result.visualization_type == "grouped_bar_chart"


def test_geographic_counts_unique_countries(studies, make_plan):
    result = geographic(studies, make_plan("geographic"))
    assert {row["country"] for row in result.data} == {"Italy", "United States"}
    assert all(row["trial_count"] == 1 for row in result.data)
    assert all(row["citations"][0]["exact_value"] == row["country"] for row in result.data)


def test_network_nodes_edges_are_typed_weighted_and_cited(studies, make_plan):
    plan = make_plan("network", network_entity_types=["sponsor", "drug"])
    result = network(studies, plan, top_n=30, min_edge_weight=1)
    assert result.nodes
    assert all(
        {"id", "label", "type", "weight", "citations"} <= node.keys() for node in result.nodes
    )
    assert result.edges
    assert all({"source", "target", "weight", "citations"} <= edge.keys() for edge in result.edges)
    assert all(len(edge["citations"]) >= 2 for edge in result.edges)


def test_network_respects_node_cap_and_edge_threshold(studies, make_plan):
    plan = make_plan("network", network_entity_types=["sponsor", "drug"])
    result = network(studies, plan, top_n=1, min_edge_weight=2)
    assert len(result.nodes) == 1
    assert result.edges == []


def test_drug_network_links_cooccurring_interventions(studies, make_plan):
    plan = make_plan("network", network_entity_types=["drug"])
    result = network(studies, plan, top_n=30, min_edge_weight=1)
    assert result.edges
    edge = next(edge for edge in result.edges if edge["weight"] == 1)
    assert len(edge["citations"]) == 2
    assert all(
        citation["field_path"].endswith("interventions[].name") for citation in edge["citations"]
    )


def test_network_excludes_configured_generic_interventions(studies, make_plan):
    plan = make_plan("network", network_entity_types=["drug"])
    result = network(
        studies,
        plan,
        top_n=30,
        min_edge_weight=1,
        excluded_interventions=[" PLACEBO "],
    )
    assert all(node["label"].casefold() != "placebo" for node in result.nodes)
    assert all("drug:placebo" not in (edge["source"], edge["target"]) for edge in result.edges)
    assert any("placebo" in assumption for assumption in result.assumptions)


def test_combination_network_weights_match_raw_api_fixture(pembrolizumab_studies, make_plan):
    exclusions = ["placebo", "standard of care", "saline", "best supportive care"]
    excluded = set(exclusions)
    expected: dict[tuple[str, str], set[str]] = defaultdict(set)
    for study in pembrolizumab_studies:
        protocol = study["protocolSection"]
        nct_id = protocol["identificationModule"]["nctId"]
        interventions = protocol.get("armsInterventionsModule", {}).get("interventions", [])
        drugs = {
            " ".join(intervention["name"].casefold().split())
            for intervention in interventions
            if intervention.get("type") == "DRUG"
            and intervention.get("name")
            and " ".join(intervention["name"].casefold().split()) not in excluded
        }
        for left, right in combinations(sorted(drugs), 2):
            expected[(f"drug:{left}", f"drug:{right}")].add(nct_id)

    plan = make_plan("network", network_entity_types=["drug"])
    result = network(
        pembrolizumab_studies,
        plan,
        top_n=1000,
        min_edge_weight=1,
        excluded_interventions=exclusions,
    )
    actual = {
        (edge["source"], edge["target"]): (edge["weight"], set(edge["nct_ids"]))
        for edge in result.edges
    }

    assert set(actual) == set(expected)
    assert all(actual[pair] == (len(nct_ids), nct_ids) for pair, nct_ids in expected.items())


def test_histogram_and_scatter_enrollment_provenance(studies, make_plan):
    histogram_result = histogram(studies, make_plan("histogram"))
    scatter_result = scatter(studies, make_plan("scatter"))
    assert sum(row["trial_count"] for row in histogram_result.data) == 2
    assert len(scatter_result.data) == 2
    assert len(scatter_result.data[0]["citations"]) == 2
    assert scatter_result.data[0]["citations"][0]["exact_value"] is not None


def test_registry_dispatches_each_supported_type(studies, make_plan):
    types = (
        "time_trend",
        "distribution",
        "comparison",
        "geographic",
        "network",
        "histogram",
        "scatter",
    )
    for analysis_type in types:
        plan = make_plan(
            analysis_type,
            group_by="phase" if analysis_type == "distribution" else None,
            comparison_groups=["Tirofiban", "Placebo"] if analysis_type == "comparison" else [],
            network_entity_types=["sponsor", "drug"] if analysis_type == "network" else [],
        )
        assert aggregate(studies, plan, min_edge_weight=1).visualization_type
