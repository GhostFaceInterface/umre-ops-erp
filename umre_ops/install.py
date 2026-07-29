# Copyright (c) 2026, Sermed Turizm and contributors

"""Fresh-install bootstrap for state normally introduced by upgrade patches."""

from umre_ops.patches.create_accounting_custom_fields import execute as ensure_accounting_custom_fields


def after_install() -> None:
	# Frappe records upgrade patches as completed on a fresh app install. These
	# standard-DocType fields therefore need an explicit fresh-install path too.
	ensure_accounting_custom_fields()
