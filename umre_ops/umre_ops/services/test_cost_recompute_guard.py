from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services import cost_engine


class TestCostRecomputeGuard(TestCase):
	def test_submitted_cost_journal_protects_component_snapshot(self) -> None:
		db = Mock()
		db.get_value.side_effect = ["ACC-JV-1", 1]
		with patch.object(cost_engine.frappe, "db", db):
			self.assertTrue(cost_engine._has_submitted_cost_posting("BOOK-1"))

	def test_cancelled_cost_journal_allows_recompute(self) -> None:
		db = Mock()
		db.get_value.side_effect = ["ACC-JV-1", 2]
		with patch.object(cost_engine.frappe, "db", db):
			self.assertFalse(cost_engine._has_submitted_cost_posting("BOOK-1"))
