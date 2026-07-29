# Copyright (c) 2026, Sermed Turizm and contributors

import json

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("payment-date-repair")
@click.option("--csv", "csv_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--apply", "apply_changes", is_flag=True, default=False, help="Apply the validated repair batch")
@click.option("--expected-sha256", help="Exact batch hash returned by the dry-run")
@pass_context
def payment_date_repair(context, csv_path: str, apply_changes: bool, expected_sha256: str | None) -> None:
	"""Validate or apply an auditable payment-date repair CSV."""
	from umre_ops.umre_ops.services.payment_date_reconciliation import repair_payment_dates

	site = get_site(context)
	try:
		frappe.init(site)
		frappe.connect()
		frappe.set_user("Administrator")
		result = repair_payment_dates(csv_path, apply=apply_changes, expected_sha256=expected_sha256)
		if apply_changes:
			frappe.db.commit()
		click.echo(json.dumps(result, ensure_ascii=False, default=str, indent=2))
	except Exception:
		if frappe.db:
			frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


commands = [payment_date_repair]
