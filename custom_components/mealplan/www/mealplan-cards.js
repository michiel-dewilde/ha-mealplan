/* SPDX-License-Identifier: GPL-3.0-or-later */
/**
 * The Meal Plan dashboard cards.
 *
 * Four cards, one file, no build step. Plain custom elements rather than Lit:
 * a card that reaches into the frontend's own module graph to borrow LitElement
 * breaks on the day that graph changes, and none of this is complicated enough
 * to need a framework. What it does need is to survive Home Assistant upgrades.
 *
 * Everything is read from `sensor.<name>_summary`'s attributes, which is the
 * contract, and written through the integration's own services. No card ever
 * touches a calendar.
 *
 * The cards are deliberately dumb: no state of their own beyond what is being
 * edited right now. The integration is the single source of truth, and a
 * service call comes back as a state change that redraws the card.
 */

const DOMAIN = "mealplan";
const VERSION = "1.0.0";

/* ------------------------------------------------------------------ strings */

const STRINGS = {
  en: {
    menu: "Menu",
    nothing_planned: "—",
    save: "Save",
    clear: "Clear the day",
    close: "Close",
    suggestions: "Suggested",
    often: "Often",
    why_usual_day: "usual day",
    why_overdue: "a while ago",
    why_never_planned: "never yet",
    why_expiring: "{x} expiring",
    dish: "Dish",
    note: "Note for this day",
    people: "p",
    extend: "One more day",
    reset_window: "Back to the week",
    shopping: "Shopping list",
    later: "Next trip",
    stock: "In the house",
    list_empty: "Nothing on the list.",
    add: "Add",
    sort: "Sort",
    print: "Print",
    complete_all: "Tick everything off",
    sure: "Sure?",
    completed_n: "{n} ticked off",
    fridge: "Fridge round",
    pantry: "Cupboard round",
    nothing_to_check: "Nothing to check.",
    nothing_in_house: "Nothing noted.",
    add_to_house: "Note something",
    no_date: "No date",
    tomorrow: "Tomorrow",
    day_after: "Day after",
    this_week: "This week",
    next_week: "Next week",
    exact: "Date",
    now: "This trip",
    now_short: "Buy",
    later_short: "Later",
    on_list: "On the list",
    keep: "Have it",
    more: "{n} more",
    reason_cadence: "due again",
    reason_no_history: "not seen yet",
    reason_menu: "on the menu",
    last_listed: "last {d}",
    today: "today",
    expired: "past",
    in_days: "in {n} d",
    route: "Walking route",
    route_hint: "Fix it while you are standing in it. The open list is re-sorted straight away.",
    up: "Up",
    down: "Down",
    scope_general: "Everything due",
    scope_menu: "For the menu",
    no_plan: "No meal plan found. Set one up first.",
    loading: "…",
  },
  nl: {
    menu: "Weekmenu",
    nothing_planned: "—",
    save: "Bewaren",
    clear: "Dag leegmaken",
    close: "Sluiten",
    suggestions: "Voorstel",
    often: "Vaak",
    why_usual_day: "vaste dag",
    why_overdue: "lang geleden",
    why_never_planned: "nog nooit",
    why_expiring: "{x} vervalt",
    dish: "Gerecht",
    note: "Notitie voor deze dag",
    people: "p",
    extend: "Dag erbij",
    reset_window: "Terug naar de week",
    shopping: "Boodschappen",
    later: "Volgende beurt",
    stock: "In huis",
    list_empty: "Niets op de lijst.",
    add: "Erbij",
    sort: "Sorteren",
    print: "Afdrukken",
    complete_all: "Alles afvinken",
    sure: "Zeker?",
    completed_n: "{n} afgevinkt",
    fridge: "Frigoronde",
    pantry: "Kastronde",
    nothing_to_check: "Niets na te kijken.",
    nothing_in_house: "Niets genoteerd.",
    add_to_house: "Iets noteren",
    no_date: "Geen datum",
    tomorrow: "Morgen",
    day_after: "Overmorgen",
    this_week: "Deze week",
    next_week: "Volgende week",
    exact: "Datum",
    now: "Deze beurt",
    now_short: "Nu",
    later_short: "Later",
    on_list: "Staat erop",
    keep: "Nog ok",
    more: "nog {n}",
    reason_cadence: "weer toe",
    reason_no_history: "nog niet gezien",
    reason_menu: "op het menu",
    last_listed: "laatst {d}",
    today: "vandaag",
    expired: "voorbij",
    in_days: "over {n} d",
    route: "Looproute",
    route_hint: "Zet het recht terwijl je erin staat. De openstaande lijst wordt meteen mee gesorteerd.",
    up: "Omhoog",
    down: "Omlaag",
    scope_general: "Alles wat toe is",
    scope_menu: "Voor het menu",
    no_plan: "Geen weekplanning gevonden. Stel er eerst een in.",
    loading: "…",
  },
};

/* ------------------------------------------------------------------ helpers */

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Parse an ISO date as a *local* day. `new Date("2026-08-04")` is UTC midnight,
 *  which formats as the day before in half the world. */
const parseISO = (iso) => {
  const [y, m, d] = String(iso).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};

const toISO = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

const todayISO = () => toISO(new Date());

const shiftISO = (iso, days) => {
  const date = parseISO(iso);
  date.setDate(date.getDate() + days);
  return toISO(date);
};

const daysBetween = (fromISO, toIso) => Math.round((parseISO(toIso) - parseISO(fromISO)) / 86400000);

/* --------------------------------------------------------------------- base */

class MealplanCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._error = null;
    if (this._root) this.redraw();
  }

  set hass(hass) {
    const previous = this._hass;
    this._hass = hass;
    if (!this._root) this.build();
    const id = this.entityId;
    if (!id) {
      this.renderMissing();
      return;
    }
    // The frontend hands every card a fresh `hass` on every state change in the
    // house. Redrawing on all of them would make the dish picker unusable.
    if (!previous || previous.states[id] !== hass.states[id]) this.redraw();
  }

  get hass() {
    return this._hass;
  }

  /** The summary sensor: whatever the card was configured with, else the first
   *  one that carries the meal plan contract. */
  get entityId() {
    if (this._config?.entity) return this._config.entity;
    if (this._found && this._hass?.states[this._found]) return this._found;
    this._found = Object.keys(this._hass?.states || {}).find(
      (id) => id.startsWith("sensor.") && this._hass.states[id].attributes?.window_start && this._hass.states[id].attributes?.entities,
    );
    return this._found;
  }

  get summary() {
    return this._hass?.states[this.entityId];
  }

  get attrs() {
    return this.summary?.attributes || {};
  }

  get lang() {
    const language = this._hass?.locale?.language || this._hass?.language || "en";
    return STRINGS[language] ? language : "en";
  }

  t(key, values) {
    let text = STRINGS[this.lang][key] ?? STRINGS.en[key] ?? key;
    for (const [name, value] of Object.entries(values || {})) text = text.replace(`{${name}}`, value);
    return text;
  }

  /** Format a date the way the browser's locale does. */
  fmt(iso, options) {
    return new Intl.DateTimeFormat(this.lang, options).format(parseISO(iso));
  }

  /** Call one of the integration's services, with the meal plan resolved.
   *
   *  Failure is recorded, never re-rendered from here: a failing read that
   *  redrew the card would call itself again, and again, for as long as the
   *  error lasted. The caller decides when to show it. */
  async call(service, data = {}, wantResponse = false) {
    const payload = { ...data };
    const entryId = this._config?.entry_id || this.attrs.entry_id;
    if (entryId) payload.entry_id = entryId;
    try {
      const result = await this._hass.callService(DOMAIN, service, payload, undefined, true, wantResponse);
      this._error = null;
      return wantResponse ? result?.response : result;
    } catch (err) {
      this._error = err?.message || String(err);
      return null;
    }
  }

  /** Build the shadow root once. Subclasses fill `this._root`. */
  build() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${BASE_CSS}${this.constructor.css || ""}</style><ha-card></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    this._root = this.shadowRoot;
    this.init();
  }

  init() {}

  renderMissing() {
    if (this._card) this._card.innerHTML = `<div class="pad muted">${escapeHtml(this.t("no_plan"))}</div>`;
  }

  errorLine() {
    return this._error ? `<div class="error">${escapeHtml(this._error)}</div>` : "";
  }

  getCardSize() {
    return 6;
  }
}

/* Shared look. Everything is expressed in Home Assistant's own theme variables,
   so the cards follow whatever theme the household picked, including dark. */
const BASE_CSS = `
:host { display: block; }
ha-card { overflow: hidden; }
.pad { padding: 12px 16px; }
.muted { color: var(--secondary-text-color); }
.error {
  margin: 8px 16px; padding: 8px 10px; border-radius: 8px;
  background: rgba(var(--rgb-error-color, 219,68,55), .12);
  color: var(--error-color, #db4437); font-size: 13px;
}
header {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  padding: 14px 16px 8px;
}
header h1 {
  margin: 0; font-size: var(--ha-card-header-font-size, 20px);
  font-weight: 400; color: var(--ha-card-header-color, var(--primary-text-color));
  line-height: 1.2;
}
header .sub { font-size: 13px; color: var(--secondary-text-color); margin-left: auto; }
button {
  font: inherit; color: inherit; background: none; border: none; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 12px 12px; }
/* A phone is 390px wide and a Dutch button label is long. Wrapping onto a
   second row is fine; a label sliced off at the card edge is not. */
.actions button {
  flex: 1 1 auto; min-width: 104px; min-height: 40px; padding: 0 12px;
  border-radius: 10px; border: 1px solid var(--divider-color); font-size: 14px;
  white-space: nowrap;
}
.actions button.primary {
  background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent;
}
.actions button:active { opacity: .7; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 7px 12px; border-radius: 999px; border: 1px solid var(--divider-color);
  font-size: 14px; line-height: 1.2; background: var(--secondary-background-color);
}
.chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
input[type="text"], input[type="date"], input[type="search"] {
  font: inherit; width: 100%; box-sizing: border-box; min-height: 40px;
  padding: 0 10px; border-radius: 10px; border: 1px solid var(--divider-color);
  background: var(--card-background-color); color: var(--primary-text-color);
}
input:focus { outline: 2px solid var(--primary-color); outline-offset: -2px; }
`;

/* -------------------------------------------------------------- menu card */

class MealplanMenuCard extends MealplanCard {
  static css = `
.days { display: block; }
.day {
  display: flex; gap: 12px; align-items: flex-start; width: 100%; text-align: left;
  padding: 10px 16px; border-top: 1px solid var(--divider-color);
}
.day:first-child { border-top: none; }
.day .when { flex: 0 0 46px; line-height: 1.15; }
.day .when b { display: block; font-size: 13px; text-transform: lowercase; }
.day .when span { font-size: 12px; color: var(--secondary-text-color); }
.day.today .when b { color: var(--primary-color); font-weight: 700; }
.day .what { flex: 1 1 auto; min-width: 0; }
/* An empty day is a normal state, not a fault: muted, never red. */
.day .dish { display: block; font-size: 16px; overflow-wrap: anywhere; }
.day.free .dish { color: var(--secondary-text-color); }
.day .note { display: block; font-size: 13px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
/* One line, cut off with an ellipsis. A holiday calendar can put a dozen
   entries on a single day, and they must never push the card wider than the
   phone it is being read on. */
.day .cal {
  display: block; font-size: 12px; color: var(--secondary-text-color); opacity: .85;
  margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.day .cal::before { content: "· "; }
.day .who { flex: 0 0 auto; font-size: 12px; color: var(--secondary-text-color); padding-top: 2px; }
.sheet { border-top: 2px solid var(--primary-color); padding: 12px 16px 4px; background: var(--secondary-background-color); }
.sheet .title { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.sheet .title b { font-size: 15px; }
.sheet .title button { margin-left: auto; font-size: 20px; line-height: 1; padding: 4px 8px; }
.sheet .label { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); margin: 10px 0 4px; }
.sheet .chip small { display: block; font-size: 11px; opacity: .7; }
.sheet .field { margin-top: 10px; }
`;

  init() {
    this._card.innerHTML = `<header><h1></h1><span class="sub"></span></header><div class="days"></div><div class="foot"></div>`;
    this._card.addEventListener("click", (event) => this.onClick(event));
  }

  redraw() {
    if (!this.summary) return this.renderMissing();
    const a = this.attrs;
    this._card.querySelector("h1").textContent = this._config.title ?? this.t("menu");
    this._card.querySelector(".sub").textContent =
      `${this.fmt(a.window_start, { day: "numeric", month: "short" })} – ${this.fmt(a.window_end, { day: "numeric", month: "short" })}`;
    this.renderDays();
    this.renderFoot();
    if (this._open) this.renderSheet();
    this.loadExtras();
  }

  renderDays() {
    const today = todayISO();
    const events = this._week || {};
    this._card.querySelector(".days").innerHTML = (this.attrs.menu || [])
      .map((day) => {
        const calendar = (events[day.date] || []).map((e) => e.summary).filter(Boolean);
        // Two entries and a count. Whoever has eleven things on today already
        // knows; what they need from this line is that the day is busy.
        const shown = calendar.slice(0, 2).join(" · ");
        const rest = calendar.length > 2 ? ` +${calendar.length - 2}` : "";
        return `<button class="day${day.date === today ? " today" : ""}${day.dish ? "" : " free"}" data-date="${day.date}">
          <span class="when"><b>${escapeHtml(this.fmt(day.date, { weekday: "short" }))}</b><span>${escapeHtml(this.fmt(day.date, { day: "numeric" }))}</span></span>
          <span class="what">
            <span class="dish">${escapeHtml(day.dish || this.t("nothing_planned"))}</span>
            ${day.note ? `<span class="note">${escapeHtml(day.note)}</span>` : ""}
            ${calendar.length ? `<span class="cal" title="${escapeHtml(calendar.join(" · "))}">${escapeHtml(shown + rest)}</span>` : ""}
          </span>
          ${day.people ? `<span class="who">${day.people}${this.t("people")}</span>` : ""}
        </button>`;
      })
      .join("");
  }

  renderFoot() {
    const extended = this.attrs.window_extended;
    this._card.querySelector(".foot").innerHTML =
      `${this.errorLine()}<div class="actions">
        <button data-act="extend">${escapeHtml(this.t("extend"))}</button>
        ${extended ? `<button data-act="reset">${escapeHtml(this.t("reset_window"))}</button>` : ""}
      </div>`;
  }

  /** The calendar entries, the suggestions and the dish frequencies are
   *  asynchronous; the menu itself sits in the sensor, so the card is already
   *  useful before any of them arrive. */
  async loadExtras() {
    if (this._loading) return;
    this._loading = true;
    const week = await this.call("get_week", {}, true);
    if (week?.days) {
      this._week = Object.fromEntries(week.days.map((day) => [day.date, day.calendar || []]));
      this.renderDays();
    }
    const dishes = await this.call("list_dishes", {}, true);
    if (dishes?.dishes) this._dishStats = dishes.dishes;
    const suggested = await this.call("suggest_menu", { limit: 3 }, true);
    if (suggested?.suggestions) {
      this._suggestions = Object.fromEntries(suggested.suggestions.map((s) => [s.date, s.candidates || []]));
    }
    if (this._open) this.renderSheet();
    if (this._error) this.renderFoot();
    this._loading = false;
  }

  onClick(event) {
    const day = event.target.closest(".day");
    if (day) return this.openSheet(day.dataset.date);
    const action = event.target.closest("[data-act]")?.dataset.act;
    if (!action) return;
    if (action === "extend") this.call("set_window", { extend_days: 1 });
    if (action === "reset") this.call("set_window", { reset: true });
    if (action === "close") this.closeSheet();
    if (action === "pick") this.plan(event.target.closest("[data-dish]").dataset.dish);
    if (action === "save") this.save();
    if (action === "clear") this.call("plan_menu", { date: this._open, clear: true }).then(() => this.closeSheet());
  }

  openSheet(date) {
    this._open = date;
    this.renderSheet();
    this._card.querySelector(".sheet")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  closeSheet() {
    this._open = null;
    this._card.querySelector(".sheet")?.remove();
  }

  /** The eight dishes this household eats most cover about four days in five.
   *  They are one tap; everything else is a tap and some typing. */
  frequent() {
    const known = this.attrs.dishes || [];
    const ranked = (this._dishStats || []).slice().sort((a, b) => b.times - a.times);
    const top = ranked.map((d) => d.name).filter((name) => known.includes(name));
    return (top.length ? top : known).slice(0, 8);
  }

  renderSheet() {
    const date = this._open;
    if (!date) return;
    const stored = (this.attrs.menu || []).find((d) => d.date === date) || {};
    // Suggestions arrive while the sheet is already open. Whatever is half
    // typed wins over what the sensor last said.
    const existing = this._card.querySelector(".sheet");
    const day = existing
      ? {
          ...stored,
          dish: existing.querySelector("input.dish").value,
          note: existing.querySelector("input.note").value,
        }
      : stored;
    const suggestions = (this._suggestions?.[date] || []).map((c) => c.dish);
    const frequent = this.frequent().filter((name) => !suggestions.includes(name));

    const chip = (name, hint) =>
      `<button class="chip${stored.dish === name ? " on" : ""}" data-act="pick" data-dish="${escapeHtml(name)}">${escapeHtml(name)}${hint ? `<small>${escapeHtml(hint)}</small>` : ""}</button>`;

    const html = `<div class="sheet">
      <div class="title">
        <b>${escapeHtml(this.fmt(date, { weekday: "long", day: "numeric", month: "long" }))}</b>
        <button data-act="close" aria-label="${escapeHtml(this.t("close"))}">✕</button>
      </div>
      ${suggestions.length ? `<div class="label">${escapeHtml(this.t("suggestions"))}</div><div class="chips">${suggestions.map((name) => chip(name, this.reason(date, name))).join("")}</div>` : ""}
      ${frequent.length ? `<div class="label">${escapeHtml(this.t("often"))}</div><div class="chips">${frequent.map((name) => chip(name)).join("")}</div>` : ""}
      <div class="field"><input type="text" class="dish" list="mealplan-dishes" placeholder="${escapeHtml(this.t("dish"))}" value="${escapeHtml(day.dish || "")}"></div>
      <div class="field"><input type="text" class="note" placeholder="${escapeHtml(this.t("note"))}" value="${escapeHtml(day.note || "")}"></div>
      <datalist id="mealplan-dishes">${(this.attrs.dishes || []).map((name) => `<option value="${escapeHtml(name)}"></option>`).join("")}</datalist>
      <div class="actions">
        <button class="primary" data-act="save">${escapeHtml(this.t("save"))}</button>
        <button data-act="clear">${escapeHtml(this.t("clear"))}</button>
      </div>
    </div>`;

    if (existing) existing.outerHTML = html;
    else this._card.querySelector(".foot").insertAdjacentHTML("beforebegin", html);
  }

  /** Why a dish is being suggested. Worth showing: "Friday" and "the mince
   *  expires" are very different reasons to accept the same suggestion. */
  reason(date, dish) {
    const candidate = (this._suggestions?.[date] || []).find((c) => c.dish === dish);
    const reason = candidate?.reasons?.[0];
    if (!reason) return "";
    if (reason.startsWith("expiring:")) return this.t("why_expiring", { x: reason.slice(9).split(",")[0].trim() });
    return this.t(`why_${reason}`);
  }

  async plan(dish) {
    const date = this._open;
    await this.call("plan_menu", { date, dish });
    this.closeSheet();
  }

  async save() {
    const sheet = this._card.querySelector(".sheet");
    const dish = sheet.querySelector("input.dish").value.trim();
    const note = sheet.querySelector("input.note").value.trim();
    const date = this._open;
    if (!dish && !note) return this.call("plan_menu", { date, clear: true }).then(() => this.closeSheet());
    await this.call("plan_menu", { date, dish, note });
    this.closeSheet();
  }

  static getStubConfig() {
    return {};
  }
}

/* -------------------------------------------------------------- list card */

class MealplanListCard extends MealplanCard {
  static css = `
section { padding: 2px 16px 8px; }
h2 {
  margin: 10px 0 2px; font-size: 12px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--secondary-text-color); border-bottom: 1px solid var(--divider-color); padding-bottom: 2px;
}
ul { list-style: none; margin: 0; padding: 0; }
li { display: flex; align-items: flex-start; gap: 10px; padding: 2px 0; }
li .tick {
  flex: 0 0 auto; width: 34px; height: 34px; margin-left: -6px; display: grid; place-items: center;
}
li .tick i {
  width: 18px; height: 18px; border: 2px solid var(--secondary-text-color);
  border-radius: 4px; display: block;
}
li .txt { flex: 1 1 auto; min-width: 0; font-size: 15px; padding-top: 7px; overflow-wrap: anywhere; }
li .txt small { display: block; font-size: 12px; color: var(--secondary-text-color); }
li em {
  font-style: normal; font-size: 11px; border: 1px solid var(--divider-color);
  border-radius: 4px; padding: 0 4px; margin-left: 6px; color: var(--secondary-text-color);
}
li .due { flex: 0 0 auto; font-size: 12px; padding-top: 9px; color: var(--secondary-text-color); }
li .due.urgent { color: var(--error-color, #db4437); font-weight: 600; }
.add { display: flex; gap: 8px; padding: 8px 16px 4px; }
.add button { border: 1px solid var(--divider-color); border-radius: 10px; padding: 0 14px; min-height: 40px; }
.done { padding: 4px 16px 0; font-size: 13px; color: var(--secondary-text-color); }
`;

  setConfig(config) {
    super.setConfig(config);
    this._list = this._config.list || "shopping";
  }

  init() {
    this._card.innerHTML = `<header><h1></h1><span class="sub"></span></header>
      <div class="add"><input type="text" placeholder=""><button data-act="add">＋</button></div>
      <div class="body"></div><div class="foot"></div>`;
    this._card.addEventListener("click", (event) => this.onClick(event));
    this._card.querySelector(".add input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.addItem();
    });
  }

  redraw() {
    if (!this.summary) return this.renderMissing();
    this._card.querySelector("h1").textContent = this._config.title ?? this.t(this._list);
    const input = this._card.querySelector(".add input");
    input.placeholder = this.t("add");
    this._card.querySelector(".add").style.display = this._config.show_add === false ? "none" : "";
    this.load();
  }

  async load() {
    const data = await this.call("get_list", { list: this._list }, true);
    if (!data) return;
    this._data = data;
    this._card.querySelector(".sub").textContent =
      this._list === "shopping" && data.store ? data.store : `${data.open}`;
    this.renderBody();
    this.renderFoot();
  }

  renderBody() {
    const groups = this._data?.groups || [];
    const today = todayISO();
    this._card.querySelector(".body").innerHTML = groups.length
      ? groups
          .map(
            (group) => `<section><h2>${escapeHtml(group.label)}</h2><ul>${group.items
              .map((item) => {
                const left = item.due ? daysBetween(today, item.due) : null;
                const due =
                  left === null
                    ? ""
                    : `<span class="due${left <= 2 ? " urgent" : ""}">${escapeHtml(
                        left < 0 ? this.t("expired") : left === 0 ? this.t("today") : this.t("in_days", { n: left }),
                      )}</span>`;
                return `<li>
                  <button class="tick" data-act="tick" data-uid="${escapeHtml(item.uid)}" aria-label="${escapeHtml(item.summary)}"><i></i></button>
                  <span class="txt">${escapeHtml(item.summary)}${item.availability ? `<em>${escapeHtml(item.availability)}</em>` : ""}${item.note ? `<small>${escapeHtml(item.note)}</small>` : ""}</span>
                  ${due}
                </li>`;
              })
              .join("")}</ul></section>`,
          )
          .join("")
      : `<div class="pad muted">${escapeHtml(this.t("list_empty"))}</div>`;
  }

  renderFoot() {
    if (this._config.actions === false) {
      this._card.querySelector(".foot").innerHTML = this.errorLine();
      return;
    }
    const done = this._data?.completed || 0;
    this._card.querySelector(".foot").innerHTML =
      `${done ? `<div class="done">${escapeHtml(this.t("completed_n", { n: done }))}</div>` : ""}
      ${this.errorLine()}
      <div class="actions">
        <button data-act="sort">${escapeHtml(this.t("sort"))}</button>
        <button data-act="complete">${escapeHtml(this._confirming ? this.t("sure") : this.t("complete_all"))}</button>
        <button data-act="print">${escapeHtml(this.t("print"))}</button>
      </div>`;
  }

  onClick(event) {
    const action = event.target.closest("[data-act]")?.dataset.act;
    if (!action) return;
    if (action === "add") this.addItem();
    if (action === "tick") this.tick(event.target.closest("[data-uid]").dataset.uid);
    if (action === "sort") this.call("sort_list").then(() => this.load());
    if (action === "print") this.print();
    if (action === "complete") this.completeAll();
  }

  async addItem() {
    const input = this._card.querySelector(".add input");
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    if (this._list === "stock") await this.call("add_stock", { article: value });
    else await this.call("running_low", { article: value, when: this._list === "later" ? "later" : "now" });
    this.load();
  }

  /** Ticking goes through the to-do entity rather than a service of ours, so
   *  the built-in to-do card and this one stay the same list. */
  async tick(uid) {
    const entity = this.attrs.entities?.[this._list];
    if (!entity) return;
    await this._hass.callService("todo", "update_item", { item: uid, status: "completed" }, { entity_id: entity });
    this.load();
  }

  async completeAll() {
    if (!this._confirming) {
      this._confirming = true;
      this.renderFoot();
      setTimeout(() => {
        this._confirming = false;
        this.renderFoot();
      }, 4000);
      return;
    }
    this._confirming = false;
    await this.call("complete_all");
    this.load();
  }

  /** The print view needs authentication, and a new tab carries none. A signed
   *  path is how the frontend hands out a URL you can simply open. */
  async print() {
    const result = await this.call("print_list", {}, true);
    if (!result?.url) return;
    try {
      const signed = await this._hass.callWS({ type: "auth/sign_path", path: result.url, expires: 300 });
      window.open(signed.path, "_blank");
    } catch {
      window.open(result.url, "_blank");
    }
  }

  static getStubConfig() {
    return { list: "shopping" };
  }
}

/* ------------------------------------------------------------- round card */

class MealplanRoundCard extends MealplanCard {
  static css = `
/* Wrapping, not shrinking: three buttons and an article name do not fit on
   390px, and a row that overflows takes the whole card off the screen with it. */
.row {
  display: flex; align-items: center; gap: 8px; padding: 8px 16px;
  border-top: 1px solid var(--divider-color); flex-wrap: wrap;
}
.row:first-child { border-top: none; }
.row .name { flex: 1 1 130px; min-width: 0; font-size: 15px; overflow-wrap: anywhere; }
.row .name small { display: block; font-size: 12px; color: var(--secondary-text-color); }
.row .btns { display: flex; gap: 6px; flex: 0 0 auto; margin-left: auto; }
.row .btns button {
  min-height: 36px; padding: 0 12px; border-radius: 9px; border: 1px solid var(--divider-color);
  font-size: 13px; white-space: nowrap;
}
.row .btns button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
.row.listed { opacity: .5; }
.badge { font-size: 12px; padding: 4px 8px; border-radius: 999px; background: var(--secondary-background-color); }
.badge.urgent { background: var(--error-color, #db4437); color: #fff; }
.dates { padding: 8px 16px 12px; background: var(--secondary-background-color); border-top: 1px solid var(--divider-color); }
.dates .who { font-size: 14px; margin-bottom: 8px; }
.dates input[type="date"] { margin-top: 8px; }
.scope { display: flex; gap: 6px; padding: 0 16px 8px; }
.section { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--secondary-text-color); padding: 12px 16px 2px; }
.pool { padding: 4px 16px 12px; }
`;

  setConfig(config) {
    super.setConfig(config);
    this._mode = this._config.mode || "fridge";
    this._scope = this._config.scope || "general";
    this._dismissed = new Set();
  }

  init() {
    this._card.innerHTML = `<header><h1></h1></header><div class="body"></div><div class="foot"></div>`;
    this._card.addEventListener("click", (event) => this.onClick(event));
    this._card.addEventListener("change", (event) => {
      if (event.target.classList.contains("exact")) this.pick(event.target.value);
    });
  }

  redraw() {
    if (!this.summary) return this.renderMissing();
    this._card.querySelector("h1").textContent = this._config.title ?? this.t(this._mode === "pantry" ? "pantry" : "fridge");
    this.load();
  }

  async load() {
    if (this._mode === "pantry") {
      const data = await this.call("get_pantry_check", { scope: this._scope }, true);
      this._items = (data?.articles || []).filter((a) => !this._dismissed.has(a.article));
    } else {
      const data = await this.call("get_list", { list: "stock" }, true);
      const items = (data?.groups || []).flatMap((group) => group.items);
      // Soonest first; the ones without a date sit at the end and stay there
      // until somebody ticks them off. Nothing disappears on its own.
      items.sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
      this._items = items;
    }
    this.render();
  }

  render() {
    const today = todayISO();
    const body = this._card.querySelector(".body");
    if (this._mode === "pantry") {
      body.innerHTML =
        `<div class="scope">
          <button class="chip${this._scope === "general" ? " on" : ""}" data-act="scope" data-scope="general">${escapeHtml(this.t("scope_general"))}</button>
          <button class="chip${this._scope === "menu" ? " on" : ""}" data-act="scope" data-scope="menu">${escapeHtml(this.t("scope_menu"))}</button>
        </div>` +
        (this._items?.length
          ? this._items
              .map(
                (item) => `<div class="row${item.already_listed ? " listed" : ""}">
                  <span class="name">${escapeHtml(item.article)}<small>${escapeHtml(this.why(item))}</small></span>
                  <span class="btns">
                    <button class="primary" data-act="low" data-article="${escapeHtml(item.article)}" data-when="now">${escapeHtml(this.t("now_short"))}</button>
                    <button data-act="low" data-article="${escapeHtml(item.article)}" data-when="later">${escapeHtml(this.t("later_short"))}</button>
                    <button data-act="keep" data-article="${escapeHtml(item.article)}">${escapeHtml(this.t("keep"))}</button>
                  </span>
                </div>`,
              )
              .join("")
          : `<div class="pad muted">${escapeHtml(this.t("nothing_to_check"))}</div>`);
      this._card.querySelector(".foot").innerHTML = this.errorLine();
      return;
    }

    const pool = (this.attrs.watch_expiry || []).filter(
      (name) => !(this._items || []).some((item) => (item.article || item.summary) === name),
    );
    body.innerHTML =
      (this._items?.length
        ? this._items
            .map((item) => {
              const left = item.due ? daysBetween(today, item.due) : null;
              const badge =
                left === null
                  ? this.t("no_date")
                  : left < 0
                    ? this.t("expired")
                    : left === 0
                      ? this.t("today")
                      : this.t("in_days", { n: left });
              return `<div class="row">
                <span class="name">${escapeHtml(item.summary)}</span>
                <button class="badge${left !== null && left <= 2 ? " urgent" : ""}" data-act="date" data-article="${escapeHtml(item.summary)}">${escapeHtml(badge)}</button>
                <span class="btns"><button data-act="tick" data-uid="${escapeHtml(item.uid)}">✓</button></span>
              </div>`;
            })
            .join("")
        : `<div class="pad muted">${escapeHtml(this.t("nothing_in_house"))}</div>`) +
      // Thirty-odd articles worth watching is a wall of chips on a phone, and
      // the round is about what is already in the fridge. Folded away until asked.
      (pool.length
        ? `<div class="actions"><button data-act="pool">${escapeHtml(this.t("add_to_house"))}${this._showPool ? " ▴" : " ▾"}</button></div>
           ${this._showPool ? `<div class="pool chips">${pool
             .map((name) => `<button class="chip" data-act="date" data-article="${escapeHtml(name)}">${escapeHtml(name)}</button>`)
             .join("")}</div>` : ""}`
        : "");

    this._card.querySelector(".foot").innerHTML = this.errorLine() + (this._picking ? this.datePicker() : "");
  }

  /** Why this article is being asked about, and when it last went on a list.
   *
   *  "Due" on its own is an assertion you cannot check. "Due · last 3 Jun" is
   *  one you can: you either remember buying coffee since, or you do not. */
  why(item) {
    if (item.already_listed) return this.t("on_list");
    const parts = [this.t(`reason_${item.reason}`)];
    if (item.last_listed) parts.push(this.t("last_listed", { d: this.fmt(item.last_listed, { day: "numeric", month: "short" }) }));
    return parts.join(" · ");
  }

  /** Dates the way they are actually said out loud while the fridge door is
   *  open. The exact field is there for the one time in ten it matters. */
  datePicker() {
    const today = todayISO();
    const options = [
      [this.t("tomorrow"), shiftISO(today, 1)],
      [this.t("day_after"), shiftISO(today, 2)],
      [this.t("this_week"), shiftISO(today, 7)],
      [this.t("next_week"), shiftISO(today, 14)],
    ];
    return `<div class="dates">
      <div class="who">${escapeHtml(this._picking)}</div>
      <div class="chips">
        ${options.map(([label, iso]) => `<button class="chip" data-act="pick" data-date="${iso}">${escapeHtml(label)}</button>`).join("")}
        <button class="chip" data-act="pick" data-date="">${escapeHtml(this.t("no_date"))}</button>
      </div>
      <input type="date" class="exact" min="${today}">
    </div>`;
  }

  onClick(event) {
    const target = event.target.closest("[data-act]");
    const action = target?.dataset.act;
    if (!action) return;
    if (action === "scope") {
      this._scope = target.dataset.scope;
      this.load();
    }
    if (action === "low") {
      this.call("running_low", { article: target.dataset.article, when: target.dataset.when }).then(() => this.load());
    }
    if (action === "keep") {
      this._dismissed.add(target.dataset.article);
      this.load();
    }
    if (action === "pool") {
      this._showPool = !this._showPool;
      this.render();
    }
    if (action === "tick") this.tick(target.dataset.uid);
    if (action === "date") {
      this._picking = target.dataset.article;
      this._card.querySelector(".foot").innerHTML = this.datePicker();
      this._card.querySelector(".dates").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    if (action === "pick") this.pick(target.dataset.date);
  }

  async pick(iso) {
    const article = this._picking;
    this._picking = null;
    await this.call("add_stock", iso ? { article, expiry: iso } : { article });
    this.load();
  }

  async tick(uid) {
    const entity = this.attrs.entities?.stock;
    if (!entity) return;
    await this._hass.callService("todo", "update_item", { item: uid, status: "completed" }, { entity_id: entity });
    this.load();
  }

  static getStubConfig() {
    return { mode: "fridge" };
  }
}

/* ------------------------------------------------------------- route card */

class MealplanRouteCard extends MealplanCard {
  static css = `
.hint { padding: 0 16px 8px; font-size: 13px; color: var(--secondary-text-color); }
.stores { padding: 0 16px 10px; }
.row {
  display: flex; align-items: center; gap: 8px; padding: 6px 16px;
  border-top: 1px solid var(--divider-color);
}
.row .n { flex: 0 0 22px; font-size: 12px; color: var(--secondary-text-color); }
.row .name { flex: 1 1 auto; font-size: 15px; }
.row button {
  width: 42px; height: 42px; border-radius: 10px; border: 1px solid var(--divider-color); font-size: 17px;
}
.row button[disabled] { opacity: .3; }
`;

  init() {
    this._card.innerHTML = `<header><h1></h1></header>
      <div class="stores chips"></div><div class="hint"></div><div class="body"></div><div class="foot"></div>`;
    this._card.addEventListener("click", (event) => this.onClick(event));
  }

  /** The store selector, by whatever entity id it carries in this house. */
  get storeEntity() {
    return this._hass?.states[this.attrs.entities?.store];
  }

  set hass(hass) {
    const before = this._hass?.states[this.attrs.entities?.store];
    super.hass = hass;
    // The route is per store, so a change of store is a change of card.
    if (this._root && before !== this.storeEntity) this.redraw();
  }

  get hass() {
    return this._hass;
  }

  redraw() {
    if (!this.summary) return this.renderMissing();
    this._card.querySelector("h1").textContent = this._config.title ?? this.t("route");
    const select = this.storeEntity;
    this._card.querySelector(".stores").innerHTML = (select?.attributes?.options || [])
      .map(
        (name) =>
          `<button class="chip${name === select.state ? " on" : ""}" data-act="store" data-store="${escapeHtml(name)}">${escapeHtml(name)}</button>`,
      )
      .join("");
    this._card.querySelector(".hint").textContent = this.t("route_hint");
    const departments = this.attrs.departments || [];
    this._card.querySelector(".body").innerHTML = departments
      .map(
        (department, index) => `<div class="row">
          <span class="n">${index + 1}</span>
          <span class="name">${escapeHtml(department.label)}</span>
          <button data-act="up" data-key="${escapeHtml(department.key)}" aria-label="${escapeHtml(this.t("up"))}"${index === 0 ? " disabled" : ""}>▲</button>
          <button data-act="down" data-key="${escapeHtml(department.key)}" aria-label="${escapeHtml(this.t("down"))}"${index === departments.length - 1 ? " disabled" : ""}>▼</button>
        </div>`,
      )
      .join("");
    this._card.querySelector(".foot").innerHTML = this.errorLine();
  }

  onClick(event) {
    const target = event.target.closest("[data-act]");
    if (!target || target.disabled) return;
    if (target.dataset.act === "store") {
      this._hass.callService(
        "select",
        "select_option",
        { option: target.dataset.store },
        { entity_id: this.attrs.entities?.store },
      );
      return;
    }
    const order = (this.attrs.departments || []).map((department) => department.key);
    const from = order.indexOf(target.dataset.key);
    const to = target.dataset.act === "up" ? from - 1 : from + 1;
    if (from < 0 || to < 0 || to >= order.length) return;
    order.splice(to, 0, order.splice(from, 1)[0]);
    this.call("set_store_order", { departments: order });
  }

  getCardSize() {
    return 8;
  }

  static getStubConfig() {
    return {};
  }
}

/* ----------------------------------------------------------------- register */

const CARDS = [
  ["mealplan-menu-card", MealplanMenuCard, "Meal Plan: menu", "Seven days, what the calendars say, and a dish two taps away."],
  ["mealplan-list-card", MealplanListCard, "Meal Plan: list", "A shopping list with department headings, in the walking order of the store."],
  ["mealplan-round-card", MealplanRoundCard, "Meal Plan: round", "The fridge round and the cupboard round: one screen, one item after another."],
  ["mealplan-route-card", MealplanRouteCard, "Meal Plan: walking route", "Correct the order the departments come in, standing in the shop."],
];

window.customCards = window.customCards || [];

for (const [name, cls, label, description] of CARDS) {
  if (!customElements.get(name)) customElements.define(name, cls);
  if (!window.customCards.some((card) => card.type === name)) {
    window.customCards.push({
      type: name,
      name: label,
      description,
      preview: false,
      documentationURL: "https://github.com/michiel-dewilde/ha-mealplan",
    });
  }
}

console.info(`%c MEAL PLAN CARDS %c ${VERSION} `, "background:#03a9f4;color:#fff;border-radius:3px 0 0 3px", "background:#555;color:#fff;border-radius:0 3px 3px 0");
