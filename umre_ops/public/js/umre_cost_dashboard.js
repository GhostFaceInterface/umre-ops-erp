/*
 * Umre Operasyon Paneli — Financial Dashboard
 *
 * Strategy: detect when the user lands on the "Umre Operasyon Paneli"
 * Workspace, mount our financial panel above the existing link cards,
 * and refetch on `umre_cost_dashboard_dirty` realtime events.
 *
 * Single source of truth: backend `umre_ops.umre_ops.services.dashboard_service.get_tour_cost_breakdown`.
 */
(function () {
	"use strict";

	const PANEL_ID = "umre-fin-panel";
	const WORKSPACE_NAME = "Umre Operasyon Paneli";
	const WORKSPACE_ROUTES = ["umre-operasyon-paneli", "Umre Operasyon Paneli"];
	const ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_tour_cost_breakdown";

	let _state = {
		tour: "",        // "" = all tours
		loading: false,
		debounce_handle: null,
		chart: null,
		last_payload: null
	};

	function fmt_money(value, currency) {
		const n = Number(value || 0);
		const cur = (currency || "USD").toString().toUpperCase();
		// Force ISO USD formatting so we never show wrong symbols (e.g. "L") from
		// corrupted Currency master rows or Company TRY defaults bleeding into Desk.
		if (cur === "USD") {
			try {
				return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
			} catch (e) {
				/* fall through */
			}
		}
		if (typeof format_currency === "function") {
			try {
				return format_currency(n, cur);
			} catch (e) {
				/* fall through */
			}
		}
		try {
			return frappe.format(n, { fieldtype: "Currency", options: cur });
		} catch (e) {
			return cur + " " + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		}
	}

	function fmt_pct(value) {
		const n = Number(value || 0) * 100;
		return n.toFixed(1) + "%";
	}

	function fmt_int(value) {
		return Number(value || 0).toLocaleString("tr-TR");
	}

	const SEASON_PANEL_ID = "umre-season-fin-panel";
	const SEASON_ENDPOINT = "umre_ops.umre_ops.services.dashboard_service.get_operational_expense_dashboard";

	let _season_state = {
		season: "",
		category: "",
		currency: "",
		money_account: "",
		chart_cat: null,
		chart_month: null
	};

	function on_target_route() {
		const route = (frappe.get_route && frappe.get_route()) || [];
		if (!route || route.length < 2) return false;
		if (route[0] !== "Workspaces") return false;
		return WORKSPACE_ROUTES.includes(route[1]);
	}

	function ensure_mounted() {
		if (!on_target_route()) {
			const tp = document.getElementById(PANEL_ID);
			if (tp) tp.remove();
			const sp = document.getElementById(SEASON_PANEL_ID);
			if (sp) sp.remove();
			_state.chart = null;
			_season_state.chart_cat = null;
			_season_state.chart_month = null;
			return;
		}

		const candidates = [
			document.querySelector(".workspace-sidebar-toggle ~ .codex-editor"),
			document.querySelector(".layout-main-section .codex-editor"),
			document.querySelector(".codex-editor")
		];
		const container = candidates.find(Boolean);
		if (!container) return;

		if (!document.getElementById(PANEL_ID)) {
			const panel = document.createElement("div");
			panel.id = PANEL_ID;
			panel.className = "umre-fin-panel";
			panel.innerHTML = render_skeleton();
			container.parentNode.insertBefore(panel, container);
			wire_events(panel);
			schedule_refresh(0);
		}

		ensure_season_panel();
	}

	function ensure_season_panel() {
		const tour = document.getElementById(PANEL_ID);
		if (!tour || document.getElementById(SEASON_PANEL_ID)) return;
		const sp = document.createElement("div");
		sp.id = SEASON_PANEL_ID;
		sp.className = "umre-fin-panel umre-season-fin-panel";
		sp.innerHTML = render_season_skeleton();
		tour.after(sp);
		wire_season_events(sp);
		schedule_season_refresh(0);
	}

	function render_skeleton() {
		return `
			<div class="umre-fin-panel__header">
				<div class="umre-fin-panel__title"><span class="dot"></span>${__("Tur Maliyeti Paneli")}</div>
				<div class="umre-fin-panel__filter">
					<label for="umre-fin-tour">${__("Tur")}</label>
					<select id="umre-fin-tour"><option value="">${__("Tüm Turlar")}</option></select>
					<button type="button" class="umre-fin-panel__refresh" id="umre-fin-refresh">${__("Yenile")}</button>
				</div>
			</div>
			<div class="umre-fin-hero" id="umre-fin-hero"></div>

			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Maliyet Dağılımı")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-cost">
				<div class="umre-fin-cost__cards" id="umre-fin-cards"></div>
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Maliyet Dağılımı (%)")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-fin-chart"></div>
				</div>
			</div>

			<div class="umre-fin-section">
				<div class="umre-fin-section__title">${__("Performans")}</div>
				<div class="umre-fin-section__rule"></div>
			</div>
			<div class="umre-fin-kpi" id="umre-fin-kpi"></div>
		`;
	}

	function wire_events(panel) {
		const sel = panel.querySelector("#umre-fin-tour");
		sel.addEventListener("change", function () {
			_state.tour = sel.value || "";
			schedule_refresh(0);
		});
		const btn = panel.querySelector("#umre-fin-refresh");
		btn.addEventListener("click", function () {
			btn.classList.remove("is-stale");
			schedule_refresh(0);
		});
	}

	function schedule_refresh(delay_ms) {
		if (_state.debounce_handle) clearTimeout(_state.debounce_handle);
		_state.debounce_handle = setTimeout(refresh, delay_ms == null ? 250 : delay_ms);
	}

	function render_season_skeleton() {
		return `
			<div class="umre-fin-panel__header">
				<div class="umre-fin-panel__title umre-season-fin-panel__title"><span class="dot"></span>${__("Sezonluk Genel Giderler")}</div>
				<div class="umre-fin-panel__filter umre-season-filters">
					<select id="umre-season-filter"></select>
					<select id="umre-season-cat"></select>
					<select id="umre-season-ccy"></select>
					<select id="umre-season-acc"></select>
					<button type="button" class="umre-fin-panel__refresh" id="umre-season-refresh">${__("Yenile")}</button>
				</div>
			</div>
			<div class="umre-fin-hero umre-season-hero" id="umre-season-hero"></div>
			<div class="umre-fin-cost umre-season-charts">
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Kategori Dağılımı (USD)")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-season-chart-cat"></div>
				</div>
				<div class="umre-fin-cost__chart">
					<div class="umre-fin-cost__chart-title">${__("Aylık Trend (USD)")}</div>
					<div class="umre-fin-cost__chart-body" id="umre-season-chart-month"></div>
				</div>
			</div>`;
	}

	function wire_season_events(sp) {
		const bind = (sel, key) => {
			sp.querySelector(sel).addEventListener("change", function () {
				_season_state[key] = this.value || "";
				schedule_season_refresh(0);
			});
		};
		bind("#umre-season-filter", "season");
		bind("#umre-season-cat", "category");
		bind("#umre-season-ccy", "currency");
		bind("#umre-season-acc", "money_account");
		sp.querySelector("#umre-season-refresh").addEventListener("click", function () {
			schedule_season_refresh(0);
		});
	}

	let _season_debounce = null;
	function schedule_season_refresh(ms) {
		if (_season_debounce) clearTimeout(_season_debounce);
		_season_debounce = setTimeout(refresh_season, ms == null ? 200 : ms);
	}

	function refresh_season() {
		const sp = document.getElementById(SEASON_PANEL_ID);
		if (!sp) return;
		sp.classList.add("umre-fin-loading");
		frappe.call({
			method: SEASON_ENDPOINT,
			args: {
				season: _season_state.season || "",
				category: _season_state.category || "",
				currency: _season_state.currency || "",
				money_account: _season_state.money_account || ""
			},
			freeze: false
		}).then((r) => {
			sp.classList.remove("umre-fin-loading");
			if (!r || !r.message) return;
			render_season_payload(sp, r.message);
		}).catch(() => {
			sp.classList.remove("umre-fin-loading");
		});
	}

	function render_season_payload(sp, p) {
		const f = p.filters || {};
		const curSeason = _season_state.season;
		const curCat = _season_state.category;
		const curCcy = _season_state.currency;
		const curAcc = _season_state.money_account;

		const sf = sp.querySelector("#umre-season-filter");
		sf.innerHTML = [`<option value="">${__("(Tüm sezonlar)")}</option>`].concat(
			(f.seasons || []).map(
				(s) =>
					`<option value="${frappe.utils.escape_html(s.name)}">${frappe.utils.escape_html(s.season_name || s.name)}</option>`
			)
		).join("");
		sf.value = curSeason || "";

		const sc = sp.querySelector("#umre-season-cat");
		sc.innerHTML = [`<option value="">${__("(Tüm kategoriler)")}</option>`].concat(
			(f.categories || []).map(
				(c) =>
					`<option value="${frappe.utils.escape_html(c.name)}">${frappe.utils.escape_html(c.category_name || c.name)}</option>`
			)
		).join("");
		sc.value = curCat || "";

		const sx = sp.querySelector("#umre-season-ccy");
		sx.innerHTML = [`<option value="">${__("(Tüm para birimleri)")}</option>`].concat(
			(f.currencies || []).map(
				(c) => `<option value="${frappe.utils.escape_html(c)}">${frappe.utils.escape_html(c)}</option>`
			)
		).join("");
		sx.value = curCcy || "";

		const sa = sp.querySelector("#umre-season-acc");
		sa.innerHTML = [`<option value="">${__("(Tüm hesaplar)")}</option>`].concat(
			(f.money_accounts || []).map(
				(a) =>
					`<option value="${frappe.utils.escape_html(a.name)}">${frappe.utils.escape_html(a.account_name || a.name)}</option>`
			)
		).join("");
		sa.value = curAcc || "";

		const buckets = p.buckets_usd || {};
		const hero = sp.querySelector("#umre-season-hero");
		hero.innerHTML = [
			hero_cell("revenue", __("Toplam Operasyonel Gider"), fmt_money(p.total_operational_usd, p.currency || "USD"), ""),
			hero_cell("cost", __("Pazarlama"), fmt_money(buckets.marketing, p.currency || "USD"), ""),
			hero_cell("cost", __("Ofis"), fmt_money(buckets.office, p.currency || "USD"), "")
		].join("") + [
			hero_cell("profit", __("Vergiler"), fmt_money(buckets.taxes, p.currency || "USD"), ""),
			hero_cell("profit", __("Personel"), fmt_money(buckets.personnel, p.currency || "USD"), ""),
			hero_cell("profit", __("Diğer"), fmt_money(buckets.other, p.currency || "USD"), "")
		].join("");

		const hostCat = sp.querySelector("#umre-season-chart-cat");
		hostCat.innerHTML = "";
		const cc = p.chart_by_category || {};
		_season_state.chart_cat = null;
		if ((cc.labels || []).length && typeof frappe.Chart === "function") {
			_season_state.chart_cat = new frappe.Chart(hostCat, {
				type: "donut",
				data: { labels: cc.labels, datasets: cc.datasets || [] },
				height: 240,
				colors: ["#ea580c", "#2563eb", "#16a34a", "#9333ea", "#64748b", "#0ea5e9"]
			});
		} else {
			hostCat.innerHTML = `<div class="umre-fin-empty">${__("Kayıt yok")}</div>`;
		}

		const hostM = sp.querySelector("#umre-season-chart-month");
		hostM.innerHTML = "";
		const cm = p.chart_monthly || {};
		_season_state.chart_month = null;
		if ((cm.labels || []).length && typeof frappe.Chart === "function") {
			_season_state.chart_month = new frappe.Chart(hostM, {
				type: "bar",
				data: { labels: cm.labels, datasets: cm.datasets || [] },
				height: 240,
				colors: ["#0ea5e9"]
			});
		} else {
			hostM.innerHTML = `<div class="umre-fin-empty">${__("Trend yok")}</div>`;
		}
	}

	function refresh() {
		const panel = document.getElementById(PANEL_ID);
		if (!panel) return;
		_state.loading = true;
		panel.classList.add("umre-fin-loading");

		frappe.call({
			method: ENDPOINT,
			args: { tour: _state.tour || "", _: Date.now() },
			freeze: false
		}).then((r) => {
			_state.loading = false;
			panel.classList.remove("umre-fin-loading");
			if (!r || !r.message) return;
			_state.last_payload = r.message;
			render_payload(panel, r.message);
		}).catch((err) => {
			_state.loading = false;
			panel.classList.remove("umre-fin-loading");
			console.error("Umre cost dashboard refresh failed", err);
		});
	}

	function render_payload(panel, p) {
		// Tour selector population (preserve current selection).
		const sel = panel.querySelector("#umre-fin-tour");
		const current = _state.tour;
		const opts = [`<option value="">${__("Tüm Turlar")}</option>`].concat(
			(p.tours || []).map((t) => `<option value="${frappe.utils.escape_html(t.name)}">${frappe.utils.escape_html(t.label)}</option>`)
		);
		sel.innerHTML = opts.join("");
		sel.value = current;

		// Hero strip.
		const hero = panel.querySelector("#umre-fin-hero");
		const profit_loss = (p.net_kar || 0) < 0 ? "is-loss" : "";
		hero.innerHTML = [
			hero_cell("revenue", __("Gelir"),         fmt_money(p.gelir, p.currency),       __("Tahsil edilen") + ": " + fmt_money(p.tahsil_edilen, p.currency)),
			hero_cell("cost",    __("Toplam Maliyet"), fmt_money(p.total_cost, p.currency), __("Kişi sayısı") + ": " + fmt_int(p.kisi_sayisi)),
			hero_cell("profit " + profit_loss, __("Net Kar"), fmt_money(p.net_kar, p.currency), __("Kalan alacak") + ": " + fmt_money(p.kalan_alacak, p.currency))
		].join("");

		// Cost cards (order = Cost Type.sort_order from server; meal/other hidden if 0).
		const cards = panel.querySelector("#umre-fin-cards");
		const total = Number(p.total_cost || 0);
		const ordered_codes = (p.component_order && p.component_order.length)
			? p.component_order
			: Object.keys(p.components || {});
		cards.innerHTML = ordered_codes.map((code) => {
			const c = (p.components || {})[code] || { label: code, amount: 0, color: "#dc2626" };
			const amt = Number(c.amount || 0);
			if (c.hide_if_zero && amt <= 0) {
				return "";
			}
			const share = total > 0 ? (amt / total) : 0;
			const zero_class = amt > 0 ? "" : " is-zero";
			return `
				<div class="umre-fin-cost-card${zero_class}" style="--cost-color:${c.color}">
					<div class="umre-fin-cost-card__label">${frappe.utils.escape_html(c.label)}</div>
					<div class="umre-fin-cost-card__amount">${fmt_money(amt, p.currency)}</div>
					<div class="umre-fin-cost-card__share">${fmt_pct(share)}</div>
				</div>`;
		}).join("");

		// Doughnut.
		render_chart(panel, p);

		// KPIs.
		const kpi = panel.querySelector("#umre-fin-kpi");
		const k = p.kpis || {};
		const kbk_cls = (k.kisi_basi_kar || 0) < 0 ? "is-loss" : "";
		kpi.innerHTML = [
			kpi_cell("cost",   __("Kişi Başı Maliyet"), fmt_money(k.kisi_basi_maliyet, p.currency)),
			kpi_cell("profit " + kbk_cls, __("Kişi Başı Kar"), fmt_money(k.kisi_basi_kar, p.currency)),
			kpi_cell("ratio",  __("Yemek Oranı"),       fmt_pct(k.yemek_orani))
		].join("");
	}

	function hero_cell(kind, label, value, sub) {
		return `
			<div class="umre-fin-hero__cell umre-fin-hero__cell--${kind}">
				<div class="umre-fin-hero__label">${frappe.utils.escape_html(label)}</div>
				<div class="umre-fin-hero__value">${value}</div>
				<div class="umre-fin-hero__sub">${frappe.utils.escape_html(sub)}</div>
			</div>`;
	}

	function kpi_cell(kind, label, value) {
		return `
			<div class="umre-fin-kpi__cell umre-fin-kpi__cell--${kind}">
				<div class="umre-fin-kpi__label">${frappe.utils.escape_html(label)}</div>
				<div class="umre-fin-kpi__value">${value}</div>
			</div>`;
	}

	function render_chart(panel, p) {
		const host = panel.querySelector("#umre-fin-chart");
		host.innerHTML = ""; // reset
		const labels = (p.chart && p.chart.labels) || [];
		if (!labels.length) {
			host.innerHTML = `<div class="umre-fin-empty">${__("Maliyet bileşeni bulunamadı.")}</div>`;
			_state.chart = null;
			return;
		}
		// Frappe Charts is bundled with desk; defer to it.
		if (typeof frappe.Chart !== "function") {
			host.innerHTML = `<div class="umre-fin-empty">${__("Grafik kütüphanesi yüklenmedi.")}</div>`;
			return;
		}
		const shareTot = Number((p.chart && p.chart.total_for_share) || p.total_cost || 0);
		_state.chart = new frappe.Chart(host, {
			type: "donut",
			data: {
				labels: labels,
				datasets: (p.chart && p.chart.datasets) || []
			},
			height: 280,
			colors: (p.chart && p.chart.colors) || [],
			truncateLegends: false,
			tooltipOptions: {
				formatTooltipY: (d) => {
					const v = Number(d || 0);
					const pct = shareTot > 0 ? ((v / shareTot) * 100).toFixed(1) : "0.0";
					return fmt_money(v, p.currency) + " (" + pct + "%)";
				}
			}
		});
	}

	// --- bootstrap -----------------------------------------------------

	function bootstrap() {
		// Mount on every route change AND on initial DOM ready.
		$(document).on("app_ready page-change", ensure_mounted);

		// Frappe v14 emits `change` on its router.
		if (frappe.router && frappe.router.on) {
			frappe.router.on("change", ensure_mounted);
		}

		// Watch for workspace re-renders (Frappe re-mounts the codex editor
		// when switching workspaces); MutationObserver is the safety net.
		const obs = new MutationObserver(() => {
			ensure_mounted();
		});
		obs.observe(document.body, { childList: true, subtree: true });

		// Realtime: refresh on any cost-component dirty signal. Debounce
		// because component generation fires 6 events per booking.
		if (frappe.realtime && frappe.realtime.on) {
			frappe.realtime.on("umre_cost_dashboard_dirty", () => {
				const btn = document.getElementById("umre-fin-refresh");
				if (btn) btn.classList.add("is-stale");
				schedule_refresh(800);
			});
			frappe.realtime.on("umre_operational_expense_dirty", () => {
				schedule_season_refresh(500);
			});
		}

		// Also refresh whenever an Umre Booking or Cost Component is saved
		// from anywhere in the desk (covers the "after booking insert" rule
		// even without a realtime event from the server).
		$(document).on("after_save", function (_evt, doc) {
			if (!doc) return;
			if (
				doc.doctype === "Umre Booking" ||
				doc.doctype === "Cost Component" ||
				doc.doctype === "Umre Tour" ||
				doc.doctype === "Tour Cost Configuration" ||
				doc.doctype === "Meal Cost Rule" ||
				doc.doctype === "Other Cost Rule"
			) {
				schedule_refresh(500);
			}
			if (doc.doctype === "Operational Expense") {
				schedule_season_refresh(400);
			}
		});

		// Initial mount attempt.
		ensure_mounted();
	}

	if (typeof frappe !== "undefined") {
		$(document).ready(bootstrap);
	}
})();
