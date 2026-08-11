from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.doctype.tour_airfare_cost_rule.tour_airfare_cost_rule import TourAirfareCostRule


class TestTourAirfareCostRule(TestCase):
	@patch("umre_ops.umre_ops.doctype.tour_airfare_cost_rule.tour_airfare_cost_rule.apply_tour_season")
	def test_validate_enforces_tour_season_and_usd(self, apply_tour_season: Mock) -> None:
		doc = TourAirfareCostRule({"doctype": "Tour Airfare Cost Rule", "para_birimi": "TRY"})
		doc.validate()
		apply_tour_season.assert_called_once_with(doc, tour_fieldname="tur")
		self.assertEqual(doc.para_birimi, "USD")
