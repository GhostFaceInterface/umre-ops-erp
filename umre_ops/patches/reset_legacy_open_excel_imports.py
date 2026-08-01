"""Reset non-terminal imports created by the retired worksheet-selection workflow."""

import frappe


def execute() -> None:
	if not frappe.db.table_exists("Umre Excel Import"):
		return
	frappe.db.sql(
		"""
		update `tabUmre Excel Import`
		set status = 'Draft',
			job_id = null,
			validation_signature = null,
			started_at = null,
			completed_at = null,
			error_log = %s
		where status in ('Validated', 'Queued', 'Processing', 'Failed')
		""",
		(
			"Tek sayfalı manuel kolon eşleme sürümüne geçiş nedeniyle aktarım sıfırlandı. "
			"Başlık satırını ve kolon eşlemelerini seçip yeniden doğrulayın.",
		),
	)
