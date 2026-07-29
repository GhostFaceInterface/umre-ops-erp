# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services import dashboard_service, expense_service


class TestDashboardSeasonIsolation(TestCase):
	def test_booking_metrics_always_filters_selected_season(self) -> None:
		db = Mock()
		db.sql.return_value = []
		with patch.object(dashboard_service.frappe, "db", db):
			dashboard_service._booking_metrics("1448", None)

		query, params = db.sql.call_args.args[:2]
		self.assertIn("JOIN `tabUmre Tour` t ON t.name = b.tur", query)
		self.assertIn("t.season = %(season)s", query)
		self.assertNotIn("b.tur = %(tour)s", query)
		self.assertEqual(params, {"season": "1448"})

	def test_booking_metrics_adds_optional_tour_filter(self) -> None:
		db = Mock()
		db.sql.return_value = []
		with patch.object(dashboard_service.frappe, "db", db):
			dashboard_service._booking_metrics("1448", "TOUR-1")

		query, params = db.sql.call_args.args[:2]
		self.assertIn("b.tur = %(tour)s", query)
		self.assertEqual(params, {"season": "1448", "tour": "TOUR-1"})

	def test_component_rollup_always_filters_selected_season_and_tour(self) -> None:
		db = Mock()
		db.sql.return_value = []
		with patch.object(dashboard_service.frappe, "db", db):
			dashboard_service._component_rollup("1448", "TOUR-1")

		query, params = db.sql.call_args.args[:2]
		self.assertIn("JOIN `tabUmre Tour` t ON t.name = b.tur", query)
		self.assertIn("t.season = %(season)s", query)
		self.assertIn("b.tur = %(tour)s", query)
		self.assertEqual(params, {"season": "1448", "tour": "TOUR-1"})

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
	@patch.object(dashboard_service, "_component_rollup", return_value=({}, []))
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
		_component_rollup: Mock,
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
		_booking_metrics.assert_called_once_with("1448", None)
		_component_rollup.assert_called_once_with("1448", None)
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
