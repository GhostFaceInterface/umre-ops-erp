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
		this.selected_season = null;
		this.seasons = [];
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
		Promise.all([
			frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_operational_expense_taxonomy"
			}),
			frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_active_season"
			}),
			frappe.call({
				method: "umre_ops.umre_ops.services.expense_service.get_seasons"
			})
		]).then(([taxonomy_response, active_response, seasons_response]) => {
			this.taxonomy = taxonomy_response.message || [];
			this.active_season = active_response.message || null;
			this.selected_season = this.active_season;
			this.seasons = seasons_response.message || [];
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
			<div class="mb-4" style="display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;">
				<div>
					<div class="text-muted text-uppercase small">${__("Aktif Sezon")}</div>
					<div class="h4 mb-0">${frappe.utils.escape_html(this.active_season)}</div>
				</div>
				<div style="min-width:260px;">
					<label class="text-muted text-uppercase small" for="umre-expense-season" style="display:block;margin-bottom:4px;">${__("Gider Sezonu")}</label>
					<select id="umre-expense-season" class="form-control" style="height:34px;border-color:#cfd4dc;">
						${this.render_season_options()}
					</select>
				</div>
			</div>
			<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">
				${this.taxonomy.map((group) => this.render_group(group)).join("")}
			</div>
		`;
		this.container.html(html);
		this.bind_actions();
	}

	render_group(group) {
		return `
			<div class="frappe-card p-4" style="border:1px solid #d5dae1;box-shadow:0 1px 2px rgba(15,23,42,0.04);background:#fff;">
				<div class="h5 mb-3" style="line-height:1.25;text-transform:uppercase;letter-spacing:0;font-weight:700;">${frappe.utils.escape_html(this.group_title(group))}</div>
				${(group.children || []).map((child) => this.render_node(child)).join("")}
			</div>
		`;
	}

	render_season_options() {
		const seen = new Set();
		const rows = [];
		(this.seasons || []).forEach((season) => {
			if (!season.name || seen.has(season.name)) return;
			seen.add(season.name);
			rows.push(season);
		});
		if (this.selected_season && !seen.has(this.selected_season)) {
			rows.unshift({ name: this.selected_season, season_name: this.selected_season });
		}
		return rows.map((season) => {
			const name = season.name || "";
			const label = season.season_name || season.name || "";
			const selected = name === this.selected_season ? "selected" : "";
			return `<option value="${frappe.utils.escape_html(name)}" ${selected}>${frappe.utils.escape_html(label)}</option>`;
		}).join("");
	}

	group_title(group) {
		const label = group.label || group.name || "";
		if (typeof label.toLocaleUpperCase === "function") {
			return label.toLocaleUpperCase("tr-TR");
		}
		return label.toUpperCase();
	}

	render_node(node) {
		if (node.is_group) {
			return `
				<div class="mt-3 mb-2 text-muted text-uppercase small">${frappe.utils.escape_html(node.label || node.name)}</div>
				${(node.children || []).map((child) => this.render_node(child)).join("")}
			`;
		}
		const label = node.label || node.name;
		return `
			<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-color);">
				<div style="min-width:0;line-height:1.35;">${frappe.utils.escape_html(label)}</div>
				<button
					type="button"
					class="btn btn-xs btn-default"
					data-expense-category="${frappe.utils.escape_html(node.name)}"
					title="${frappe.utils.escape_html(__("Yeni gider ekle") + ": " + label)}"
					aria-label="${frappe.utils.escape_html(__("Yeni gider ekle") + ": " + label)}"
					style="display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 9px;border-radius:6px;background:var(--control-bg);border:1px solid var(--border-color);color:var(--text-color);font-weight:500;white-space:nowrap;box-shadow:none;"
				>
					${this.add_icon()}
					<span>${__("Ekle")}</span>
				</button>
			</div>
		`;
	}

	add_icon() {
		if (frappe.utils && typeof frappe.utils.icon === "function") {
			return frappe.utils.icon("add", "xs");
		}
		return `<span aria-hidden="true" style="font-size:14px;line-height:1;">+</span>`;
	}

	bind_actions() {
		this.container.find("#umre-expense-season").on("change", (event) => {
			this.selected_season = $(event.currentTarget).val() || this.active_season;
		});
		this.container.find("[data-expense-category]").on("click", (event) => {
			const category = $(event.currentTarget).attr("data-expense-category");
			this.create_expense(category);
		});
	}

	create_expense(category) {
		const season = this.selected_season || this.active_season;
		if (!season) {
			frappe.msgprint(__("Gider girişi için sezon seçilmelidir."));
			return;
		}
		frappe.model.with_doctype("Operational Expense", () => {
			const doc = frappe.model.get_new_doc("Operational Expense");
			doc.season = season;
			doc.expense_category = category;
			doc.status = "Confirmed";
			frappe.set_route("Form", "Operational Expense", doc.name);
		});
	}
}
