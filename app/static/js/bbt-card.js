/**
 * bbt-card.js — BBT Fertility Tracker custom Lovelace card
 *
 * Auto-installed to /config/www/bbt-card.js by the add-on on startup.
 *
 * Add as a Lovelace resource:
 *   URL:  /local/bbt-card.js
 *   Type: JavaScript module
 *
 * Card YAML:
 *   type: custom:bbt-fertility-card
 *   profile_slug: default        # slug of the profile to display
 *   title: BBT Fertility Tracker  # optional card title
 *   show_open_button: true        # optional, default true
 */

const PHASE_COLORS = {
  menstruation:  '#ef5350',
  pre_ovulatory: '#42a5f5',
  fertile:       '#66bb6a',
  ovulation:     '#ff9800',
  luteal:        '#ab47bc',
  unknown:       '#9e9e9e',
};

const PHASE_LABELS = {
  menstruation:  'Menstruation',
  pre_ovulatory: 'Pre-Ovulatory',
  fertile:       'Fertile Window',
  ovulation:     'Ovulation',
  luteal:        'Luteal Phase',
  unknown:       'Unknown',
};


class BBTFertilityCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  setConfig(config) {
    this._config = {
      title: 'BBT Fertility Tracker',
      profile_slug: 'default',
      show_open_button: true,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _state(entityId) {
    return this._hass?.states[entityId]?.state ?? null;
  }

  _attr(entityId, attr) {
    return this._hass?.states[entityId]?.attributes?.[attr] ?? null;
  }

  _render() {
    if (!this._config || !this._hass) return;

    const slug  = this._config.profile_slug;
    const pfx   = `bbt_${slug}`;

    const cycleDay    = this._state(`sensor.${pfx}_cycle_day`);
    const phase       = this._state(`sensor.${pfx}_cycle_phase`) || 'unknown';
    const lastTemp    = this._state(`sensor.${pfx}_last_temp`);
    const fertile     = this._state(`binary_sensor.${pfx}_fertile_window`);
    const ovConf      = this._state(`binary_sensor.${pfx}_ovulation_confirmed`);
    const ovDate      = this._state(`sensor.${pfx}_ovulation_date`);
    const nextPeriod  = this._state(`sensor.${pfx}_next_period_date`);
    const lutealLen   = this._state(`sensor.${pfx}_luteal_length`);
    const avgCycle    = this._state(`sensor.${pfx}_avg_cycle_length`);
    const unit        = this._attr(`sensor.${pfx}_last_temp`, 'unit_of_measurement') || '°';

    const phaseColor = PHASE_COLORS[phase] ?? PHASE_COLORS.unknown;
    const phaseLabel = PHASE_LABELS[phase] ?? phase.replace(/_/g, ' ');
    const isFertile  = fertile === 'on';
    const isOvConf   = ovConf === 'on';
    const noData     = !cycleDay || cycleDay === 'unknown';

    const tempDisplay = (lastTemp && lastTemp !== 'unknown')
      ? `${parseFloat(lastTemp).toFixed(2)}${unit}`
      : '—';

    const nextDisplay = (nextPeriod && nextPeriod !== 'unknown' && nextPeriod !== 'none')
      ? nextPeriod.slice(5)
      : '—';

    const ovDisplay = (() => {
      if (isOvConf) {
        const d = (ovDate && ovDate !== 'none') ? ' ' + ovDate.slice(5) : '';
        return `<span class="ov-confirmed">✓ Confirmed${d}</span>`;
      }
      if (ovDate && ovDate !== 'none' && ovDate !== 'unknown') {
        return `Est. ${ovDate.slice(5)}`;
      }
      return 'Not yet detected';
    })();

    const lutealDisplay = (isOvConf && lutealLen && lutealLen !== 'unknown')
      ? ` · ${lutealLen}d luteal` : '';

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --primary:      #9c27b0;
          --primary-dark: #6a0080;
          font-family: var(--paper-font-body1_-_font-family, 'Segoe UI', sans-serif);
          font-size: 14px;
        }
        ha-card { overflow: hidden; }

        .card-header {
          padding: 10px 16px 4px;
          font-size: 13px;
          font-weight: 600;
          color: var(--primary-dark);
          letter-spacing: .3px;
        }

        /* ── Phase banner ─────────────────── */
        .phase-banner {
          background: ${phaseColor};
          color: #fff;
          padding: 12px 16px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }
        .phase-name { font-size: 17px; font-weight: 700; }
        .phase-sub  { font-size: 11px; opacity: .8; margin-top: 2px; }
        .cycle-day-box { text-align: right; }
        .cycle-day-label { font-size: 10px; opacity: .8; text-transform: uppercase; letter-spacing: .4px; }
        .cycle-day-num   { font-size: 30px; font-weight: 700; line-height: 1; }

        /* ── Stats row ────────────────────── */
        .stats {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 1px;
          background: var(--divider-color, #e0e0e0);
          border-top: 1px solid var(--divider-color, #e0e0e0);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .stat {
          background: var(--card-background-color, #fff);
          padding: 10px 6px;
          text-align: center;
        }
        .stat-val {
          font-size: 17px;
          font-weight: 700;
          color: var(--primary-text-color, #212121);
          white-space: nowrap;
        }
        .stat-val.small { font-size: 13px; }
        .stat-val.fertile-on  { color: #388e3c; font-size: 13px; }
        .stat-val.fertile-off { color: var(--secondary-text-color, #9e9e9e); font-size: 13px; }
        .stat-lbl {
          font-size: 9px;
          color: var(--secondary-text-color, #757575);
          text-transform: uppercase;
          letter-spacing: .5px;
          margin-top: 2px;
        }

        /* ── Footer ───────────────────────── */
        .footer {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 9px 14px;
          background: var(--card-background-color, #fff);
        }
        .ov-info        { font-size: 12px; color: var(--secondary-text-color, #757575); }
        .ov-confirmed   { color: #388e3c; font-weight: 600; }

        /* ── Open button ──────────────────── */
        .open-btn {
          background: var(--primary, #9c27b0);
          color: #fff;
          border: none;
          border-radius: 6px;
          padding: 7px 14px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          letter-spacing: .3px;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .open-btn:hover { filter: brightness(1.1); }

        /* ── No-data state ────────────────── */
        .no-data {
          padding: 22px 16px;
          text-align: center;
          color: var(--secondary-text-color, #757575);
          font-size: 13px;
          line-height: 1.6;
        }
      </style>

      <ha-card>
        <div class="card-header">${this._config.title}</div>

        ${noData ? `
          <div class="no-data">
            🌡️ No data yet.<br>
            Start logging temperatures in the tracker.
            ${this._config.show_open_button
              ? `<br><br><button class="open-btn" id="openBtn">Open Tracker</button>`
              : ''}
          </div>
        ` : `
          <div class="phase-banner">
            <div>
              <div class="phase-name">${phaseLabel}</div>
              ${avgCycle && avgCycle !== 'unknown'
                ? `<div class="phase-sub">~${avgCycle} day avg cycle</div>`
                : ''}
            </div>
            <div class="cycle-day-box">
              <div class="cycle-day-label">Cycle Day</div>
              <div class="cycle-day-num">${cycleDay}</div>
            </div>
          </div>

          <div class="stats">
            <div class="stat">
              <div class="stat-val">${tempDisplay}</div>
              <div class="stat-lbl">Last Temp</div>
            </div>
            <div class="stat">
              <div class="stat-val ${isFertile ? 'fertile-on' : 'fertile-off'}">
                ${isFertile ? '✓ Fertile' : 'Not Fertile'}
              </div>
              <div class="stat-lbl">Window</div>
            </div>
            <div class="stat">
              <div class="stat-val small">${nextDisplay}</div>
              <div class="stat-lbl">Next Period</div>
            </div>
          </div>

          <div class="footer">
            <div class="ov-info">
              ${ovDisplay}${lutealDisplay}
            </div>
            ${this._config.show_open_button
              ? `<button class="open-btn" id="openBtn">Open Tracker</button>`
              : ''}
          </div>
        `}
      </ha-card>
    `;

    const btn = this.shadowRoot.getElementById('openBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        const e = new CustomEvent('hass-action', {
          bubbles: true,
          composed: true,
          detail: {
            config: {
              tap_action: {
                action: 'navigate',
                navigation_path: '/hassio/ingress/bbt_fertility_tracker',
              },
            },
            action: 'tap',
          },
        });
        this.dispatchEvent(e);
      });
    }
  }

  getCardSize() { return 3; }

  static getStubConfig() {
    return {
      type: 'custom:bbt-fertility-card',
      profile_slug: 'default',
      title: 'BBT Fertility Tracker',
    };
  }
}

customElements.define('bbt-fertility-card', BBTFertilityCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        'bbt-fertility-card',
  name:        'BBT Fertility Card',
  description: 'Shows cycle phase, day, last temperature, fertile window, ovulation status, and next period estimate.',
  preview:     false,
});
