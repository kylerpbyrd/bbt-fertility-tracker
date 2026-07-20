#!/usr/bin/with-contenv bashio

# Ensure Python can find the app modules
export PYTHONPATH="/app:${PYTHONPATH:-}"
export PATH="/opt/venv/bin:${PATH}"
export DATA_PATH="/data"

# Read add-on configuration via bashio
TEMP_UNIT=$(bashio::config 'temp_unit' 'F')
HA_SENSOR_ENTITY=$(bashio::config 'ha_sensor_entity' '')
POLL_INTERVAL=$(bashio::config 'poll_interval_minutes' '15')

export BBT_TEMP_UNIT="${TEMP_UNIT}"
export BBT_HA_SENSOR_ENTITY="${HA_SENSOR_ENTITY}"
export BBT_POLL_INTERVAL="${POLL_INTERVAL}"

bashio::log.info "Starting BBT Fertility Tracker v1.0.4"
bashio::log.info "  Temperature unit : ${TEMP_UNIT}"
bashio::log.info "  Poll interval    : ${POLL_INTERVAL} min"
if [ -n "${HA_SENSOR_ENTITY}" ]; then
    bashio::log.info "  HA sensor entity : ${HA_SENSOR_ENTITY}"
fi

exec python3 /app/app.py
