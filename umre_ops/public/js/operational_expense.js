// Operational Expense — USD önizleme (kayıt sunucuda validate ile kesinleşir)
frappe.ui.form.on("Operational Expense", {
	setup(frm) {
		frm.set_query("expense_category", function () {
			return { filters: { is_group: 0, is_active: 1 } };
		});
	},
	onload(frm) {
		default_active_season(frm);
	},
	amount(frm) {
		preview_usd(frm);
	},
	usd_exchange_rate(frm) {
		preview_usd(frm);
	},
	currency(frm) {
		preview_usd(frm);
	},
	money_account(frm) {
		preview_usd(frm);
	},
	receipt_attachment(frm) {
		prevent_unsaved_receipt_upload(frm);
	},
	refresh(frm) {
		default_active_season(frm);
		preview_usd(frm);
		configure_receipt_attachment(frm);
	},
});

function default_active_season(frm) {
	if (!frm.is_new() || frm.doc.season) return;
	frappe.call({
		method: "umre_ops.umre_ops.services.expense_service.get_active_season"
	}).then((r) => {
		if (r && r.message && !frm.doc.season) {
			frm.set_value("season", r.message);
		}
	});
}

function preview_usd(frm) {
	const cur = (frm.doc.currency || "").toString().toUpperCase();
	const amt = frappe.utils.flt(frm.doc.amount);
	if (cur === "USD") {
		frm.set_value("usd_exchange_rate", 1);
		frm.set_value("usd_amount", amt);
		return;
	}
	const rate = frappe.utils.flt(frm.doc.usd_exchange_rate);
	if (rate > 0) {
		frm.set_value("usd_amount", amt / rate);
	}
}

function configure_receipt_attachment(frm) {
	const is_new = frm.is_new();
	frm.set_df_property("receipt_attachment", "read_only", is_new ? 1 : 0);
	frm.set_df_property(
		"receipt_attachment",
		"description",
		is_new
			? __("Dekont yüklemek için önce gider formunu kaydedin. Aksi halde Frappe eki bağlamak için formu otomatik kaydeder.")
			: __("PDF veya resim dosyası yükleyin: pdf, jpg, jpeg, png, webp.")
	);
}

function prevent_unsaved_receipt_upload(frm) {
	if (!frm.is_new() || !frm.doc.receipt_attachment) return;
	const attachment = frm.doc.receipt_attachment;
	frm.set_value("receipt_attachment", "");
	frappe.msgprint({
		title: __("Dekont daha sonra yüklenmeli"),
		message: __(
			"{0} dosyası forma bağlanmadı. Önce gider kaydını kaydedin, ardından dekontu yükleyin.",
			[frappe.utils.escape_html(attachment)]
		),
		indicator: "orange",
	});
}
