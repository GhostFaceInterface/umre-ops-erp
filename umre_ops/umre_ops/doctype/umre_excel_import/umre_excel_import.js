// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Umre Excel Import", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		const import_is_locked = ["Queued", "Processing", "Completed"].includes(frm.doc.status);
		frm.toggle_enable(["import_file", "target_tour", "worksheet_name"], !import_is_locked);
		load_worksheet_options(frm);

		if (!import_is_locked) {
			frm.add_custom_button(__("Validate / Dry Run"), () => {
				prepare_validation(frm).then(() => frm.call({
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
				}));
			});
		}

		if (frm.doc.status === "Validated" && !frm.doc.row_errors) {
			frm.add_custom_button(__("Start Import"), () => {
				frappe.confirm(
					__("This will create or update Umreci and Umre Booking records. Continue?"),
					async () => {
						if (frm.is_dirty()) {
							await frm.save();
						}
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

		if (["Queued", "Processing"].includes(frm.doc.status) && frm.doc.job_id) {
			frm.add_custom_button(__("Kuyruğu Kontrol Et / Yeniden Dene"), () => {
				frm.call({
					method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.start_import",
					args: { docname: frm.doc.name },
					freeze: true,
					freeze_message: __("Kuyruk durumu kontrol ediliyor..."),
					callback(r) {
						if (r.message) {
							frappe.show_alert({ message: __("Aktarım işi kuyruğa hazır."), indicator: "green" });
							frm.reload_doc();
						}
					},
				});
			});
		}
	},
	import_file(frm) {
		frm.set_df_property("worksheet_name", "options", [""]);
		frm.set_value("worksheet_name", null);
	},
	after_save(frm) {
		load_worksheet_options(frm);
	},
});

async function prepare_validation(frm) {
	if (frm.is_dirty()) {
		await frm.save();
	}
	const worksheets = await load_worksheet_options(frm);
	if (worksheets.length > 1 && !frm.doc.worksheet_name) {
		frappe.throw(__("Excel dosyasında birden fazla sayfa var. Lütfen içe aktarılacak sayfayı seçin."));
	}
	if (frm.is_dirty()) {
		await frm.save();
	}
}

async function load_worksheet_options(frm) {
	if (frm.is_new() || !frm.doc.import_file || (frm.doc.status === "Completed" && !frm.doc.worksheet_name)) {
		return [];
	}
	const import_file = frm.doc.import_file;
	const response = await frappe.call({
		method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.get_worksheet_names",
		args: { docname: frm.doc.name },
	});
	if (frm.doc.import_file !== import_file) {
		return [];
	}
	const worksheets = response.message || [];
	frm.set_df_property("worksheet_name", "options", ["", ...worksheets]);
	if (worksheets.length === 1 && !frm.doc.worksheet_name) {
		await frm.set_value("worksheet_name", worksheets[0]);
	} else if (frm.doc.worksheet_name && !worksheets.includes(frm.doc.worksheet_name)) {
		await frm.set_value("worksheet_name", null);
	}
	return worksheets;
}

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
