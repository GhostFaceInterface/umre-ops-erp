# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

import json
from pathlib import Path
from unittest import TestCase

from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestUmreci(IntegrationTestCase):
	"""
	Integration tests for Umreci.
	Use this class for testing interactions between multiple components.
	"""

	pass


class TestUmreciTourHistory(TestCase):
	def test_metadata_has_dynamic_history_html(self) -> None:
		meta = json.loads(Path(__file__).with_name("umreci.json").read_text())
		field = next(item for item in meta["fields"] if item.get("fieldname") == "tur_gecmisi_html")
		self.assertEqual(field["fieldtype"], "HTML")
		self.assertIn("tur_gecmisi_html", meta["field_order"])
