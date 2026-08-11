# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from umre_ops.umre_ops.services.tour_cost_rule_service import apply_tour_hotel_rule_derived_fields


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class TestTourHotelCostRule(TestCase):
	def test_sar_per_usd_rate_is_a_divisor(self) -> None:
		doc = SimpleNamespace(gece_sayisi=5, birim_fiyat_sar=375, kur=3.75)
		apply_tour_hotel_rule_derived_fields(doc)
		self.assertEqual(doc.toplam_oda_maliyeti_usd, 500)
		self.assertEqual(doc.iki_kisilik_oda_maliyeti, 250)

	@patch("umre_ops.umre_ops.services.tour_cost_rule_service.frappe.throw", side_effect=ValueError)
	def test_positive_sar_total_requires_rate(self, _throw) -> None:
		doc = SimpleNamespace(gece_sayisi=1, birim_fiyat_sar=100, kur=0)
		with self.assertRaises(ValueError):
			apply_tour_hotel_rule_derived_fields(doc)
