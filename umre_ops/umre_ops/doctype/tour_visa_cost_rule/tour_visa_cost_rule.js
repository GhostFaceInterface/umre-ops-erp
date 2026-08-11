// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Tour Visa Cost Rule", {
	setup(frm) {
		frappe.call("umre_ops.umre_ops.services.expense_service.get_active_season").then((response) => {
			if (response.message) frm.set_query("tur", () => ({ filters: { season: response.message } }));
		});
	},
});
