# SPDX-License-Identifier: Apache-2.0

"""Tests for the empty-result verification helpers in tier2.strategy."""

from __future__ import annotations

import pytest
from coa_serve.tier2.strategy import (
    StrategyResult,
    empty_result_is_verified,
    is_unverified_empty,
    user_supplied_literal_in_sql,
)


def _result(row_count: int, verified: bool = False) -> StrategyResult:
    return StrategyResult(
        sql="SELECT 1",
        rows=[{"x": 1}] * row_count,
        columns=["x"],
        confidence=0.9,
        strategy_name="nl_to_sql",
        trace_steps=[],
        row_count=row_count,
        empty_verified=verified,
    )


@pytest.mark.unit
class TestUserSuppliedLiteral:
    def test_user_identifier_is_detected(self):
        sql = "SELECT hire_date FROM employees WHERE employee_id = 'EMP-9999'"
        assert user_supplied_literal_in_sql(sql, "员工 EMP-9999 的入职日期是哪天？")

    def test_case_insensitive(self):
        assert user_supplied_literal_in_sql("SELECT 1 FROM t WHERE c = 'ACME'", "orders for acme")

    def test_guessed_categorical_value_is_not_user_supplied(self):
        # Live regression c52895c8: the model guessed 'active'; the question never said it.
        sql = "SELECT city, COUNT(DISTINCT id) FROM employees WHERE LOWER(employment_status) = 'active' GROUP BY city"
        assert not user_supplied_literal_in_sql(sql, "每个城市有多少名在职员工？")

    def test_single_char_literal_ignored(self):
        assert not user_supplied_literal_in_sql("SELECT 1 FROM t WHERE flag = 'y'", "any y here")

    def test_escaped_quote_literal(self):
        assert user_supplied_literal_in_sql("SELECT 1 FROM t WHERE n = 'O''Brien'", "who is o'brien")

    def test_empty_inputs(self):
        assert not user_supplied_literal_in_sql("", "q")
        assert not user_supplied_literal_in_sql("SELECT 'a'", "")


@pytest.mark.unit
class TestEmptyResultIsVerified:
    def test_user_identifier_only(self):
        sql = "SELECT hire_date FROM employees WHERE employee_id = 'EMP-9999'"
        assert empty_result_is_verified(sql, "员工 EMP-9999 的入职日期是哪天？")

    def test_no_string_filter_is_verified(self):
        assert empty_result_is_verified("SELECT * FROM claims", "Show all claims")

    def test_guessed_value_is_not_verified(self):
        sql = "SELECT city FROM employees WHERE LOWER(employment_status) = 'active'"
        assert not empty_result_is_verified(sql, "每个城市有多少名在职员工？")

    def test_one_guessed_value_beside_a_user_value_is_not_verified(self):
        sql = "SELECT 1 FROM leave_balances WHERE employee_id = 'EMP-3105' AND leave_type = 'annual'"
        assert not empty_result_is_verified(sql, "EMP-3105 还有几天年假")

    def test_ontop_iri_template_literals_ignored(self):
        sql = (
            "SELECT CONCAT('http://coa.amazon.com/ns/x/employee/', v1.id) AS e FROM employees v1 "
            "WHERE v1.employee_id = 'EMP-9999'"
        )
        assert empty_result_is_verified(sql, "EMP-9999 是谁")

    def test_empty_sql_is_not_verified(self):
        assert not empty_result_is_verified("", "q")


@pytest.mark.unit
class TestIsUnverifiedEmpty:
    def test_rows_are_never_unverified_empty(self):
        assert not is_unverified_empty(_result(3))

    def test_empty_without_proof(self):
        assert is_unverified_empty(_result(0))

    def test_empty_with_proof(self):
        assert not is_unverified_empty(_result(0, verified=True))
