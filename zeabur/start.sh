#!/usr/bin/env bash
set -u

: "${PORT:?Zeabur must provide PORT}"

mkdir -p "${OMBRE_BUCKETS_DIR:-/data/buckets}" "${OMBRE_STATE_DIR:-/data/state}"
envsubst '${PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

nginx -t -c /etc/nginx/nginx.conf

python server.py &
brain_pid=$!
python gateway.py &
gateway_pid=$!
nginx -c /etc/nginx/nginx.conf -g 'daemon off;' &
nginx_pid=$!

shutdown() {
    trap - INT TERM EXIT
    kill -TERM "$brain_pid" "$gateway_pid" "$nginx_pid" 2>/dev/null || true
    wait "$brain_pid" "$gateway_pid" "$nginx_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

set +e
wait -n "$brain_pid" "$gateway_pid" "$nginx_pid"
status=$?
set -e
shutdown
exit "$status"
