# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from umre_ops.umre_ops.services.excel_import_service import (
	create_referral as create_import_referral,
)
from umre_ops.umre_ops.services.excel_import_service import (
	enqueue_import,
	run_dry_run,
)
from umre_ops.umre_ops.services.excel_import_service import (
	inspect_headers as inspect_import_headers,
)
from umre_ops.umre_ops.services.excel_import_service import (
	resolve_referral as resolve_import_referral,
)


class UmreExcelImport(Document):
	def validate(self) -> None:
		if self.import_file and not str(self.import_file).lower().endswith(
			(".xlsx", ".xlsm", ".xltx", ".xltm")
		):
			frappe.throw(_("Lütfen geçerli bir Excel (.xlsx) dosyası yükleyin."))
		self._invalidate_stale_validation()

	def _invalidate_stale_validation(self) -> None:
		"""A validation result belongs to one exact file, tour, header row and mapping."""
		if self.is_new() or self.flags.ignore_import_source_guard:
			return
		persisted = frappe.get_doc("Umre Excel Import", self.name)
		if not persisted:
			return
		if persisted.status == "Completed" and self.status != "Completed":
			frappe.throw(_("Tamamlanmış bir aktarımın durumu değiştirilemez. Yeni bir kayıt oluşturun."))
		mapping = [(row.target_field, row.source_column) for row in self.get("column_mappings") or []]
		old_mapping = [
			(row.target_field, row.source_column) for row in persisted.get("column_mappings") or []
		]
		input_changed = (
			self.import_file != persisted.import_file
			or self.target_tour != persisted.target_tour
			or cint(self.header_row or 1) != cint(persisted.header_row or 1)
			or mapping != old_mapping
		)
		if not input_changed:
			return
		if persisted.status in {"Queued", "Processing", "Partially Completed", "Completed"}:
			frappe.throw(
				_("Kuyruktaki, işlenen veya tamamlanmış bir aktarımın kaynağı ya da eşlemesi değiştirilemez.")
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
			self.set("staged_rows", [])


@frappe.whitelist()
def inspect_headers(docname: str) -> list[str]:
	"""Return the selected header row from a workbook that contains exactly one sheet."""
	doc = frappe.get_doc("Umre Excel Import", docname)
	doc.check_permission("read")
	return inspect_import_headers(doc)


@frappe.whitelist()
def resolve_referral(docname: str, referral_text: str, referral_source: str) -> None:
	resolve_import_referral(docname, referral_text, referral_source)


@frappe.whitelist()
def create_referral(docname: str, referral_text: str) -> str:
	return create_import_referral(docname, referral_text)


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
