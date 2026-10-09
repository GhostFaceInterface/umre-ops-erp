# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services import dashboard_service, expense_service
from umre_ops.umre_ops.services.pnl_service import build_pnl


def sample_pnl() -> dict:
	return build_pnl(
		tours=[{"name": "TOUR-1", "label": "Ramazan", "durum": "Aktif"}],
		bookings=[
			{"name": "B1", "tur": "TOUR-1", "statu": "UMRECI", "ucret": 1300, "kms": 50, "odenen": 1000, "company": "ACME"},
			{"name": "B2", "tur": "TOUR-1", "statu": "HOCA", "ucret": 0, "kms": 0, "odenen": 0, "company": "ACME"},
		],
		components=[
			{"booking": "B1", "cost_type": "HOTEL", "currency": "USD", "amount": 300, "is_system_generated": 1},
			{"booking": "B1", "cost_type": "MEAL", "currency": "USD", "amount": 100, "is_system_generated": 1},
			{"booking": "B2", "cost_type": "HOTEL", "currency": "USD", "amount": 300, "is_system_generated": 1},
		],
		tour_expenses={"TOUR-1": 50},
		overhead=200,
	)


class TestDashboardPayload(TestCase):
	def test_payload_matches_pnl_and_keeps_colours_per_cost_type(self) -> None:
		payload = dashboard_service.build_dashboard_payload(sample_pnl())
		kpis = payload["kpis"]
		self.assertEqual(kpis["net_sales"], 1250)
		self.assertEqual(kpis["passenger_cost"], 700)
		self.assertEqual(kpis["total_cost"], 750)
		self.assertEqual(kpis["tour_profit"], 500)
		self.assertEqual(kpis["season_result"], 300)
		self.assertEqual(kpis["net_profit"], kpis["tour_profit"])
		self.assertEqual(
			sum(row["value"] for row in payload["cost_breakdown"]), kpis["total_cost"]
		)
		colours = {row["key"]: row["color"] for row in payload["cost_breakdown"]}
		self.assertEqual(colours["HOTEL"], dashboard_service.CHART_HEX_BY_CODE["HOTEL"])
		self.assertEqual(colours["MEAL"], dashboard_service.CHART_HEX_BY_CODE["MEAL"])
		self.assertEqual(payload["performance"]["profit_per_paying_passenger"], 500)
		self.assertEqual(payload["collections"]["open_receivable"], 300)
		self.assertTrue(payload["financial_data_valid"])


class TestDashboardSeasonIsolation(TestCase):
	@patch.object(dashboard_service, "require_doctype_permission")
	@patch.object(dashboard_service.frappe, "throw", side_effect=ValueError)
	def test_cross_season_tour_is_rejected(self, _throw: Mock, _permission: Mock) -> None:
		db = Mock()
		db.exists.return_value = True
		db.get_value.return_value = {"name": "TOUR-OLD", "season": "1447"}
		with patch.object(dashboard_service.frappe, "db", db), self.assertRaises(ValueError):
			dashboard_service.get_tour_cost_breakdown(season="1448", tour="TOUR-OLD")
		_throw.assert_called_once()

	def test_tour_options_are_dependent_on_selected_season(self) -> None:
		with patch.object(dashboard_service.frappe, "get_all", return_value=[]) as get_all:
			dashboard_service._list_tour_options("1448")
		self.assertEqual(get_all.call_args.kwargs["filters"], {"season": "1448"})

	@patch.object(dashboard_service, "require_doctype_permission")
	@patch.object(dashboard_service, "_assert_usd_tours")
	@patch.object(dashboard_service, "_company_context", return_value="ACME")
	@patch.object(dashboard_service, "_cost_type_labels", return_value={})
	@patch.object(dashboard_service, "get_season_pnl")
	@patch.object(dashboard_service, "get_active_season", return_value="1448")
	def test_empty_season_defaults_active_and_uses_single_pnl(
		self,
		_get_active_season: Mock,
		get_season_pnl: Mock,
		_labels: Mock,
		_company: Mock,
		_assert_usd_tours: Mock,
		_permission: Mock,
	) -> None:
		get_season_pnl.return_value = sample_pnl()

		def get_all(doctype: str, **_kwargs):
			if doctype == "Umre Season":
				return [{"name": "1448", "season_name": "1448 Hicri"}]
			return [{"name": "TOUR-1", "tur_adi": "Ramazan", "tur_kodu": "R1"}]

		db = Mock()
		db.exists.return_value = True
		with (
			patch.object(dashboard_service.frappe, "db", db),
			patch.object(dashboard_service.frappe, "get_all", side_effect=get_all),
		):
			result = dashboard_service.get_tour_cost_breakdown()

		self.assertEqual(result["selected_season"], "1448")
		self.assertEqual(result["seasons"], [{"name": "1448", "label": "1448 Hicri"}])
		self.assertEqual(result["tours"], [{"name": "TOUR-1", "label": "Ramazan"}])
		get_season_pnl.assert_called_once_with("1448", None, "ACME")
		_assert_usd_tours.assert_called_once_with("1448", None)

	@patch.object(dashboard_service, "require_doctype_permission")
	@patch.object(dashboard_service, "get_operational_dashboard_summary", return_value={"total_expense_usd": 1})
	@patch.object(dashboard_service, "get_tour_cost_breakdown")
	def test_overhead_panel_does_not_depend_on_tour_calculation(
		self, get_breakdown: Mock, _summary: Mock, _permission: Mock
	) -> None:
		result = dashboard_service.get_operational_dashboard_data({"season": "1447", "tour": "TOUR-OLD"})
		get_breakdown.assert_not_called()
		self.assertEqual(result, {"operational_dashboard": {"total_expense_usd": 1}})


class TestExpenseScope(TestCase):
	def test_overhead_excludes_tour_expenses(self) -> None:
		where, params = expense_service._where_clause({"season": "1448"})
		self.assertIn("COALESCE(oe.related_tour, '') = ''", where)
		self.assertNotIn("tour", params)

	def test_tour_filter_selects_that_tours_extras(self) -> None:
		where, params = expense_service._where_clause({"season": "1448", "tour": "TOUR-1"})
		self.assertIn("oe.related_tour = %(tour)s", where)
		self.assertEqual(params["tour"], "TOUR-1")

	def test_draft_count_uses_draft_status(self) -> None:
		_where, params = expense_service._where_clause({"season": "1448"}, status="Draft")
		self.assertEqual(params["status"], "Draft")
