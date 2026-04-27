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
		const cur = currency || "USD";
		// Prefer the global helper — it knows the symbol for any registered Currency.
		if (typeof format_currency === "function") {
			try { return format_currency(n, cur); } catch (e) { /* fall through */ }
		}
		try {
			return frappe.format(n, { fieldtype: "Currency", options: cur });
		} catch (e) {
			return cur + " " + n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		}
	}

	function fmt_pct(value) {
		const n = Number(value || 0) * 100;
		return n.toFixed(1) + "%";
	}

	function fmt_int(value) {
		return Number(value || 0).toLocaleString("tr-TR");
	}

	function on_target_route() {
		const route = (frappe.get_route && frappe.get_route()) || [];
		if (!route || route.length < 2) return false;
		if (route[0] !== "Workspaces") return false;
		return WORKSPACE_ROUTES.includes(route[1]);
	}

	function ensure_mounted() {
		if (!on_target_route()) {
			// Cleanly detach when navigating away.
			const existing = document.getElementById(PANEL_ID);
			if (existing) existing.remove();
			_state.chart = null;
			return;
		}

		// Existing panel? leave it (we'll re-render in place).
		if (document.getElementById(PANEL_ID)) return;

		// Find the workspace body container. Frappe v14 wraps workspace
		// content in `.codex-editor` (block editor). Mount above it.
		const candidates = [
			document.querySelector(".workspace-sidebar-toggle ~ .codex-editor"),
			document.querySelector(".layout-main-section .codex-editor"),
			document.querySelector(".codex-editor")
		];
		const container = candidates.find(Boolean);
		if (!container) return; // Will retry on next mutation.

		const panel = document.createElement("div");
		panel.id = PANEL_ID;
		panel.className = "umre-fin-panel";
		panel.innerHTML = render_skeleton();
		container.parentNode.insertBefore(panel, container);

		wire_events(panel);
		schedule_refresh(0);
	}

	function render_skeleton() {
		return `
			<div class="umre-fin-panel__header">
				<div class="umre-fin-panel__title"><span class="dot"></span>${__("Finansal Panel")}</div>
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

	function refresh() {
		const panel = document.getElementById(PANEL_ID);
		if (!panel) return;
		_state.loading = true;
		panel.classList.add("umre-fin-loading");

		frappe.call({
			method: ENDPOINT,
			args: { tour: _state.tour || "" },
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

		// Cost cards.
		const cards = panel.querySelector("#umre-fin-cards");
		const total = Number(p.total_cost || 0);
		const ordered_codes = ["HOTEL", "FLIGHT", "VISA", "DIYANET", "MEAL", "OTHER", "MANUAL"];
		cards.innerHTML = ordered_codes.map((code) => {
			const c = (p.components || {})[code] || { label: code, amount: 0, color: "#dc2626" };
			const amt = Number(c.amount || 0);
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
				formatTooltipY: (d) => fmt_money(d, p.currency)
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
		}

		// Also refresh whenever an Umre Booking or Cost Component is saved
		// from anywhere in the desk (covers the "after booking insert" rule
		// even without a realtime event from the server).
		$(document).on("after_save", function (_evt, doc) {
			if (!doc) return;
			if (doc.doctype === "Umre Booking" || doc.doctype === "Cost Component") {
				schedule_refresh(500);
			}
		});

		// Initial mount attempt.
		ensure_mounted();
	}

	if (typeof frappe !== "undefined") {
		$(document).ready(bootstrap);
	}
})();
