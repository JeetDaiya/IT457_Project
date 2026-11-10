#!/usr/bin/env bash
# Readable run folder name, shared by run_http.sh, run_mqtt.sh, measure_run.sh and restart_test.sh (source this file).
#   <date>_<stage>_<kind>_<rate>per-s_run<repeat>      e.g. 2026-11-10_A_mqtt-100conn_100per-s_run1
#   stage: STAGE_NAME if set, else the stage argument (a single letter is upper-cased: a -> A)
#   kind:  http, or mqtt-<CONNECTIONS>conn with -<RUN_NOTE> appended when set (e.g. mqtt-100conn-restart)
# The stage argument itself still goes into the database run tag (device_id prefix), so it must differ between runs
# that would otherwise share a tag; STAGE_NAME only changes the folder name.
run_suffix() {  # <stage> <http|mqtt> <rate> <repeat>
    local stage=${STAGE_NAME:-$1} proto=$2 rate=$3 repeat=$4 kind=$2
    case $stage in [a-z]) stage=${stage^^} ;; esac
    if [ "$proto" = mqtt ]; then kind="mqtt-${CONNECTIONS:-1}conn${RUN_NOTE:+-$RUN_NOTE}"; fi
    echo "${stage}_${kind}_${rate}per-s_run${repeat}"
}
