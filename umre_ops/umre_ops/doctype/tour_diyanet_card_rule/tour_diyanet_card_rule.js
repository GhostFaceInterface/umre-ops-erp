frappe.ui.form.on("Tour Diyanet Card Rule", {
	setup(frm) {
		frappe.call("umre_ops.umre_ops.services.expense_service.get_active_season").then((response) => {
			if (response.message) frm.set_query("tur", () => ({ filters: { season: response.message } }));
		});
	},
});
