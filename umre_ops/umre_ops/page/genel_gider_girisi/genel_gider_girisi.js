frappe.pages["genel-gider-girisi"].on_page_load = function (wrapper) {
	new GenelGiderGirisi(wrapper);
};

class GenelGiderGirisi {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Genel Gider Girişi"),
			single_column: true
		});
		this.active_season = null;
		this.taxonomy = [];
		this.make();
	}

	make() {
		this.container = $("<div>").css({
			maxWidth: "1200px",
			margin: "0 auto",
			padding: "20px"
		});
		this.page.main.empty().append(this.container);
		this.render_loading();
		this.load();
	}

	load() {
		frappe.call({
			method: "umre_ops.umre_ops.services.expense_service.get_operational_expense_taxonomy"
		}).then((r) => {
			this.taxonomy = r.message || [];
			return frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_active_season"
			});
		}).then((r) => {
			this.active_season = r.message || null;
			this.render();
		}).catch((err) => {
			console.error("Expense taxonomy load failed", err);
			this.render_error(__("Gider taksonomisi yüklenemedi."));
		});
	}

	render_loading() {
		this.container.html(`<div class="text-muted">${__("Yükleniyor...")}</div>`);
	}

	render_error(message) {
		this.container.html(`<div class="frappe-card p-4 text-muted">${frappe.utils.escape_html(message)}</div>`);
	}

	render() {
		if (!this.active_season) {
			this.render_error(__("Umre Ops Ayarları içinde Aktif Sezon seçilmeden gider girişi yapılamaz."));
			return;
		}
		if (!this.taxonomy.length) {
			this.render_error(__("Aktif gider taksonomisi bulunamadı."));
			return;
		}

		const html = `
			<div class="mb-4">
				<div class="text-muted text-uppercase small">${__("Aktif Sezon")}</div>
				<div class="h4 mb-0">${frappe.utils.escape_html(this.active_season)}</div>
			</div>
			<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;">
				${this.taxonomy.map((group) => this.render_group(group)).join("")}
			</div>
		`;
		this.container.html(html);
		this.bind_actions();
	}

	render_group(group) {
		return `
			<div class="frappe-card p-4">
				<div class="h5 mb-3">${frappe.utils.escape_html(group.label || group.name)}</div>
				${(group.children || []).map((child) => this.render_node(child)).join("")}
			</div>
		`;
	}

	render_node(node) {
		if (node.is_group) {
			return `
				<div class="mt-3 mb-2 text-muted text-uppercase small">${frappe.utils.escape_html(node.label || node.name)}</div>
				${(node.children || []).map((child) => this.render_node(child)).join("")}
			`;
		}
		return `
			<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-color);">
				<div>${frappe.utils.escape_html(node.label || node.name)}</div>
				<button type="button" class="btn btn-xs btn-primary" data-expense-category="${frappe.utils.escape_html(node.name)}">
					${__("Yeni Gider Ekle")}
				</button>
			</div>
		`;
	}

	bind_actions() {
		this.container.find("[data-expense-category]").on("click", (event) => {
			const category = $(event.currentTarget).attr("data-expense-category");
			this.create_expense(category);
		});
	}

	create_expense(category) {
		frappe.model.with_doctype("Operational Expense", () => {
			const doc = frappe.model.get_new_doc("Operational Expense");
			doc.season = this.active_season;
			doc.expense_category = category;
			doc.status = "Draft";
			frappe.set_route("Form", "Operational Expense", doc.name);
		});
	}
}
