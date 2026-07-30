# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from umre_ops.umre_ops.services.excel_import_service import (
	enqueue_import,
	run_dry_run,
)
from umre_ops.umre_ops.services.excel_import_service import (
	get_worksheet_names as get_import_worksheet_names,
)


class UmreExcelImport(Document):
	def validate(self) -> None:
		if self.import_file and not str(self.import_file).lower().endswith(
			(".xlsx", ".xlsm", ".xltx", ".xltm")
		):
			frappe.throw(_("Lütfen geçerli bir Excel (.xlsx) dosyası yükleyin."))
		self._invalidate_stale_validation()

	def _invalidate_stale_validation(self) -> None:
		"""A validation result belongs to one exact file, target tour and worksheet."""
		if self.is_new() or self.flags.ignore_import_source_guard:
			return
		persisted = frappe.db.get_value(
			"Umre Excel Import",
			self.name,
			["import_file", "target_tour", "worksheet_name", "status"],
			as_dict=True,
		)
		if not persisted:
			return
		if persisted.status == "Completed" and self.status != "Completed":
			frappe.throw(_("Tamamlanmış bir aktarımın durumu değiştirilemez. Yeni bir kayıt oluşturun."))
		input_changed = any(
			(
				self.import_file != persisted.import_file,
				self.target_tour != persisted.target_tour,
				self.worksheet_name != persisted.worksheet_name,
			)
		)
		if not input_changed:
			return
		if persisted.status in {"Queued", "Processing", "Completed"}:
			frappe.throw(
				_(
					"Kuyruktaki, işlenen veya tamamlanmış bir aktarımın dosyası, hedef turu ya da Excel sayfası değiştirilemez."
				)
			)
		if persisted.status in {"Validated", "Failed"}:
			self.status = "Draft"
			self.validation_signature = None
			self.total_rows = 0
			self.created_umreci = 0
			self.updated_umreci = 0
			self.created_bookings = 0
			self.updated_bookings = 0
			self.row_errors = 0
			self.dry_run_result = None
			self.row_log = None
			self.error_log = None
			self.started_at = None
			self.completed_at = None


@frappe.whitelist()
def get_worksheet_names(docname: str) -> list[str]:
	"""Return sheet names for the saved import document's attached file."""
	doc = frappe.get_doc("Umre Excel Import", docname)
	doc.check_permission("read")
	return get_import_worksheet_names(doc)


@frappe.whitelist()
def validate_import(docname: str) -> dict:
	"""Run validation/dry-run synchronously and store the row-level preview."""
	_doc = frappe.get_doc("Umre Excel Import", docname)
	_doc.check_permission("write")
	if _doc.status in {"Queued", "Processing", "Completed"}:
		frappe.throw(_("Kuyruktaki, işlenen veya tamamlanmış bir aktarım yeniden doğrulanamaz."))
	return run_dry_run(docname)


@frappe.whitelist()
def start_import(docname: str) -> dict:
	"""Queue the actual import so Desk is not blocked by large Excel files."""
	_doc = frappe.get_doc("Umre Excel Import", docname)
	_doc.check_permission("write")
	if _doc.status in {"Queued", "Processing"} and _doc.job_id:
		return enqueue_import(docname, user=frappe.session.user)
	if _doc.status != "Validated" or cint(_doc.row_errors):
		frappe.throw(_("Aktarımı başlatmadan önce hatasız bir kuru çalıştırma yapın."))
	return enqueue_import(docname, user=frappe.session.user)
