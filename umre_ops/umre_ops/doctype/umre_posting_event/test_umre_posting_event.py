# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from umre_ops.umre_ops.services.idempotency_service import ensure_event_started, get_existing_result
from umre_ops.umre_ops.tests.ci_company_bootstrap import get_or_create_test_company


EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestUmrePostingEvent(IntegrationTestCase):
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

