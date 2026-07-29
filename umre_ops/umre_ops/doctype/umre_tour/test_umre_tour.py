# Copyright (c) 2026, Sermed Turizm and contributors
# See license.txt

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.patches import backfill_umre_tour_season
from umre_ops.umre_ops.doctype.umre_tour.umre_tour import UmreTour


class _TourStub(dict):
	def set(self, fieldname: str, value: str) -> None:
		self[fieldname] = value


class TestUmreTourSeason(TestCase):
	def test_season_metadata_contract(self) -> None:
		meta = json.loads(Path(__file__).with_name("umre_tour.json").read_text())
		season = next(field for field in meta["fields"] if field.get("fieldname") == "season")

		self.assertEqual(season["fieldtype"], "Link")
		self.assertEqual(season["options"], "Umre Season")
		self.assertEqual(season["reqd"], 1)
		self.assertEqual(season["in_list_view"], 1)
		self.assertEqual(season["in_standard_filter"], 1)
		self.assertLess(meta["field_order"].index("season"), meta["field_order"].index("baslangic_tarihi"))

	@patch("umre_ops.umre_ops.services.season_service.get_active_season", return_value="1448")
	def test_before_validate_defaults_active_season(self, _get_active_season: Mock) -> None:
		doc = _TourStub()

		UmreTour.before_validate(doc)

		self.assertEqual(doc["season"], "1448")

	@patch("umre_ops.umre_ops.services.season_service.get_active_season", return_value="1448")
	def test_before_validate_preserves_explicit_season(self, _get_active_season: Mock) -> None:
		doc = _TourStub(season="1447")

		UmreTour.before_validate(doc)

		self.assertEqual(doc["season"], "1447")

	@patch("umre_ops.umre_ops.doctype.umre_tour.umre_tour.frappe.throw", side_effect=ValueError)
	def test_validate_rejects_season_change_on_saved_tour(self, throw: Mock) -> None:
		doc = Mock()
		doc.is_new.return_value = False
		doc.has_value_changed.return_value = True

		with self.assertRaises(ValueError):
			UmreTour.validate(doc)

		doc.has_value_changed.assert_called_once_with("season")
		throw.assert_called_once()

	@patch("umre_ops.umre_ops.doctype.umre_tour.umre_tour.frappe.throw")
	def test_validate_allows_season_on_new_tour(self, throw: Mock) -> None:
		doc = Mock()
		doc.is_new.return_value = True

		UmreTour.validate(doc)

		throw.assert_not_called()
		doc.has_value_changed.assert_not_called()


class TestBackfillUmreTourSeason(TestCase):
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_all", return_value=[])
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.db")
	def test_execute_is_noop_when_no_blank_tours_exist(self, db: Mock, get_all: Mock) -> None:

		backfill_umre_tour_season.execute()

		get_all.assert_called_once()
		db.set_value.assert_not_called()

	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_doc")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_all")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.db")
	def test_execute_assigns_existing_legacy_season(
		self,
		db: Mock,
		get_all: Mock,
		get_doc: Mock,
	) -> None:
		get_all.return_value = [{"name": "Şevval 2026"}]
		db.exists.return_value = "2025-2026 Sezonu"

		backfill_umre_tour_season.execute()

		get_doc.assert_not_called()
		db.set_value.assert_called_once_with(
			"Umre Tour",
			{"name": "Şevval 2026", "season": ["is", "not set"]},
			"season",
			"2025-2026 Sezonu",
			update_modified=False,
		)

	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_doc")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_all")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.db")
	def test_execute_creates_inactive_legacy_season_without_dates(
		self,
		db: Mock,
		get_all: Mock,
		get_doc: Mock,
	) -> None:
		get_all.return_value = [{"name": "Şevval 2026"}]
		db.exists.return_value = None
		inserted = Mock()
		inserted.name = "2025-2026 Sezonu"
		get_doc.return_value.insert.return_value = inserted

		backfill_umre_tour_season.execute()

		get_doc.assert_called_once_with(
			{
				"doctype": "Umre Season",
				"season_name": "2025-2026 Sezonu",
				"is_active": 0,
			}
		)
		get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)
		db.set_value.assert_called_once()

	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_all")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.db")
	def test_execute_is_noop_after_first_assignment(self, db: Mock, get_all: Mock) -> None:
		get_all.side_effect = [[{"name": "Şevval 2026"}], []]
		db.exists.return_value = "2025-2026 Sezonu"

		backfill_umre_tour_season.execute()
		backfill_umre_tour_season.execute()

		db.set_value.assert_called_once_with(
			"Umre Tour",
			{"name": "Şevval 2026", "season": ["is", "not set"]},
			"season",
			"2025-2026 Sezonu",
			update_modified=False,
		)

	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_doc")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.get_all")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.db")
	@patch("umre_ops.patches.backfill_umre_tour_season.frappe.throw", side_effect=ValueError)
	def test_unexpected_blank_tour_stops_before_any_write(
		self,
		throw: Mock,
		db: Mock,
		get_all: Mock,
		get_doc: Mock,
	) -> None:
		get_all.return_value = [
			{"name": "Şevval 2026"},
			{"name": "BEKLENMEYEN-TUR"},
		]

		with self.assertRaises(ValueError):
			backfill_umre_tour_season.execute()

		throw.assert_called_once()
		db.exists.assert_not_called()
		get_doc.assert_not_called()
		db.set_value.assert_not_called()
