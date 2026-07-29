# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.exceptions import PermissionError


def require_doctype_permission(doctype: str, permission_type: str) -> None:
	"""Enforce a DocType permission before a whitelisted service reads or writes."""
	if frappe.has_permission(doctype, permission_type, throw=False):
		return
	frappe.throw(
		_("Not permitted to {0} {1}.").format(permission_type, doctype),
		exc=PermissionError,
	)


def require_document_permission(doc, permission_type: str) -> None:
	"""Enforce document-level permission, including user-permission constraints."""
	doc.check_permission(permission_type)
