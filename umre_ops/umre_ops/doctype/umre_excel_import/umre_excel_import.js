// Copyright (c) 2026, Sermed Turizm and contributors

frappe.ui.form.on("Umre Excel Import", {
	refresh(frm) {
		const locked = ["Queued", "Processing", "Partially Completed", "Completed"].includes(frm.doc.status);
		frm.toggle_enable(["import_file", "target_tour", "header_row", "column_mappings"], !locked);

		if (!locked && frm.doc.import_file) {
			frm.add_custom_button(__("Başlıkları Oku"), () => load_headers(frm));
			if (!frm.is_new()) {
				const pending = (frm.doc.staged_rows || []).find(
					(row) => row.row_status === "Pending Referral" && row.referral_text
				);
				if (pending) {
					frm.add_custom_button(__("Bekleyen Referansı Eşle"), () => frappe.prompt(
						[{
							fieldname: "referral_source",
							fieldtype: "Link",
							options: "Referral Source",
							label: __("Referans Kaynağı"),
							reqd: 1,
						}],
						(values) => frappe.call({
							method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.resolve_referral",
							args: {
								docname: frm.doc.name,
								referral_text: pending.referral_text,
								referral_source: values.referral_source,
							},
							callback: () => frm.reload_doc(),
						}),
						__("Bekleyen Referansı Eşle")
					));
					frm.add_custom_button(__("Bekleyen Referansı Oluştur"), () => frappe.confirm(
						__("Yeni referans kaynağı oluşturulsun mu: {0}", [pending.referral_text]),
						() => frappe.call({
							method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.create_referral",
							args: { docname: frm.doc.name, referral_text: pending.referral_text },
							callback: () => frm.reload_doc(),
						})
					));
				}
			}
			frm.add_custom_button(__("Ön Kontrol"), () => run_preflight(frm));
		}
		const ready = new Set(["Create Ready", "Update Ready", "No-op"]);
		const clean_preflight = frm.doc.status === "Validated" && !frm.doc.row_errors &&
			Number(frm.doc.total_rows || 0) > 0 && (frm.doc.staged_rows || []).length > 0 &&
			(frm.doc.staged_rows || []).every((row) => ready.has(row.row_status));
		if (clean_preflight) {
			frm.add_custom_button(__("İçe Aktar"), () => frappe.confirm(
				__("Ön kontrolü temiz olan tüm satırlar tek işlem olarak aktarılacak. Devam?"),
				() => frm.call({
					method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.start_import",
					args: { docname: frm.doc.name }, freeze: true,
					callback: () => frm.reload_doc(),
				})
			));
		}
		if (["Queued", "Processing"].includes(frm.doc.status) && frm.doc.job_id) {
			frm.add_custom_button(__("Kuyruğu Kontrol Et / Yeniden Dene"), () => frm.call({
				method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.start_import",
				args: { docname: frm.doc.name }, callback: () => frm.reload_doc(),
			}));
			window.clearTimeout(frm.__umre_import_poll);
			frm.__umre_import_poll = window.setTimeout(() => frm.reload_doc(), 3000);
		}
		if (["Partially Completed", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Yeni Deneme Oluştur"), () => frappe.new_doc(
				"Umre Excel Import",
				{
					import_file: frm.doc.import_file,
					target_tour: frm.doc.target_tour,
					header_row: frm.doc.header_row || 1,
				}
			));
		}
		show_category_summary(frm);
	},
	async import_file(frm) {
		invalidate_source(frm, true);
		if (frm.doc.import_file) await load_headers(frm);
	},
	async header_row(frm) {
		invalidate_source(frm, true);
		if (frm.doc.import_file) await load_headers(frm);
	},
	target_tour(frm) { invalidate_source(frm, false); },
});

async function load_headers(frm) {
	const response = await frappe.call({
		method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.inspect_headers",
		args: {
			docname: frm.is_new() ? null : frm.doc.name,
			import_file: frm.doc.import_file,
			header_row: frm.doc.header_row || 1,
		},
		freeze: true,
	});
	const payload = response.message || {};
	const headers = payload.headers || [];
	const source_field = frappe.meta.get_docfield("Umre Excel Column Mapping", "source_column", frm.doc.name);
	if (source_field) source_field.options = ["", ...headers].join("\n");
	frm.clear_table("column_mappings");
	(payload.mappings || []).forEach((mapping) => frm.add_child("column_mappings", mapping));
	frm.fields_dict.column_mappings.grid.refresh();
	frappe.msgprint({
		title: __("Bulunan Başlıklar"),
		message: headers.map(frappe.utils.escape_html).join("<br>") +
			`<p class="text-muted">${__("Eşleşmeyen hedefleri tabloda elle seçin.")}</p>`,
	});
}

async function run_preflight(frm) {
	if (frm.is_new() || frm.is_dirty()) await frm.save();
	const response = await frm.call({
		method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.validate_import",
		args: { docname: frm.doc.name },
		freeze: true,
		freeze_message: __("Excel dosyası ön kontrolden geçiriliyor..."),
	});
	if (response.message) show_summary(response.message);
	await frm.reload_doc();
}

function invalidate_source(frm, clear_mapping) {
	if (clear_mapping) frm.clear_table("column_mappings");
	["validation_signature", "dry_run_result", "row_log", "error_log", "started_at", "completed_at"].forEach(
		(fieldname) => frm.set_value(fieldname, null),
	);
	frm.clear_table("staged_rows");
	["total_rows", "created_umreci", "updated_umreci", "created_bookings", "updated_bookings", "row_errors"].forEach(
		(fieldname) => frm.set_value(fieldname, 0),
	);
	if (!frm.is_new() && !["Queued", "Processing", "Completed"].includes(frm.doc.status)) {
		frm.set_value("status", "Draft");
	}
}

function show_summary(result) {
	const summary = result.summary || result;
	frappe.msgprint({
		title: __("Dry Run Complete"),
		indicator: summary.row_errors ? "orange" : "green",
		message: `${__("Total Rows")}: ${summary.total_rows || 0}<br>${__("Row Errors")}: ${summary.row_errors || 0}`,
	});
}

function show_category_summary(frm) {
	const counts = (frm.doc.staged_rows || []).reduce((out, row) => {
		out[row.row_status] = (out[row.row_status] || 0) + 1;
		return out;
	}, {});
	const html = Object.entries(counts).map(([status, count]) =>
		`${frappe.utils.escape_html(__(status))}: ${frappe.utils.escape_html(String(count))}`
	).join(" · ");
	frm.set_intro(html || null, Object.keys(counts).some((key) => !["Create Ready", "Update Ready", "No-op", "Imported"].includes(key)) ? "orange" : "blue");
}
