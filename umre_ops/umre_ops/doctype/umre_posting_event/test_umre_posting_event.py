# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from umre_ops.umre_ops.services.idempotency_service import ensure_event_started, get_existing_result
from umre_ops.umre_ops.tests.ci_company_bootstrap import get_or_create_test_company


class TestUmrePostingEventIdempotency(FrappeTestCase):
	"""
	Database integration test for idempotency only.

	Uses FrappeTestCase (not IntegrationTestCase) so Frappe does not build the full
	Link-dependency test-record tree: with ERPNext installed, `make_test_records` for
	`Umre Posting Event` would recurse through Company and a large part of the ERP graph.
	We instead rely on `get_or_create_test_company()` and explicit service calls.
	"""

	def test_idempotency_event_reuse(self) -> None:
		company = get_or_create_test_company()
		key = "TEST::UMRE::IDEMPOTENCY::1"
		payload = {"a": 1, "b": "x"}

		event_name_1, h1 = ensure_event_started(
			idempotency_key=key,
			operation="TEST_OP",
			company=company,
			source_doctype="Umre Booking",
			source_name="TEST-BOOKING",
			request_payload=payload,
		)
		event_name_2, h2 = ensure_event_started(
			idempotency_key=key,
			operation="TEST_OP",
			company=company,
			source_doctype="Umre Booking",
			source_name="TEST-BOOKING",
			request_payload=payload,
		)
		self.assertEqual(event_name_1, event_name_2)
		self.assertEqual(h1, h2)

		existing = get_existing_result(key)
		self.assertIsNotNone(existing)
		self.assertEqual(existing.event_name, event_name_1)

