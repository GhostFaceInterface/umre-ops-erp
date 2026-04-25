# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document

from umre_ops.umre_ops.services.excel_import_service import enqueue_import, run_dry_run


class UmreExcelImport(Document):
	def validate(self) -> None:
		if self.import_file and not str(self.import_file).lower().endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
			frappe.throw("Please attach an Excel .xlsx file.")


@frappe.whitelist()
def validate_import(docname: str) -> dict:
	"""Run validation/dry-run synchronously and store the row-level preview."""
	_doc = frappe.get_doc("Umre Excel Import", docname)
	_doc.check_permission("write")
	return run_dry_run(docname)


@frappe.whitelist()
def start_import(docname: str) -> dict:
	"""Queue the actual import so Desk is not blocked by large Excel files."""
	_doc = frappe.get_doc("Umre Excel Import", docname)
	_doc.check_permission("write")
	return enqueue_import(docname, user=frappe.session.user)
