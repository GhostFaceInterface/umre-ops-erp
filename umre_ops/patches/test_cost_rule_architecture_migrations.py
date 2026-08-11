from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.patches import (
	add_cost_rule_unique_constraints,
	backfill_cost_rule_seasons_from_tours,
	rename_tour_passenger_to_airfare_rule,
)


class TestAirfareRuleRename(TestCase):
	@patch.object(rename_tour_passenger_to_airfare_rule.frappe, "rename_doc")
	def test_renames_only_when_old_exists(self, rename_doc: Mock) -> None:
		db = Mock()
		db.exists.side_effect = lambda _doctype, name: name != "Tour Airfare Cost Rule"
		db.has_column.return_value = False
		db.count.return_value = 0
		db.sql.return_value = []
		with patch.object(rename_tour_passenger_to_airfare_rule.frappe, "db", db):
			rename_tour_passenger_to_airfare_rule.execute()
		rename_doc.assert_called_once_with(
			"DocType", "Tour Passenger Cost Rule", "Tour Airfare Cost Rule", force=True
		)

	@patch.object(rename_tour_passenger_to_airfare_rule.frappe, "rename_doc")
	def test_is_idempotent_after_rename(self, rename_doc: Mock) -> None:
		db = Mock()
		db.exists.side_effect = [False, True]
		with patch.object(rename_tour_passenger_to_airfare_rule.frappe, "db", db):
			rename_tour_passenger_to_airfare_rule.execute()
		rename_doc.assert_not_called()

	@patch.object(rename_tour_passenger_to_airfare_rule.frappe, "rename_doc")
	def test_non_airfare_rows_stop_before_rename(self, rename_doc: Mock) -> None:
		db = Mock()
		db.exists.side_effect = lambda _doctype, name: name != "Tour Airfare Cost Rule"
		db.has_column.return_value = True
		db.sql.return_value = [{"name": "R-1", "tur": "T-1", "expense_component": "Otel"}]
		with (
			patch.object(rename_tour_passenger_to_airfare_rule.frappe, "db", db),
			patch.object(rename_tour_passenger_to_airfare_rule.frappe, "throw", side_effect=ValueError),
			self.assertRaises(ValueError),
		):
			rename_tour_passenger_to_airfare_rule.execute()
		rename_doc.assert_not_called()


class TestCostRuleUniquePreflight(TestCase):
	def test_duplicate_preflight_writes_no_indexes(self) -> None:
		db = Mock()
		db.exists.return_value = True
		with (
			patch.object(add_cost_rule_unique_constraints, "UNIQUE_RULES", (("Rule", ("tour",), "uniq"),)),
			patch.object(add_cost_rule_unique_constraints, "_duplicates", return_value=[{"tour": "T-1", "row_count": 2}]),
			patch.object(add_cost_rule_unique_constraints.frappe, "db", db),
			patch.object(add_cost_rule_unique_constraints.frappe, "throw", side_effect=ValueError),
			self.assertRaises(ValueError),
		):
			add_cost_rule_unique_constraints.execute()
		db.add_unique.assert_not_called()


class TestCostRuleSeasonBackfill(TestCase):
	def test_preflights_every_row_before_writing(self) -> None:
		db = Mock()
		db.exists.return_value = True
		db.get_value.return_value = None
		with (
			patch.object(backfill_cost_rule_seasons_from_tours, "RULES", (("Rule", "tour"),)),
			patch.object(
				backfill_cost_rule_seasons_from_tours.frappe,
				"get_all",
				return_value=[{"name": "R-1", "tour": "T-1", "season": "S-OLD"}],
			),
			patch.object(backfill_cost_rule_seasons_from_tours.frappe, "db", db),
			patch.object(backfill_cost_rule_seasons_from_tours.frappe, "throw", side_effect=ValueError),
			self.assertRaises(ValueError),
		):
			backfill_cost_rule_seasons_from_tours.execute()
		db.set_value.assert_not_called()

	def test_updates_mismatch_and_second_run_is_noop(self) -> None:
		db = Mock()
		db.exists.return_value = True
		db.get_value.return_value = "S-1"
		rows = [{"name": "R-1", "tour": "T-1", "season": "S-OLD"}]
		with (
			patch.object(backfill_cost_rule_seasons_from_tours, "RULES", (("Rule", "tour"),)),
			patch.object(backfill_cost_rule_seasons_from_tours.frappe, "get_all", return_value=rows),
			patch.object(backfill_cost_rule_seasons_from_tours.frappe, "db", db),
		):
			backfill_cost_rule_seasons_from_tours.execute()
		db.set_value.assert_called_once_with("Rule", "R-1", "season", "S-1", update_modified=False)

		db.reset_mock()
		db.exists.return_value = True
		db.get_value.return_value = "S-1"
		with (
			patch.object(backfill_cost_rule_seasons_from_tours, "RULES", (("Rule", "tour"),)),
			patch.object(
				backfill_cost_rule_seasons_from_tours.frappe,
				"get_all",
				return_value=[{"name": "R-1", "tour": "T-1", "season": "S-1"}],
			),
			patch.object(backfill_cost_rule_seasons_from_tours.frappe, "db", db),
		):
			backfill_cost_rule_seasons_from_tours.execute()
		db.set_value.assert_not_called()
