/*
 * Family Board cards: the family's calendars, birthdays, events, trips and chores on one dashboard, in both houses.
 * Every card reads a Family Board sensor and finds it on its own, so the simplest configuration is one line:
 *
 * type: custom:family-today-card        today, one column per person and one for everyone (sensor.family_board_today)
 * type: custom:family-week-card         the days ahead                                   (sensor.family_board_week)
 * type: custom:family-birthdays-card    whose birthday is next, and in how many days      (sensor.family_board_birthdays)
 * type: custom:family-events-card       the Events board: what the family has tickets for (sensor.family_board_events)
 * type: custom:family-trip-card         the next journey, counting down, on both homes' clocks (sensor.family_board_trip)
 * type: custom:family-chores-card       everyone's chores today, tick them here, points this week (sensor.family_board_chores_*)
 *
 * Options every card takes: entity (a sensor other than the default), title ("" for none). The rest are documented on
 * each card below. Built for a phone first; the columns and lists reflow for a wall screen.
 *
 * The integration serves this file and registers it as a dashboard resource; nothing to install.
 * Copyright (c) 2026 Mark Christie. MIT licence.
 */
(function () {
  const DAY_MS = 86400000;
  const STR = {
    en: {
      today: "Today", tomorrow: "Tomorrow", yesterday: "Yesterday", allDay: "All day", everyone: "Everyone",
      nothingToday: "Nothing on today", nothingAhead: "Nothing coming up", week: "Week ahead",
      birthdays: "Birthdays", noBirthdays: "No birthdays yet", turns: (n) => `turns ${n}`, inDays: (n) => `in ${n} days`,
      events: "Events", nothingOnBoard: "Nothing on the board", more: (n) => `+${n} more`,
      trip: "Next trip", noTrips: "No trips booked", underWay: "Under way", dayToGo: "day to go", daysToGo: "days to go",
      departs: "Departs", arrives: "Arrives", flight: "Flight",
      chores: "Chores", nothingToDo: "Nothing to do today", allDone: "All done", later: (n) => `${n} for later`,
      points: (n) => `${n} ${n === 1 ? "point" : "points"}`, thisWeek: "this week", missing: (k) => `No Family Board "${k}" sensor yet. Set up the Family Board integration first.`,
    },
    nb: {
      today: "I dag", tomorrow: "I morgen", yesterday: "I går", allDay: "Hele dagen", everyone: "Alle",
      nothingToday: "Ingenting i dag", nothingAhead: "Ingenting fremover", week: "Uka som kommer",
      birthdays: "Bursdager", noBirthdays: "Ingen bursdager ennå", turns: (n) => `fyller ${n}`, inDays: (n) => `om ${n} dager`,
      events: "Arrangementer", nothingOnBoard: "Ingenting på tavla", more: (n) => `+${n} til`,
      trip: "Neste reise", noTrips: "Ingen reiser planlagt", underWay: "Underveis", dayToGo: "dag igjen", daysToGo: "dager igjen",
      departs: "Avreise", arrives: "Ankomst", flight: "Fly",
      chores: "Husarbeid", nothingToDo: "Ingenting å gjøre i dag", allDone: "Alt ferdig", later: (n) => `${n} senere`,
      points: (n) => `${n} poeng`, thisWeek: "denne uka", missing: (k) => `Ingen Family Board-sensor "${k}" ennå. Sett opp Family Board-integrasjonen først.`,
    },
  };

  const CSS = `
    :host { display: block; }
    ha-card { padding: 4px 0 10px; }
    .head { display: flex; align-items: baseline; gap: 10px; padding: 12px 16px 6px; }
    .head .title { font-size: 1.15em; font-weight: 500; color: var(--primary-text-color); }
    .head .sub { font-size: 0.85em; color: var(--secondary-text-color); margin-left: auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .empty { padding: 10px 16px 6px; color: var(--secondary-text-color); }
    .day { padding: 12px 16px 2px; font-size: 0.78em; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
    .row { display: grid; grid-template-columns: 4.4em minmax(0, 1fr) auto; column-gap: 10px; align-items: center;
           padding: 7px 14px 7px 16px; border-top: 1px solid var(--divider-color, rgba(127,127,127,0.2)); }
    .row.first { border-top: none; }
    .when { font-size: 0.9em; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .what { min-width: 0; color: var(--primary-text-color); }
    .what .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .what .w { font-size: 0.8em; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dots { display: flex; gap: 3px; }
    .dot { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
           font-size: 0.68em; font-weight: 700; color: var(--primary-text-color); background: color-mix(in srgb, var(--c) 25%, transparent);
           border: 1.5px solid var(--c); }
    .avatar { width: 30px; height: 30px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
              font-size: 0.85em; font-weight: 700; color: var(--primary-text-color); background: color-mix(in srgb, var(--c) 25%, transparent);
              border: 2px solid var(--c); flex: 0 0 30px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px; font-size: 0.82em;
            background: var(--secondary-background-color, rgba(127,127,127,0.15)); color: var(--primary-text-color); }
    .allday { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 16px 8px; }
    .columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; padding: 4px 12px 6px; }
    .col { border: 1px solid var(--divider-color, rgba(127,127,127,0.2)); border-radius: 10px; padding: 8px; min-width: 0; }
    .col.house { background: var(--secondary-background-color, rgba(127,127,127,0.08)); }
    .col .ch { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--primary-text-color); margin-bottom: 6px; }
    .col .ch span.n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .col .none { font-size: 0.85em; color: var(--secondary-text-color); }
    .ev { border-left: 3px solid var(--c, var(--divider-color)); padding: 3px 0 3px 8px; margin: 4px 0; min-width: 0; }
    .ev .tm { font-size: 0.85em; font-weight: 600; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
    .ev .tt { font-size: 0.9em; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ev .wh { font-size: 0.78em; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .more { font-size: 0.8em; color: var(--secondary-text-color); padding: 2px 0; }
    .right { text-align: right; white-space: nowrap; }
    .right .big { font-weight: 600; color: var(--primary-text-color); }
    .right .small { font-size: 0.8em; color: var(--secondary-text-color); }
    .row.hot .right .big, .row.hot .what .t { color: var(--primary-color); }
    .trip { padding: 4px 16px 6px; }
    .trip .count { display: flex; align-items: baseline; gap: 10px; }
    .trip .num { font-size: 3em; font-weight: 700; line-height: 1; color: var(--primary-color); }
    .trip .unit { color: var(--secondary-text-color); }
    .trip .route { font-size: 1.05em; font-weight: 600; color: var(--primary-text-color); margin: 6px 0 2px; }
    .trip .line { display: flex; gap: 10px; align-items: baseline; margin: 3px 0; flex-wrap: wrap; }
    .trip .lbl { font-size: 0.78em; letter-spacing: 0.05em; text-transform: uppercase; color: var(--secondary-text-color); min-width: 4.6em; }
    .trip .clock { font-weight: 600; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
    .trip .zone { font-size: 0.82em; color: var(--secondary-text-color); margin-left: 4px; }
    .trip .date { font-size: 0.85em; color: var(--secondary-text-color); margin-left: auto; }
    .trip .meta { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
    .trip .countdown { font-variant-numeric: tabular-nums; font-size: 0.9em; color: var(--secondary-text-color); margin-top: 6px; }
    .person { padding: 10px 16px 2px; display: flex; align-items: center; gap: 10px; }
    .person .nm { font-weight: 600; color: var(--primary-text-color); }
    .person .pts { margin-left: auto; font-size: 0.85em; color: var(--secondary-text-color); white-space: nowrap; }
    button.chore { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; align-items: center; column-gap: 8px; width: 100%;
                   text-align: left; background: none; border: none; border-top: 1px solid var(--divider-color, rgba(127,127,127,0.2));
                   padding: 8px 14px 8px 16px; color: var(--primary-text-color); font: inherit; cursor: pointer; }
    button.chore.first { border-top: none; }
    button.chore .ti { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    button.chore .du { font-size: 0.78em; color: var(--secondary-text-color); }
    button.chore .du.late { color: var(--error-color, #db4437); }
    button.chore.done .ti, button.chore.pending .ti { text-decoration: line-through; color: var(--secondary-text-color); }
    button.chore ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
    button.chore.done ha-icon, button.chore.pending ha-icon { color: var(--success-color, #43a047); }
    .pt { font-size: 0.78em; color: var(--secondary-text-color); white-space: nowrap; }
    .stale { padding: 0 16px 4px; font-size: 0.75em; color: var(--warning-color, #e0a800); }
  `;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function lang(hass) {
    const l = ((hass && hass.locale && hass.locale.language) || navigator.language || "en").toLowerCase();
    return l.startsWith("nb") || l.startsWith("nn") || l.startsWith("no") ? "nb" : "en";
  }
  function tzOf(hass) {
    const loc = (hass && hass.locale) || {};
    if (loc.time_zone === "server" && hass.config && hass.config.time_zone) return hass.config.time_zone;
    return undefined;
  }
  function fmt(hass) {
    const loc = (hass && hass.locale) || {};
    const l = loc.language || navigator.language;
    const tz = tzOf(hass);
    const hour12 = loc.time_format === "12" ? true : loc.time_format === "24" ? false : undefined;
    return {
      time: new Intl.DateTimeFormat(l, { hour: "2-digit", minute: "2-digit", hour12, timeZone: tz }),
      dayKey: new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: tz }),
      long: new Intl.DateTimeFormat(l, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }),
      short: new Intl.DateTimeFormat(l, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }),
      weekday: new Intl.DateTimeFormat(l, { weekday: "long", timeZone: "UTC" }),
      date: new Intl.DateTimeFormat(l, { day: "numeric", month: "short", timeZone: "UTC" }),
    };
  }
  const noon = (iso) => new Date(iso + "T12:00:00Z");
  const daysBetween = (a, b) => Math.round((noon(b) - noon(a)) / DAY_MS);
  function dayLabel(iso, today, s, f) {
    if (!today) return f.short.format(noon(iso));
    const d = daysBetween(today, iso);
    if (d === 0) return s.today;
    if (d === 1) return s.tomorrow;
    if (d === -1) return s.yesterday;
    const name = d > 1 && d < 7 ? f.weekday.format(noon(iso)) : f.short.format(noon(iso));
    return name.charAt(0).toUpperCase() + name.slice(1);
  }
  function whenText(ev, s, f) {
    if (ev.all_day) return s.allDay;
    return f.time.format(new Date(ev.start));
  }
  function initials(p) {
    const n = (p.short || p.name || "?").trim();
    const parts = n.split(/\s+/).filter(Boolean);
    return parts.length > 1 ? (parts[0][0] + parts[1][0]).toUpperCase() : n.slice(0, 2);
  }
  function peopleOf(st) {
    const map = {};
    for (const p of (st.attributes.people || [])) map[p.id] = p;
    return map;
  }
  function dots(ids, people, max) {
    const list = (ids || []).map((id) => people[id]).filter(Boolean);
    if (!list.length) return "";
    const shown = list.slice(0, max || 4);
    return `<span class="dots">${shown.map((p) => `<span class="dot" style="--c:${esc(p.colour)}" title="${esc(p.name)}">${esc(initials(p))}</span>`).join("")}` +
      (list.length > shown.length ? `<span class="dot" style="--c:var(--divider-color)">+${list.length - shown.length}</span>` : "") + `</span>`;
  }
  function avatar(p) {
    return `<span class="avatar" style="--c:${esc(p.colour || "#888")}">${esc(initials(p))}</span>`;
  }
  function header(title, sub) {
    if (!title && !sub) return "";
    return `<div class="head">${title ? `<span class="title">${esc(title)}</span>` : ""}${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</div>`;
  }
  function findEntity(hass, kind) {
    const ids = Object.keys(hass.states).filter((id) => id.startsWith("sensor.") && hass.states[id].attributes && hass.states[id].attributes.family_board === kind);
    ids.sort();
    return ids[0];
  }
  function stale(st, s, f) {
    if (!st.attributes.stale || !st.attributes.updated) return "";
    return `<div class="stale">${esc(s.today)}: ${esc(f.time.format(new Date(st.attributes.updated)))}</div>`;
  }

  class FamilyCard extends HTMLElement {
    static get kind() { return ""; }
    static get defaults() { return {}; }
    static getStubConfig() { return {}; }
    setConfig(config) {
      this._config = Object.assign({}, this.constructor.defaults, config || {});
      this._sig = null;
      if (this._hass) this._render();
    }
    set hass(hass) {
      this._hass = hass;
      this._render();
    }
    getCardSize() { return 4; }
    _state() {
      const id = this._config.entity || findEntity(this._hass, this.constructor.kind);
      return id ? this._hass.states[id] : null;
    }
    _render() {
      if (!this._hass || !this._config) return;
      const st = this._state();
      const sig = (st ? st.entity_id + "@" + st.last_updated : "none") + "#" + Math.floor(Date.now() / 60000) + JSON.stringify(this._config) + (this._extraSig ? this._extraSig() : "");
      if (sig === this._sig) return;
      this._sig = sig;
      const s = STR[lang(this._hass)], f = fmt(this._hass);
      let body;
      if (!st) body = `<div class="empty">${esc(s.missing(this.constructor.kind))}</div>`;
      else body = this._body(st, s, f) + stale(st, s, f);
      this.innerHTML = `<style>${CSS}</style><ha-card>${body}</ha-card>`;
      if (this._after) this._after(st);
    }
  }

  /* ---- Today: one column per person, one for everyone ------------------------------------------------------------- */
  class FamilyTodayCard extends FamilyCard {
    static get kind() { return "today"; }
    static get defaults() { return { title: null, max_per_column: 6, show_household: true, show_location: true }; }
    _body(st, s, f) {
      const a = st.attributes, people = peopleOf(st);
      const title = this._config.title === null ? s.today : this._config.title;
      const sub = a.date ? f.long.format(noon(a.date)) : "";
      let html = header(title, sub);
      if (a.all_day && a.all_day.length) {
        html += `<div class="allday">${a.all_day.map((ev) => `<span class="chip">${esc(ev.summary)}${dots(ev.people, people, 3)}</span>`).join("")}</div>`;
      }
      const cols = (a.columns || []).map((c) => ({ person: people[c.person], events: c.events }));
      if (this._config.show_household) cols.push({ person: null, events: a.everyone || [] });
      html += `<div class="columns">` + cols.filter((c) => c.person || c.events.length || this._config.show_household).map((c) => {
        const colour = c.person ? c.person.colour : "var(--divider-color)";
        const head = c.person ? `${avatar(c.person)}<span class="n">${esc(c.person.short || c.person.name)}</span>`
                              : `<ha-icon icon="mdi:home-heart"></ha-icon><span class="n">${esc(s.everyone)}</span>`;
        const shown = c.events.slice(0, this._config.max_per_column);
        const rows = shown.map((ev) => `<div class="ev" style="--c:${esc(colour)}"><div class="tm">${esc(whenText(ev, s, f))}</div><div class="tt">${esc(ev.summary)}</div>` +
          (this._config.show_location && ev.location ? `<div class="wh">${esc(ev.location)}</div>` : "") + `</div>`).join("");
        const more = c.events.length > shown.length ? `<div class="more">${esc(s.more(c.events.length - shown.length))}</div>` : "";
        return `<div class="col${c.person ? "" : " house"}"><div class="ch">${head}</div>${rows || `<div class="none">${esc(s.nothingToday)}</div>`}${more}</div>`;
      }).join("") + `</div>`;
      return html;
    }
  }

  /* ---- The week ahead ----------------------------------------------------------------------------------------------- */
  class FamilyWeekCard extends FamilyCard {
    static get kind() { return "week"; }
    static get defaults() { return { title: null, max_items: 12, show_location: true }; }
    _body(st, s, f) {
      const a = st.attributes, people = peopleOf(st);
      const title = this._config.title === null ? s.week : this._config.title;
      let html = header(title, "");
      let budget = this._config.max_items, hidden = 0, any = false;
      for (const day of a.days || []) {
        if (budget <= 0) { hidden += day.events.length; continue; }
        const shown = day.events.slice(0, budget);
        budget -= shown.length; hidden += day.events.length - shown.length;
        any = true;
        html += `<div class="day">${esc(dayLabel(day.date, a.date, s, f))}</div>`;
        shown.forEach((ev, i) => {
          html += `<div class="row${i === 0 ? " first" : ""}"><span class="when">${esc(whenText(ev, s, f))}</span><span class="what"><span class="t">${esc(ev.summary)}</span>` +
            (this._config.show_location && ev.location ? `<span class="w">${esc(ev.location)}</span>` : "") + `</span>${dots(ev.people, people, 3)}</div>`;
        });
      }
      if (!any) html += `<div class="empty">${esc(s.nothingAhead)}</div>`;
      if (hidden > 0) html += `<div class="empty">${esc(s.more(hidden))}</div>`;
      return html;
    }
  }

  /* ---- Birthdays ---------------------------------------------------------------------------------------------------- */
  class FamilyBirthdaysCard extends FamilyCard {
    static get kind() { return "birthdays"; }
    static get defaults() { return { title: null, limit: 6, show_age: true }; }
    _body(st, s, f) {
      const a = st.attributes, people = peopleOf(st);
      const title = this._config.title === null ? s.birthdays : this._config.title;
      let html = header(title, "");
      const list = (a.upcoming || []).slice(0, this._config.limit);
      if (!list.length) return html + `<div class="empty">${esc(s.noBirthdays)}</div>`;
      list.forEach((b, i) => {
        const when = b.days === 0 ? s.today : b.days === 1 ? s.tomorrow : s.inDays(b.days);
        const p = b.person ? people[b.person] : null;
        const left = p ? avatar(p) : `<ha-icon icon="mdi:cake-variant"></ha-icon>`;
        html += `<div class="row${i === 0 ? " first" : ""}${b.days === 0 ? " hot" : ""}" style="grid-template-columns:34px minmax(0,1fr) auto">` +
          `<span>${left}</span><span class="what"><span class="t">${esc(b.name)}</span><span class="w">${esc(f.short.format(noon(b.date)))}</span></span>` +
          `<span class="right"><div class="big">${esc(when)}</div>${this._config.show_age && b.age ? `<div class="small">${esc(s.turns(b.age))}</div>` : ""}</span></div>`;
      });
      return html;
    }
  }

  /* ---- The Events board --------------------------------------------------------------------------------------------- */
  class FamilyEventsCard extends FamilyCard {
    static get kind() { return "events"; }
    static get defaults() { return { title: null, limit: 8, show_location: true }; }
    _body(st, s, f) {
      const a = st.attributes, people = peopleOf(st);
      const title = this._config.title === null ? s.events : this._config.title;
      let html = header(title, "");
      const list = (a.events || []).slice(0, this._config.limit);
      if (!list.length) return html + `<div class="empty">${esc(s.nothingOnBoard)}</div>`;
      let last = null;
      list.forEach((ev) => {
        if (ev.date !== last) { html += `<div class="day">${esc(dayLabel(ev.date, a.date, s, f))}</div>`; last = ev.date; }
        html += `<div class="row first"><span class="when">${esc(whenText(ev, s, f))}</span><span class="what"><span class="t">${esc(ev.summary)}</span>` +
          (this._config.show_location && ev.location ? `<span class="w">${esc(ev.location)}</span>` : "") + `</span>` +
          `<span class="right"><div class="small">${esc(ev.days === 0 ? s.today : ev.days === 1 ? s.tomorrow : s.inDays(ev.days))}</div></span></div>`;
      });
      if ((a.events || []).length > list.length) html += `<div class="empty">${esc(s.more(a.events.length - list.length))}</div>`;
      return html;
    }
  }

  /* ---- The next trip ------------------------------------------------------------------------------------------------ */
  const MODE_ICON = { flight: "mdi:airplane-takeoff", ferry: "mdi:ferry", train: "mdi:train", car: "mdi:car", other: "mdi:bag-suitcase" };
  function countdownText(ms) {
    if (ms <= 0) return "";
    const t = Math.floor(ms / 1000), d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return (d > 0 ? `${d}d ` : "") + `${pad(h)}:${pad(m)}:${pad(sec)}`;
  }
  class FamilyTripCard extends FamilyCard {
    static get kind() { return "trip"; }
    static get defaults() { return { title: null, show_countdown: true, show_all: false, show_people: true }; }
    connectedCallback() { this._timer = setInterval(() => this._tick(), 1000); }
    disconnectedCallback() { if (this._timer) clearInterval(this._timer); }
    _tick() {
      const el = this.querySelector(".countdown");
      if (el && this._target) el.textContent = countdownText(this._target - Date.now());
    }
    _clocks(c, homes, s, f) {
      if (!c) return "";
      const names = homes.map((h) => h.name);
      if (!c.differs) return `<span class="clock">${esc(c.a)}</span>`;
      return `<span class="clock">${esc(c.a)}</span><span class="zone">${esc(names[0] || "")}</span>` +
             `<span class="clock" style="margin-left:10px">${esc(c.b)}</span><span class="zone">${esc(names[1] || "")}</span>`;
    }
    _body(st, s, f) {
      const a = st.attributes, people = peopleOf(st), homes = a.homes || [];
      const t = a.trip;
      const title = this._config.title === null ? s.trip : this._config.title;
      if (!t) { this._target = null; return header(title, "") + `<div class="empty">${esc(s.noTrips)}</div>`; }
      this._target = t.under_way ? (t.arrive ? Date.parse(t.arrive) : null) : Date.parse(t.depart);
      let html = header(title, "");
      html += `<div class="trip">`;
      html += `<div class="route"><ha-icon icon="${MODE_ICON[t.mode] || MODE_ICON.other}"></ha-icon> ${esc(t.title)}</div>`;
      if (t.under_way) html += `<div class="count"><span class="num" style="font-size:2em">${esc(s.underWay)}</span></div>`;
      else if (t.days <= 0) html += `<div class="count"><span class="num" style="font-size:2em">${esc(s.today)}</span></div>`;
      else html += `<div class="count"><span class="num">${t.days}</span><span class="unit">${esc(t.days === 1 ? s.dayToGo : s.daysToGo)}</span></div>`;
      if (t.from || t.to) html += `<div class="route" style="font-weight:500">${esc(t.from || "")}${t.from && t.to ? " → " : ""}${esc(t.to || "")}</div>`;
      html += `<div class="line"><span class="lbl">${esc(s.departs)}</span>${this._clocks(t.depart_clocks, homes, s, f)}<span class="date">${esc(f.short.format(noon(t.date)))}</span></div>`;
      if (t.arrive_clocks) {
        const arriveDay = t.arrive_clocks.a_date || t.date;
        html += `<div class="line"><span class="lbl">${esc(s.arrives)}</span>${this._clocks(t.arrive_clocks, homes, s, f)}` +
                (arriveDay !== t.date ? `<span class="date">${esc(f.short.format(noon(arriveDay)))}</span>` : "") + `</div>`;
      }
      const chips = (t.flights || []).map((c) => `<span class="chip"><ha-icon icon="mdi:airplane" style="--mdc-icon-size:16px"></ha-icon>${esc(c)}</span>`).join("");
      const who = this._config.show_people ? dots(t.people, people, 5) : "";
      if (chips || who) html += `<div class="meta">${chips}${who}</div>`;
      if (this._config.show_countdown && this._target) html += `<div class="countdown">${esc(countdownText(this._target - Date.now()))}</div>`;
      html += `</div>`;
      if (this._config.show_all && (a.trips || []).length > 1) {
        a.trips.slice(1).forEach((o, i) => {
          html += `<div class="row${i === 0 ? " first" : ""}"><span class="when">${esc(f.date.format(noon(o.date)))}</span><span class="what"><span class="t">${esc(o.title)}</span>` +
            (o.to ? `<span class="w">${esc(o.from ? o.from + " → " : "")}${esc(o.to)}</span>` : "") + `</span><span class="right"><div class="small">${esc(s.inDays(o.days))}</div></span></div>`;
        });
      }
      return html;
    }
  }

  /* ---- Chores: everyone's lists, ticked here ---------------------------------------------------------------------- */
  class FamilyChoresCard extends FamilyCard {
    static get kind() { return "chores"; }
    static get defaults() { return { title: null, entities: null, show_done: true, show_points: true, show_later: true }; }
    constructor() {
      super();
      this._pending = new Set();
      this.addEventListener("click", (e) => {
        const b = e.target.closest && e.target.closest("button.chore");
        if (!b || b.classList.contains("done") || !this._hass) return;
        const uid = b.dataset.uid, entity = b.dataset.entity;
        if (!uid || !entity) return;
        this._pending.add(uid);
        b.classList.add("pending");
        const icon = b.querySelector("ha-icon");
        if (icon) icon.setAttribute("icon", "mdi:checkbox-marked");
        this._hass.callService("todo", "update_item", { entity_id: entity, item: uid, status: "completed" }).catch(() => {
          this._pending.delete(uid);
          b.classList.remove("pending");
          if (icon) icon.setAttribute("icon", "mdi:checkbox-blank-outline");
        });
      });
    }
    _states() {
      const states = this._hass.states;
      let ids = Array.isArray(this._config.entities) ? this._config.entities.filter((id) => states[id])
        : Object.keys(states).filter((id) => id.startsWith("sensor.") && states[id].attributes && states[id].attributes.family_board === "chores");
      const order = [];
      for (const id of ids) {
        const people = (states[id].attributes.people || []).map((p) => p.id);
        const me = states[id].attributes.person && states[id].attributes.person.id;
        order.push([people.indexOf(me), id]);
      }
      order.sort((x, y) => x[0] - y[0] || (x[1] < y[1] ? -1 : 1));
      return order.map((o) => states[o[1]]);
    }
    _extraSig() { return this._states().map((st) => st.entity_id + "@" + st.last_updated).join("|"); }
    _state() { return this._states()[0] || null; }
    _body(first, s, f) {
      const title = this._config.title === null ? s.chores : this._config.title;
      let html = header(title, "");
      for (const st of this._states()) {
        const a = st.attributes, p = a.person || { name: st.entity_id, colour: "#888" };
        const open = a.open || [], done = a.done_today || [];
        for (const c of open) if (this._pending.has(c.uid) && !open.some((o) => o.uid === c.uid && false)) { /* keep */ }
        for (const uid of [...this._pending]) if (!open.some((c) => c.uid === uid)) this._pending.delete(uid);
        html += `<div class="person">${avatar(p)}<span class="nm">${esc(p.name)}</span>` +
          (this._config.show_points ? `<span class="pts">${esc(s.points(a.points_week || 0))} ${esc(s.thisWeek)}</span>` : "") + `</div>`;
        if (!open.length && !done.length) { html += `<div class="empty">${esc(s.nothingToDo)}</div>`; continue; }
        open.forEach((c, i) => {
          const pend = this._pending.has(c.uid);
          html += `<button class="chore${i === 0 ? " first" : ""}${pend ? " pending" : ""}" data-uid="${esc(c.uid)}" data-entity="${esc(a.todo_entity || "")}">` +
            `<ha-icon icon="${pend ? "mdi:checkbox-marked" : "mdi:checkbox-blank-outline"}"></ha-icon><span><span class="ti">${esc(c.title)}</span>` +
            (c.due ? `<div class="du${c.overdue ? " late" : ""}">${esc(dayLabel(c.due, a.date, s, f))}</div>` : "") + `</span>` +
            (this._config.show_points ? `<span class="pt">${esc(s.points(c.points))}</span>` : "<span></span>") + `</button>`;
        });
        if (!open.length) html += `<div class="empty">${esc(s.allDone)}</div>`;
        if (this._config.show_done) done.forEach((c, i) => {
          html += `<button class="chore done${!open.length && i === 0 ? " first" : ""}" disabled><ha-icon icon="mdi:checkbox-marked"></ha-icon><span class="ti">${esc(c.title)}</span>` +
            (this._config.show_points ? `<span class="pt">${esc(s.points(c.points))}</span>` : "<span></span>") + `</button>`;
        });
        if (this._config.show_later && (a.later || []).length) html += `<div class="empty" style="font-size:0.85em">${esc(s.later(a.later.length))}</div>`;
      }
      return html;
    }
  }

  const CARDS = [
    ["family-today-card", FamilyTodayCard, "Family Board: Today", "Today, one column per person and one for everyone."],
    ["family-week-card", FamilyWeekCard, "Family Board: Week ahead", "The days ahead, grouped by day, with who each event is for."],
    ["family-birthdays-card", FamilyBirthdaysCard, "Family Board: Birthdays", "Whose birthday is next, in how many days, and the age they turn."],
    ["family-events-card", FamilyEventsCard, "Family Board: Events", "The Events board: what the family has tickets for."],
    ["family-trip-card", FamilyTripCard, "Family Board: Next trip", "The next journey, counting down, with departure on both homes' clocks."],
    ["family-chores-card", FamilyChoresCard, "Family Board: Chores", "Everyone's chores today, ticked here, with points this week."],
  ];
  window.customCards = window.customCards || [];
  for (const [tag, cls, name, description] of CARDS) {
    if (!customElements.get(tag)) customElements.define(tag, cls);
    if (!window.customCards.some((c) => c.type === tag)) window.customCards.push({ type: tag, name, description, preview: true });
  }
})();
