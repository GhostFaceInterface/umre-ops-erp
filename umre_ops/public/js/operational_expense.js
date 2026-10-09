// Operational Expense — USD önizleme (kayıt sunucuda validate ile kesinleşir).
// Kur boşsa sunucu ERPNext kurunu (SAR sabit 3,75; TRY ECB) kendisi doldurur;
// form yalnızca değişiklik anında otomatik kuru önceden gösterir.
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
		reset_rate_and_fetch(frm);
	},
	expense_date(frm) {
		if (frm.doc.kur_kaynagi !== "Manuel") reset_rate_and_fetch(frm);
	},
	money_account(frm) {
		if (frm.doc.money_account) {
			frappe.db.get_value("Umre Money Account", frm.doc.money_account, ["currency", "institution"], (r) => {
				if (r) {
					frm.set_value("financial_institution", r.institution);
					if (r.currency !== frm.doc.currency) {
						frm.set_value("currency", r.currency);
					}
				}
			});
		} else {
			frm.set_value("currency", "");
			frm.set_value("financial_institution", "");
		}
	},
	refresh(frm) {
		default_active_season(frm);
		configure_receipt_attachment(frm);
	},
});

function reset_rate_and_fetch(frm) {
	const cur = (frm.doc.currency || "").toString().toUpperCase();
	if (!cur) return;
	if (cur === "USD") {
		frm.set_value("usd_exchange_rate", 1);
		preview_usd(frm);
		return;
	}
	frappe.call({
		method: "umre_ops.umre_ops.services.fx_service.get_usd_rate",
		args: { currency: cur, on_date: frm.doc.expense_date || frappe.datetime.get_today() },
	}).then((r) => {
		const out = r && r.message;
		if (out && out.currency === (frm.doc.currency || "").toUpperCase()) {
			frm.set_value("usd_exchange_rate", out.rate);
			frm.set_value("kur_kaynagi", out.source);
			preview_usd(frm);
		}
	});
}

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

// Read-only preview of the server formula (usd_amount = amount ÷ rate), rounded like the server.
function preview_usd(frm) {
	const cur = (frm.doc.currency || "").toString().toUpperCase();
	const amt = frappe.utils.flt(frm.doc.amount);
	const rate = cur === "USD" ? 1 : frappe.utils.flt(frm.doc.usd_exchange_rate);
	const usd = rate > 0 ? frappe.utils.flt(amt / rate, 2) : 0;
	if (frappe.utils.flt(frm.doc.usd_amount, 2) !== usd) {
		frm.set_value("usd_amount", usd);
	}
}

function configure_receipt_attachment(frm) {
	frm.set_df_property(
		"receipt_attachment",
		"description",
		__("PDF veya resim dosyası yükleyin: pdf, jpg, jpeg, png, webp.")
	);

	const control = frm.fields_dict.receipt_attachment;
	if (!control || control._umre_receipt_upload_patched) return;
	control._umre_receipt_upload_patched = true;

	control.on_attach_click = function () {
		this.set_upload_options();
		this.upload_options.doctype = null;
		this.upload_options.docname = null;
		this.upload_options.fieldname = null;
		this.upload_options.make_attachments_public = 0;
		this.upload_options.restrictions = {
			...(this.upload_options.restrictions || {}),
			allowed_file_types: [".pdf", ".jpg", ".jpeg", ".png", ".webp"],
		};
		this.file_uploader = new frappe.ui.FileUploader(this.upload_options);
	};

	control.on_upload_complete = async function (attachment) {
		await this.parse_validate_and_set_in_model(attachment.file_url);
		this.set_value(attachment.file_url);
		this.refresh();
		this.toggle_reload_button();

		if (this.frm) {
			this.frm.dirty();
		}
	};

	control.clear_attachment = function () {
		frappe.confirm(__("Are you sure you want to delete the attachment?"), async () => {
			await this.parse_validate_and_set_in_model(null);
			this.set_value(null);
			this.refresh();

			if (this.frm) {
				this.frm.dirty();
			}
		});
	};
}
