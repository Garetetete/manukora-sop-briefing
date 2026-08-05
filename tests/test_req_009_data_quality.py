"""REQ-009 reporting contradictions instead of resolving them silently."""

from sop.rules import find_data_quality_issues

from .conftest import make_row


def test_req_009_bioactive_launch_date_conflict_is_detected(rows):
    """The brief says mid-January launch; the extract records December sales."""
    issues = find_data_quality_issues(rows)
    skus = {i.sku for i in issues}
    assert skus == {
        "Bioactive Blend Immunity 250g",
        "Bioactive Blend Energy 250g",
        "Bioactive Blend Recovery 250g",
    }


def test_req_009_issue_states_the_evidence_and_the_assumption_taken(rows):
    issue = next(i for i in find_data_quality_issues(rows)
                 if i.sku == "Bioactive Blend Energy 250g")
    assert "272 units sold in M1" in issue.description
    assert "measured from M2" in issue.assumption


def test_req_009_a_sku_with_no_pre_launch_sales_raises_nothing():
    clean = make_row(sku="Bioactive Blend Energy 250g",
                     shopify=(0, 184, 208, 232), amazon=(0, 124, 140, 156))
    assert find_data_quality_issues([clean]) == []


def test_req_009_ordinary_skus_raise_nothing(by_sku):
    assert find_data_quality_issues([by_sku["Manuka Honey MGO 263+ 250g"]]) == []
