# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from umre_ops.umre_ops.services.booking_calculation_service import apply_to_booking


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
# Avoid pulling in ERPNext's full Company/Accounts test suite just because
# Umre Booking has link fields. Our tests here are focused on service logic.
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Company",
	"Customer",
	"Currency",
	"Mode of Payment",
	"Payment Entry",
	"Journal Entry",
	"Umre Booking Payment",
]  # eg. ["User"]



class IntegrationTestUmreBooking(IntegrationTestCase):
	"""
	Integration tests for UmreBooking.
	Use this class for testing interactions between multiple components.
	"""

	def test_recalc_vize_tipi_default_without_tour(self) -> None:
		# API / import / partial doc: same path as form validate()
		b = frappe._dict(doctype="Umre Booking", vize_tipi=None, tur=None)
		apply_to_booking(b)
		self.assertEqual(b.vize_tipi, "Umre")
		self.assertEqual(b.get("toplam_maliyet", 0), 0)
		self.assertEqual(b.get("kar", 0), 0)
