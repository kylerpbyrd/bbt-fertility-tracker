# BBT Fertility Tracker — Home Assistant Add-On

> Track basal body temperature (BBT) to monitor menstrual cycles, detect ovulation, and identify fertile windows — directly inside Home Assistant.

![Version](https://img.shields.io/badge/version-1.0.0-purple)
![HA Ingress](https://img.shields.io/badge/HA-Ingress-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Sympto-thermal method** — coverline + 3-day shift rule, conservative variant, and witch's hat exception
- **Fertile window calculation** — calendar rule (shortest cycle − 18 days) with cervical mucus override
- **Full BBT chart** — Chart.js with coverline annotation, fertile window box, ovulation line, discarded reading indicators, mucus/OPK dots
- **Multiple profiles** — track multiple people in one add-on
- **Home Assistant integration**
  - Auto-polls any HA sensor entity for temperature readings
  - Publishes 9 entities per profile (`sensor.*`, `binary_sensor.*`) for use in dashboards and automations
- **°F / °C** — configurable per profile
- **Logs**: temperature, cervical mucus, menstrual flow, OPK result, cervical position, symptoms, notes

---

## Installation

### Add as a Custom Repository

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**
2. Click the **⋮ menu → Repositories**
3. Add: `https://github.com/kylerpbyrd/bbt-fertility-tracker`
4. Find **BBT Fertility Tracker** in the store and click **Install**

### Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `temp_unit` | `F` | Temperature unit — `F` or `C` |
| `ha_sensor_entity` | _(empty)_ | Optional HA sensor entity ID to poll for automatic temp import (e.g. `sensor.bedroom_thermometer`) |
| `poll_interval_minutes` | `15` | How often (in minutes) to poll the HA sensor |

---

## Home Assistant Entities

For each profile with slug `<slug>`, the following entities are published:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.bbt_<slug>_cycle_day` | Sensor | Current cycle day number |
| `sensor.bbt_<slug>_cycle_phase` | Sensor | Current phase (`menstruation`, `fertile`, `luteal`, etc.) |
| `sensor.bbt_<slug>_last_temp` | Sensor | Most recent BBT reading |
| `binary_sensor.bbt_<slug>_fertile_window` | Binary Sensor | `on` during estimated fertile window |
| `binary_sensor.bbt_<slug>_ovulation_confirmed` | Binary Sensor | `on` when ovulation is confirmed by temperature shift |
| `sensor.bbt_<slug>_ovulation_date` | Sensor | Date ovulation was detected |
| `sensor.bbt_<slug>_next_period_date` | Sensor | Predicted next period start date |
| `sensor.bbt_<slug>_luteal_length` | Sensor | Luteal phase length in days |
| `sensor.bbt_<slug>_avg_cycle_length` | Sensor | Rolling average cycle length (last 6 cycles) |

---

## Algorithm Details

### Coverline
Calculated as the highest of the 6 pre-shift temperatures + 0.1 °F (0.05 °C threshold in Celsius mode).

### Ovulation Detection (3-Day Shift Rule)
Ovulation is confirmed when **3 consecutive temperatures** all rise above the coverline. The standard method requires all three above; the conservative method additionally requires the 3rd day to be ≥ 0.2 °F (0.1 °C) above coverline. A **witch's hat exception** allows confirmation even when day 2 dips, provided days 1, 3, and 4 are all above coverline.

### Fertile Window
- **Start**: earlier of (a) calendar rule: `shortest_past_cycle − 18` and (b) first day of fertile-quality cervical mucus (`watery` or `egg_white`)
- **End (post-ovulatory infertile)**: 3 days after the temperature shift start (confirmed) or 3 days after estimated ovulation date (possible)

### Pregnancy Indicator
≥ 18 consecutive elevated post-ovulatory temperatures triggers a pregnancy indicator flag.

### Short Luteal Phase Warning
Luteal phases under 10 days trigger a warning (may affect implantation).

---

## Development

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r app/requirements.txt

# Run locally (without HA)
DATA_PATH=./data BBT_TEMP_UNIT=F python3 app/app.py
```

---

## Privacy

All data is stored locally in `/data/bbt.db` on your Home Assistant instance. Nothing is sent externally.

---

## License

MIT — see [LICENSE](LICENSE)
