// Copyright (c) 2026, Sermed Turizm and contributors

frappe.query_reports["Payment Date Reconciliation"] = {
	filters: [
		{ fieldname: "tour", label: __("Tour"), fieldtype: "Link", options: "Umre Tour" },
		{
			fieldname: "verification_status",
			label: __("Verification Status"),
			fieldtype: "Select",
			options: "\nNeeds Review\nVerified\nRejected",
		},
		{
			fieldname: "date_source",
			label: __("Date Source"),
			fieldtype: "Select",
			options: "\nLegacy\nBank\nReceipt\nExcel\nManual",
		},
		{
			fieldname: "posting_status",
			label: __("Accounting Status"),
			fieldtype: "Select",
			options: "\nDraft\nPosted\nFailed\nCancelled",
		},
		{ fieldname: "anomalies_only", label: __("Only Anomalies"), fieldtype: "Check", default: 1 },
	],
};
