# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from umre_ops.umre_ops.report.tour_revenue_summary import tour_revenue_summary as report
from umre_ops.umre_ops.tests.test_dashboard_season_isolation import sample_pnl


class TestTourRevenueSummary(TestCase):
	def setUp(self) -> None:
		patcher = patch.object(report, "_cost_type_labels", return_value={"HOTEL": "Otel Maliyeti"})
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_only_tour_rows_carry_main_columns(self) -> None:
		data = report.get_data(sample_pnl())
		for column in report.TOUR_COLUMNS:
			total = sum(row.get(column) or 0 for row in data)
			tour_total = sum(row.get(column) or 0 for row in data if row["row_kind"] == "tour")
			self.assertEqual(total, tour_total, column)

	def test_cost_detail_rows_sum_to_tour_cost(self) -> None:
		data = report.get_data(sample_pnl())
		tour = next(row for row in data if row["row_kind"] == "tour")
		cost_details = sum(row["detay_tutar"] for row in data if row["row_kind"] == "cost")
		self.assertEqual(cost_details, tour["toplam_maliyet"])

	def test_status_detail_rows_sum_to_passenger_margin(self) -> None:
		data = report.get_data(sample_pnl())
		tour = next(row for row in data if row["row_kind"] == "tour")
		status_net = sum(row["detay_tutar"] for row in data if row["row_kind"] == "status")
		self.assertEqual(status_net, tour["net_satis"] - tour["yolcu_maliyeti"])

	def test_summary_shows_season_result(self) -> None:
		labels = {card["label"]: card["value"] for card in report.get_report_summary(sample_pnl())}
		self.assertEqual(labels["Tur Kârı"], 500)
		self.assertEqual(labels["Ofis Genel Gideri"], 200)
		self.assertEqual(labels["Sezon Sonucu"], 300)
