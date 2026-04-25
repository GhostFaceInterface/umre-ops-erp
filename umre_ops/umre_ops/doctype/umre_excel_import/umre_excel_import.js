// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Umre Excel Import", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Validate / Dry Run"), () => {
			frm.call({
				method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.validate_import",
				args: { docname: frm.doc.name },
				freeze: true,
				freeze_message: __("Validating Excel file..."),
				callback(r) {
					if (r.message) {
						show_import_summary(r.message, __("Dry Run Complete"));
						frm.reload_doc();
					}
				},
			});
		});

		if (!["Queued", "Processing"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Start Import"), () => {
				frappe.confirm(
					__("This will create or update Umreci and Umre Booking records. Continue?"),
					() => {
						frm.call({
							method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.start_import",
							args: { docname: frm.doc.name },
							freeze: true,
							freeze_message: __("Queueing import..."),
							callback(r) {
								if (r.message) {
									frappe.msgprint({
										title: __("Import Queued"),
										message: __("Background job queued: {0}", [r.message.job_id || ""]),
										indicator: "blue",
									});
									frm.reload_doc();
								}
							},
						});
					}
				);
			});
		}
	},
});

function show_import_summary(result, title) {
	const summary = result.summary || result;
	frappe.msgprint({
		title,
		indicator: summary.row_errors ? "orange" : "green",
		message: `
			<div>
				<p><b>${__("Total Rows")}:</b> ${summary.total_rows || 0}</p>
				<p><b>${__("Created Umreci")}:</b> ${summary.created_umreci || 0}</p>
				<p><b>${__("Updated Umreci")}:</b> ${summary.updated_umreci || 0}</p>
				<p><b>${__("Created Bookings")}:</b> ${summary.created_bookings || 0}</p>
				<p><b>${__("Updated Bookings")}:</b> ${summary.updated_bookings || 0}</p>
				<p><b>${__("Row Errors")}:</b> ${summary.row_errors || 0}</p>
			</div>
		`,
	});
}
