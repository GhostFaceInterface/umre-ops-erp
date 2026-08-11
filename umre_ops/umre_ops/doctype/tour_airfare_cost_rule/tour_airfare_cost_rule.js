// Copyright (c) 2026, Sermed Turizm and contributors

frappe.ui.form.on("Tour Airfare Cost Rule", {
	setup(frm) {
		frappe.call("umre_ops.umre_ops.services.expense_service.get_active_season").then((response) => {
			const active_season = response.message;
			if (active_season) frm.set_query("tur", () => ({ filters: { season: active_season } }));
		});
	},
});
