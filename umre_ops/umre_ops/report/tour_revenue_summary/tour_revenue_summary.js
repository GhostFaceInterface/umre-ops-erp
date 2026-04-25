// Copyright (c) 2026, Sermed Turizm and contributors
// For license information, please see license.txt

frappe.query_reports["Tour Revenue Summary"] = {
	filters: [
		{
			fieldname: "tour",
			label: __("Tour"),
			fieldtype: "Link",
			options: "Umre Tour",
		},
	],
};
