// Copyright (c) 2026, Sermed Turizm and contributors

frappe.ui.form.on("Umre Excel Import", {
	refresh(frm) {
		if (frm.is_new()) return;
		const locked = ["Queued", "Processing", "Completed"].includes(frm.doc.status);
		frm.toggle_enable(["import_file", "target_tour", "header_row", "column_mappings"], !locked);

		if (!locked && frm.doc.import_file) {
			frm.add_custom_button(__("Başlıkları Oku"), () => load_headers(frm));
			const pending = (frm.doc.staged_rows || []).find(
				(row) => row.row_status === "Pending Referral" && row.referral_text
			);
			if (pending) {
				frm.add_custom_button(__("Bekleyen Referansı Oluştur"), () => frappe.confirm(
					__("Yeni referans kaynağı oluşturulsun mu: {0}", [pending.referral_text]),
					() => frappe.call({
						method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.create_referral",
						args: { docname: frm.doc.name, referral_text: pending.referral_text },
						callback: () => frm.reload_doc(),
					})
				));
			}
			frm.add_custom_button(__("Validate / Dry Run"), async () => {
				if (frm.is_dirty()) await frm.save();
				frm.call({
					method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.validate_import",
					args: { docname: frm.doc.name }, freeze: true,
					freeze_message: __("Excel dosyası doğrulanıyor..."),
					callback: (r) => { if (r.message) { show_summary(r.message); frm.reload_doc(); } },
				});
			});
		}
		if (frm.doc.status === "Validated" && !frm.doc.row_errors) {
			frm.add_custom_button(__("Start Import"), () => frappe.confirm(
				__("Hazır satırlar aktarılacak; bekleyen referans ve çakışmalar atlanacak. Devam?"),
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
		}
	},
	import_file(frm) { invalidate_mapping(frm); },
	header_row(frm) { invalidate_mapping(frm); },
});

frappe.ui.form.on("Umre Excel Import Row", {
	referral_source(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.referral_source) return;
		frappe.call({
			method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.resolve_referral",
			args: { docname: frm.doc.name, referral_text: row.referral_text, referral_source: row.referral_source },
			callback: () => frm.reload_doc(),
		});
	},
});

async function load_headers(frm) {
	if (frm.is_dirty()) await frm.save();
	const response = await frappe.call({
		method: "umre_ops.umre_ops.doctype.umre_excel_import.umre_excel_import.inspect_headers",
		args: { docname: frm.doc.name }, freeze: true,
	});
	const headers = response.message || [];
	const source_field = frappe.meta.get_docfield("Umre Excel Column Mapping", "source_column", frm.doc.name);
	if (source_field) source_field.options = ["", ...headers].join("\n");
	frm.fields_dict.column_mappings.grid.refresh();
	frappe.msgprint({ title: __("Bulunan Başlıklar"), message: headers.map(frappe.utils.escape_html).join("<br>") });
}

function invalidate_mapping(frm) {
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
