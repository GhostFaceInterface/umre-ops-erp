# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
`Cost Type` master.

Adding a new cost type is a UI / data operation, not a code change. The
`cost_type_code` is the stable upper-case key used by the cost engine and the
report breakdown. `is_system_managed = 1` marks types that are auto-created
on booking insert; ad-hoc types (e.g. INSURANCE, TRANSFER) can be added by
ops without touching code, and used as MANUAL-style components.
"""
from frappe.model.document import Document


class CostType(Document):
	pass
