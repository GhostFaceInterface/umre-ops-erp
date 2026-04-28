// Operational Expense — USD önizleme (kayıt sunucuda validate ile kesinleşir)
frappe.ui.form.on("Operational Expense", {
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
	refresh(frm) {
		preview_usd(frm);
	},
});

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
