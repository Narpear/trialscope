import re
from collections import defaultdict
from itertools import combinations

import pytest
from conftest import scope

from app.aggregators import AggregationOptions, Scope, aggregate
from app.aggregators.common import normalize_intervention
from app.aggregators.comparison import comparison
from app.aggregators.distribution import distribution
from app.aggregators.geographic import geographic
from app.aggregators.histogram import histogram
from app.aggregators.network import network
from app.aggregators.scatter import scatter
from app.aggregators.time_trend import time_trend

OPTIONS = AggregationOptions()


def test_time_trend_accepts_month_and_day_dates_and_cites(studies, make_plan):
    result = time_trend(scope(studies), make_plan("time_trend"), OPTIONS)
    assert {row["year"] for row in result.data} == {2006, 2019}
    assert result.data[0]["year_date"] == "2006-01-01"
    assert result.total_citations == 2
    assert result.data[0]["citations"][0]["field_path"].endswith("startDateStruct.date")


def test_time_trend_warns_when_start_date_is_missing(studies, make_plan):
    studies[0]["protocolSection"]["statusModule"].pop("startDateStruct")
    result = time_trend(scope(studies), make_plan("time_trend"), OPTIONS)
    assert sum(row["trial_count"] for row in result.data) == 1
    assert result.warnings == ["1 trials had no usable start date and were excluded."]


def test_distribution_groups_phase_and_cites(studies, make_plan):
    plan = make_plan("distribution", group_by="phase")
    result = distribution(scope(studies), plan, OPTIONS)
    assert result.data[0]["category"] == "Phase4"
    assert result.data[0]["trial_count"] == 2
    assert result.total_citations == 2


def test_multi_phase_study_is_counted_once_in_each_reported_phase(studies, make_plan):
    studies[0]["protocolSection"]["designModule"]["phases"] = ["PHASE1", "PHASE2"]
    result = distribution(scope(studies), make_plan("distribution", group_by="phase"), OPTIONS)
    counts = {row["category"]: row["trial_count"] for row in result.data}
    assert counts["Phase1"] == 1
    assert counts["Phase2"] == 1
    assert counts["Phase4"] == 1


def test_comparison_aggregates_each_group_scope_separately(studies, make_plan):
    plan = make_plan(
        "comparison",
        comparison_groups=["tirofiban", "placebo"],
        comparison_group_type="drug",
        group_by="phase",
    )
    scopes = [
        Scope("tirofiban", studies[:1], 1, False, "u1"),
        Scope("placebo", studies, 2, False, "u2"),
    ]
    result = comparison(scopes, plan, OPTIONS)
    counts = {(row["group"], row["category"]): row["trial_count"] for row in result.data}
    assert counts[("tirofiban", "Phase4")] == 1
    assert counts[("placebo", "Phase4")] == 2
    assert result.visualization_type == "grouped_bar_chart"
    tirofiban = next(row for row in result.data if row["group"] == "tirofiban")
    assert {citation["field_path"] for citation in tirofiban["citations"]} == {
        "protocolSection.armsInterventionsModule.interventions[].name",
        "protocolSection.designModule.phases",
    }


def test_comparison_condition_groups_cite_condition_membership(studies, make_plan):
    plan = make_plan(
        "comparison",
        comparison_groups=["a", "b"],
        comparison_group_type="condition",
        group_by="sponsor_class",
    )
    condition = studies[0]["protocolSection"]["conditionsModule"]["conditions"][0]
    result = comparison([Scope(condition, studies[:1], 1, False, "")], plan, OPTIONS)
    assert result.data[0]["trial_count"] == 1
    paths = {citation["field_path"] for citation in result.data[0]["citations"]}
    assert "protocolSection.conditionsModule.conditions" in paths
    assert "protocolSection.sponsorCollaboratorsModule.leadSponsor.class" in paths


def test_geographic_counts_unique_countries(studies, make_plan):
    result = geographic(scope(studies), make_plan("geographic"), OPTIONS)
    assert {row["country"] for row in result.data} == {"Italy", "United States"}
    assert all(row["trial_count"] == 1 for row in result.data)
    assert all(row["citations"][0]["exact_value"] == row["country"] for row in result.data)


def test_network_nodes_edges_are_typed_weighted_and_cited(studies, make_plan):
    plan = make_plan("network", network_entity_types=["sponsor", "drug"])
    result = network(scope(studies), plan, AggregationOptions(network_top_n=30, network_min_edge_weight=1))
    assert result.nodes
    assert all(
        {"id", "label", "type", "weight", "citations"} <= node.keys() for node in result.nodes
    )
    assert result.edges
    assert all({"source", "target", "weight", "citations"} <= edge.keys() for edge in result.edges)
    assert all(len(edge["citations"]) >= 2 for edge in result.edges)


def test_network_respects_node_cap_and_edge_threshold(studies, make_plan):
    plan = make_plan("network", network_entity_types=["sponsor", "drug"])
    result = network(scope(studies), plan, AggregationOptions(network_top_n=1, network_min_edge_weight=2))
    assert len(result.nodes) == 1
    assert result.edges == []


def test_drug_network_links_cooccurring_interventions(studies, make_plan):
    plan = make_plan("network", network_entity_types=["drug"])
    result = network(scope(studies), plan, AggregationOptions(network_top_n=30, network_min_edge_weight=1))
    assert result.edges
    edge = next(edge for edge in result.edges if edge["weight"] == 1)
    assert len(edge["citations"]) == 2
    assert all(
        citation["field_path"].endswith("interventions[].name") for citation in edge["citations"]
    )


def test_network_excludes_configured_generic_interventions(studies, make_plan):
    plan = make_plan("network", network_entity_types=["drug"])
    result = network(
        scope(studies),
        plan,
        AggregationOptions(
            network_top_n=30, network_min_edge_weight=1, network_excluded_interventions=[" PLACEBO "]
        ),
    )
    assert all(node["label"].casefold() != "placebo" for node in result.nodes)
    assert all("drug:placebo" not in (edge["source"], edge["target"]) for edge in result.edges)
    assert any("placebo" in assumption for assumption in result.assumptions)


def reference_drug_key(name):
    without_marks = name.replace("®", "").replace("™", "").replace("©", "")
    without_brackets = re.sub(r"\(.*?\)|\[.*?\]", " ", without_marks)
    return " ".join(without_brackets.casefold().split()).strip(" .,;:-")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pembrolizumab (Keytruda®)", "pembrolizumab"),
        ("PEMBROLIZUMAB [MK-3475]", "pembrolizumab"),
        ("  pembrolizumab  ", "pembrolizumab"),
        ("Keytruda™", "keytruda"),
        ("MK-3475", "mk-3475"),
        ("Nab-paclitaxel", "nab-paclitaxel"),
    ],
)
def test_intervention_name_normalization(raw, expected):
    assert normalize_intervention(raw) == expected


def test_network_includes_biologicals_and_merges_brand_suffixes(make_plan):
    def study(nct_id, interventions):
        return {
            "protocolSection": {
                "identificationModule": {"nctId": nct_id, "briefTitle": nct_id},
                "armsInterventionsModule": {
                    "interventions": [{"type": kind, "name": name} for kind, name in interventions]
                },
            }
        }

    studies = [
        study("NCT1", [("BIOLOGICAL", "Pembrolizumab (Keytruda®)"), ("DRUG", "Carboplatin")]),
        study("NCT2", [("DRUG", "pembrolizumab"), ("DRUG", "CARBOPLATIN"), ("DEVICE", "Pump")]),
    ]
    plan = make_plan("network", network_entity_types=["drug"])
    result = network(scope(studies), plan, OPTIONS)
    assert {node["id"]: node["weight"] for node in result.nodes} == {
        "drug:pembrolizumab": 2,
        "drug:carboplatin": 2,
    }
    assert [(edge["source"], edge["target"], edge["weight"]) for edge in result.edges] == [
        ("drug:carboplatin", "drug:pembrolizumab", 2)
    ]


def test_combination_network_weights_match_raw_api_fixture(pembrolizumab_studies, make_plan):
    exclusions = ["placebo", "standard of care", "saline", "best supportive care"]
    excluded = set(exclusions)
    expected: dict[tuple[str, str], set[str]] = defaultdict(set)
    for study in pembrolizumab_studies:
        protocol = study["protocolSection"]
        nct_id = protocol["identificationModule"]["nctId"]
        interventions = protocol.get("armsInterventionsModule", {}).get("interventions", [])
        drugs = {
            key
            for intervention in interventions
            if intervention.get("type") in ("DRUG", "BIOLOGICAL") and intervention.get("name")
            for key in [reference_drug_key(intervention["name"])]
            if key not in excluded
        }
        for left, right in combinations(sorted(drugs), 2):
            expected[(f"drug:{left}", f"drug:{right}")].add(nct_id)

    plan = make_plan("network", network_entity_types=["drug"])
    result = network(
        scope(pembrolizumab_studies),
        plan,
        AggregationOptions(
            network_top_n=1000, network_min_edge_weight=1, network_excluded_interventions=exclusions
        ),
    )
    actual = {
        (edge["source"], edge["target"]): (edge["weight"], set(edge["nct_ids"]))
        for edge in result.edges
    }

    assert set(actual) == set(expected)
    assert all(actual[pair] == (len(nct_ids), nct_ids) for pair, nct_ids in expected.items())


def test_histogram_and_scatter_enrollment_provenance(studies, make_plan):
    histogram_result = histogram(scope(studies), make_plan("histogram"), OPTIONS)
    scatter_result = scatter(scope(studies), make_plan("scatter"), OPTIONS)
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
            comparison_group_type="drug" if analysis_type == "comparison" else None,
            network_entity_types=["sponsor", "drug"] if analysis_type == "network" else [],
        )
        scopes = (
            [Scope("Tirofiban", studies[:1], 1, False, ""), Scope("Placebo", studies, 2, False, "")]
            if analysis_type == "comparison"
            else scope(studies)
        )
        assert aggregate(scopes, plan, AggregationOptions(network_min_edge_weight=1)).visualization_type
