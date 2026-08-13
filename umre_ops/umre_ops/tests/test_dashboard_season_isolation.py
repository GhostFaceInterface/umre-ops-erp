# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services import dashboard_service, expense_service


class TestDashboardSeasonIsolation(TestCase):
	def test_configured_items_are_direct_rule_rows_without_synthetic_types(self) -> None:
		def get_all(doctype: str, **_kwargs):
			return {
				"Tour Hotel Cost Rule": [
					{
						"name": "H-M", "tur": "T-1", "lokasyon": "Mekke",
						"gece_sayisi": 5, "birim_fiyat_sar": 375, "kur": 3.75,
					},
					{
						"name": "H-D", "tur": "T-1", "lokasyon": "Medine",
						"gece_sayisi": 3, "birim_fiyat_sar": 300, "kur": 3.75,
					},
				],
				"Tour Airfare Cost Rule": [
					{"name": "A-1", "tur": "T-1", "yolcu_tipi": "Normal", "tutar": 400}
				],
				"Tour Visa Cost Rule": [],
				"Tour Diyanet Card Rule": [],
				"Meal Cost Rule": [
					{
						"name": "M-1", "tour": "T-1", "mekke_price_sar": 30,
						"medine_price_sar": 20, "sar_to_usd_rate": 3.75,
					}
				],
				"Other Cost Rule": [],
			}[doctype]

		with patch.object(dashboard_service.frappe, "get_all", side_effect=get_all):
			items = dashboard_service._configured_cost_items("1448", "T-1")

		self.assertEqual([row["source_name"] for row in items], ["H-M", "H-D", "A-1", "M-1"])
		self.assertEqual([row["value"] for row in items], [500, 240, 400, 56])
		self.assertTrue(all(row["currency"] == "USD" for row in items))

	def test_booking_metrics_always_filters_selected_season(self) -> None:
		db = Mock()
		db.sql.return_value = []
		with patch.object(dashboard_service.frappe, "db", db):
			dashboard_service._booking_metrics("1448", None, "ACME")

		query, params = db.sql.call_args.args[:2]
		self.assertIn("JOIN `tabUmre Tour` t ON t.name = b.tur", query)
		self.assertIn("t.season = %(season)s", query)
		self.assertNotIn("b.tur = %(tour)s", query)
		self.assertEqual(params, {"season": "1448", "company": "ACME"})

	def test_booking_metrics_adds_optional_tour_filter(self) -> None:
		db = Mock()
		db.sql.return_value = []
		with patch.object(dashboard_service.frappe, "db", db):
			dashboard_service._booking_metrics("1448", "TOUR-1", "ACME")

		query, params = db.sql.call_args.args[:2]
		self.assertIn("b.tur = %(tour)s", query)
		self.assertEqual(params, {"season": "1448", "tour": "TOUR-1", "company": "ACME"})

	def test_actual_component_totals_group_real_usd_components(self) -> None:
		db = Mock()
		db.sql.return_value = [{"cost_type": "HOTEL", "total": 125}, {"cost_type": "MEAL", "total": 25}]
		with patch.object(dashboard_service.frappe, "db", db):
			result = dashboard_service._actual_component_totals("1448", "TOUR-1", "ACME")
		query, params = db.sql.call_args.args[:2]
		self.assertIn("GROUP BY c.cost_type", query)
		self.assertIn("c.currency = %(currency)s", query)
		self.assertEqual(params["currency"], "USD")
		self.assertEqual(result, {"HOTEL": 125, "MEAL": 25})

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

	def test_payload_sum_invariant_and_invalid_financial_kpis(self) -> None:
		booking = {"kisi_sayisi": 2, "umreci_count": 2, "non_umreci_count": 0,
			"gelir": 1000, "tahsil_edilen": 0}
		common = (
			patch.object(dashboard_service, "require_doctype_permission"),
			patch.object(dashboard_service, "_assert_usd_tours"),
			patch.object(dashboard_service, "_company_context", return_value="ACME"),
			patch.object(dashboard_service, "_booking_metrics", return_value=booking),
			patch.object(dashboard_service, "_configured_cost_items", return_value=[]),
			patch.object(
				dashboard_service, "_actual_component_totals",
				return_value={"HOTEL": 100, "MEAL": 25},
			),
			patch.object(dashboard_service, "get_active_season", return_value="1448"),
			patch.object(dashboard_service, "_list_season_options", return_value=[]),
			patch.object(dashboard_service, "_list_tour_options", return_value=[]),
		)
		for manager in common:
			manager.start()
		self.addCleanup(lambda: [manager.stop() for manager in reversed(common)])
		with patch.object(dashboard_service.frappe.db, "exists", return_value=True), patch.object(
			dashboard_service, "_component_integrity_warnings", return_value=[]
		):
			valid = dashboard_service.get_tour_cost_breakdown("1448")
		self.assertEqual(valid["kpis"]["total_cost"], sum(row["value"] for row in valid["cost_breakdown"]))
		with patch.object(dashboard_service.frappe.db, "exists", return_value=True), patch.object(
			dashboard_service, "_component_integrity_warnings",
			return_value=[{"code": "NON_USD_COMPONENT", "booking": "B-1", "message": "bad"}],
		):
			invalid = dashboard_service.get_tour_cost_breakdown("1448")
		self.assertFalse(invalid["financial_data_valid"])
		self.assertIsNone(invalid["kpis"]["total_cost"])
		self.assertIsNone(invalid["kpis"]["net_profit"])
		self.assertIsNone(invalid["performance"]["cost_per_person"])

	@patch.object(dashboard_service, "require_doctype_permission")
	@patch.object(dashboard_service, "_assert_usd_tours")
	@patch.object(dashboard_service, "_company_context", return_value="ACME")
	@patch.object(dashboard_service, "_component_integrity_warnings", return_value=[])
	@patch.object(dashboard_service, "_actual_component_totals", return_value={})
	@patch.object(dashboard_service, "_configured_cost_items", return_value=[])
	@patch.object(
		dashboard_service,
		"_booking_metrics",
		return_value={
			"kisi_sayisi": 0,
			"umreci_count": 0,
			"non_umreci_count": 0,
			"gelir": 0,
			"tahsil_edilen": 0,
		},
	)
	@patch.object(dashboard_service, "get_active_season", return_value="1448")
	def test_empty_season_defaults_active_and_returns_dependent_options(
		self,
		_get_active_season: Mock,
		_booking_metrics: Mock,
		_configured_cost_items: Mock,
		_actual_component_totals: Mock,
		_component_integrity_warnings: Mock,
		_company_context: Mock,
		_assert_usd_tours: Mock,
		_permission: Mock,
	) -> None:
		def get_all(doctype: str, **_kwargs):
			if doctype == "Umre Season":
				return [{"name": "1448", "season_name": "1448 Hicri"}]
			return [{"name": "TOUR-1", "tur_adi": "Ramazan", "tur_kodu": "R1"}]

		db = Mock()
		db.exists.return_value = True
		with (
			patch.object(dashboard_service.frappe, "db", db),
			patch.object(dashboard_service.frappe, "get_all", side_effect=get_all) as get_all_mock,
		):
			result = dashboard_service.get_tour_cost_breakdown()

		self.assertEqual(result["selected_season"], "1448")
		self.assertEqual(result["active_season"], "1448")
		self.assertEqual(result["seasons"], [{"name": "1448", "label": "1448 Hicri"}])
		self.assertEqual(result["tours"], [{"name": "TOUR-1", "label": "Ramazan"}])
		_booking_metrics.assert_called_once_with("1448", None, "ACME")
		_configured_cost_items.assert_called_once_with("1448", None)
		_actual_component_totals.assert_called_once_with("1448", None, "ACME")
		_component_integrity_warnings.assert_called_once_with("1448", None, "ACME")
		_assert_usd_tours.assert_called_once_with("1448", None)
		tour_call = next(call for call in get_all_mock.call_args_list if call.args[0] == "Umre Tour")
		self.assertEqual(tour_call.kwargs["filters"], {"season": "1448"})

	@patch.object(dashboard_service, "require_doctype_permission")
	@patch.object(dashboard_service, "get_operational_dashboard_summary", return_value={})
	@patch.object(dashboard_service, "get_tour_cost_breakdown", return_value={})
	def test_combined_endpoint_passes_season_to_tour_dashboard(
		self,
		get_breakdown: Mock,
		_summary: Mock,
		_permission: Mock,
	) -> None:
		dashboard_service.get_operational_dashboard_data({"season": "1447", "tour": "TOUR-OLD"})

		get_breakdown.assert_called_once_with(season="1447", tour="TOUR-OLD")

	@patch.object(expense_service, "require_doctype_permission")
	@patch.object(expense_service, "get_operational_dashboard_summary", return_value={})
	@patch.object(dashboard_service, "get_tour_cost_breakdown", return_value={})
	def test_expense_combined_endpoint_passes_season_to_tour_dashboard(
		self,
		get_breakdown: Mock,
		_summary: Mock,
		_permission: Mock,
	) -> None:
		expense_service.get_operational_dashboard_data({"season": "1447", "tour": "TOUR-OLD"})

		get_breakdown.assert_called_once_with(season="1447", tour="TOUR-OLD")
