# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from umre_ops.umre_ops.services.excel_import_service import enqueue_import, run_dry_run


class UmreExcelImport(Document):
	def validate(self) -> None:
		if self.import_file and not str(self.import_file).lower().endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
			frappe.throw(_("Please attach an Excel .xlsx file."))
		self._invalidate_stale_validation()

	def _invalidate_stale_validation(self) -> None:
		"""A validation result belongs to one exact file reference and target tour."""
		if self.is_new() or self.status not in {"Validated", "Queued"}:
			return
		persisted = frappe.db.get_value(
			"Umre Excel Import",
			self.name,
			["import_file", "target_tour"],
			as_dict=True,
		)
		if not persisted:
			return
		if self.import_file != persisted.import_file or self.target_tour != persisted.target_tour:
			self.status = "Draft"
			self.row_errors = 0
			self.dry_run_result = None
			self.row_log = None


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
	if _doc.status != "Validated" or cint(_doc.row_errors):
		frappe.throw(_("Run a successful dry-run with zero row errors before starting the import."))
	return enqueue_import(docname, user=frappe.session.user)
