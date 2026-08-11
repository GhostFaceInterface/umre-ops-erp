frappe.ui.form.on("Meal Cost Rule", {
	setup(frm) {
		frappe.call("umre_ops.umre_ops.services.expense_service.get_active_season").then((response) => {
			if (response.message) frm.set_query("tour", () => ({ filters: { season: response.message } }));
		});
	},
});
