# Copyright (c) 2026, Sermed Turizm and contributors
"""Seed the fixed operational expense taxonomy.

The patch is idempotent and never deletes user data. Legacy generic categories
are mapped to the nearest leaf item where possible, then left inactive so they
do not appear in the new entry flow.
"""
from __future__ import annotations

import frappe


TAXONOMY = (
	(
		"PAZARLAMA SATIŞ VE DAĞITIM GİDERLERİ",
		(
			"Hocalara ödenen komisyon",
			"Reklamlar",
		),
	),
	(
		"GENEL YÖNETİM GİDERLERİ",
		(
			"Diğer genel yönetim giderleri",
		),
	),
	(
		"Ofis Giderleri",
		(
			"Bilişim teknolojileri ve yapay zeka",
			"Doğalgaz",
			"Elektrik",
			"Kira",
			"Ofise ait diğer giderler",
			"Su",
			"Yemek - Gıda",
			"İnternet erişimi",
		),
	),
	("PERSONEL GİDERLERİ", ("Personel Maaşı",)),
	(
		"VERGİLER",
		(
			"0003 GELİR VERGİSİ S. (MUHTASAR)",
			"0010 KURUMLAR VERGİSİ",
			"0015 GERÇEK USULDE KATMA DEĞER VERGİSİ",
			"0068 7183 SY. KANUNUN 6. MADDESİNİN 3. FIKRASINA GÖRE ALINAN TURİZM PAYI (%95)",
		),
	),
)

LEGACY_CATEGORY_MAP = {
	"Ofis Giderleri": "Ofise ait diğer giderler",
	"Kira": "Kira",
	"Elektrik": "Elektrik",
	"Su": "Su",
	"Doğalgaz": "Doğalgaz",
	"İnternet": "İnternet erişimi",
	"Personel Giderleri": "Personel Maaşı",
	"Pazarlama": "Reklamlar",
	"Reklam": "Reklamlar",
	"Vergiler": "0015 GERÇEK USULDE KATMA DEĞER VERGİSİ",
	"IT / Yazılım": "Bilişim teknolojileri ve yapay zeka",
	"Diğer Giderler": "Diğer genel yönetim giderleri",
	"Diyanet kart ödemesi": "Diğer genel yönetim giderleri",
	"Operasyon anındaki diğer harcamalar": "Diğer genel yönetim giderleri",
	"Otel": "Diğer genel yönetim giderleri",
	"Uçak": "Diğer genel yönetim giderleri",
	"Vize": "Diğer genel yönetim giderleri",
}


def execute():
	if not frappe.db.exists("DocType", "Operational Expense Category"):
		return

	canonical = set()
	sort = 10
	for main_label, children in TAXONOMY:
		main_name = ensure_category(main_label, None, is_group=1, sort_order=sort)
		canonical.add(main_name)
		child_sort = sort + 10
		for child in children:
			if isinstance(child, tuple):
				group_label, leaves = child
				group_name = ensure_category(group_label, main_name, is_group=1, sort_order=child_sort)
				canonical.add(group_name)
				leaf_sort = child_sort + 10
				for leaf in leaves:
					leaf_name = ensure_category(leaf, group_name, is_group=0, sort_order=leaf_sort)
					canonical.add(leaf_name)
					leaf_sort += 10
			else:
				child_name = ensure_category(child, main_name, is_group=0, sort_order=child_sort)
				canonical.add(child_name)
			child_sort += 100
		sort += 1000

	_copy_legacy_expense_category_values()
	_migrate_legacy_categories()
	_disable_noncanonical_categories(canonical)
	_default_settings_active_season()
	frappe.db.commit()


def ensure_category(label: str, parent: str | None, is_group: int, sort_order: int) -> str:
	existing = frappe.db.exists("Operational Expense Category", label)
	if not existing:
		frappe.get_doc(
			{
				"doctype": "Operational Expense Category",
				"category_name": label,
				"parent_category": parent,
				"is_group": is_group,
				"is_active": 1,
				"sort_order": sort_order,
			}
		).insert(ignore_permissions=True)
		return label

	frappe.db.set_value(
		"Operational Expense Category",
		existing,
		{
			"category_name": label,
			"parent_category": parent,
			"is_group": is_group,
			"is_active": 1,
			"sort_order": sort_order,
		},
		update_modified=False,
	)
	return existing


def _copy_legacy_expense_category_values() -> None:
	if not frappe.db.exists("DocType", "Operational Expense"):
		return
	if not frappe.db.has_column("Operational Expense", "category"):
		return
	if not frappe.db.has_column("Operational Expense", "expense_category"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabOperational Expense`
		SET expense_category = category
		WHERE IFNULL(expense_category, '') = '' AND IFNULL(category, '') != ''
		"""
	)


def _migrate_legacy_categories() -> None:
	if not frappe.db.exists("DocType", "Operational Expense"):
		return
	for old_label, new_label in LEGACY_CATEGORY_MAP.items():
		if old_label == new_label or not frappe.db.exists("Operational Expense Category", new_label):
			continue
		frappe.db.sql(
			"""
			UPDATE `tabOperational Expense`
			SET expense_category = %s
			WHERE expense_category = %s
			""",
			(new_label, old_label),
		)
		if frappe.db.has_column("Operational Expense", "category"):
			frappe.db.sql(
				"""
				UPDATE `tabOperational Expense`
				SET category = %s
				WHERE category = %s
				""",
				(new_label, old_label),
			)


def _disable_noncanonical_categories(canonical: set[str]) -> None:
	rows = frappe.get_all("Operational Expense Category", pluck="name", limit_page_length=0)
	for name in rows:
		if name in canonical:
			continue
		frappe.db.set_value(
			"Operational Expense Category",
			name,
			"is_active",
			0,
			update_modified=False,
		)


def _default_settings_active_season() -> None:
	if not frappe.db.exists("DocType", "Umre Ops Settings"):
		return
	if frappe.db.get_single_value("Umre Ops Settings", "active_season"):
		return
	seasons = frappe.get_all(
		"Umre Season",
		filters={"is_active": 1},
		pluck="name",
		order_by="start_date desc, modified desc",
		limit=1,
	)
	if seasons:
		frappe.db.set_single_value("Umre Ops Settings", "active_season", seasons[0])
