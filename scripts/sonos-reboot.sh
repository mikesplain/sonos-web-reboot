#!/bin/sh
set -eu

usage() {
    printf 'Usage: %s check|reboot PLAYER_ID COOKIE_FILE\n' "$0" >&2
    printf 'PLAYER_ID is the Sonos player id (RINCON_...) from the Sonos Web player list.\n' >&2
    printf 'Pass - as COOKIE_FILE to read the cookie value from stdin.\n' >&2
}

if [ "$#" -ne 3 ]; then
    usage
    exit 2
fi

action=$1
player_id=$2
cookie_file=$3
base_url=https://play.sonos.com/api/control

case "$player_id" in
    RINCON_[0-9A-F]*) ;;
    *)
        printf 'PLAYER_ID must look like RINCON_... from the Sonos Web player list.\n' >&2
        exit 2
        ;;
esac

case "$action" in
    check)
        url=$base_url/households
        set --
        ;;
    reboot)
        url=$base_url/players/$player_id/management/reboot
        set -- --data '{}'
        ;;
    *)
        usage
        exit 2
        ;;
esac

session_cookie=''
if [ "$cookie_file" = '-' ]; then
    IFS= read -r session_cookie || :
elif [ -f "$cookie_file" ] && [ -r "$cookie_file" ]; then
    IFS= read -r session_cookie < "$cookie_file" || :
else
    printf 'Cookie file is missing or unreadable.\n' >&2
    exit 2
fi

case "$session_cookie" in
    *"$(printf '\r')"*|[Cc][Oo][Oo][Kk][Ii][Ee]:*)
        printf 'Use the one-line Cookie header value, without the Cookie: label.\n' >&2
        exit 2
        ;;
    *=*) ;;
    *)
        printf 'A Sonos Web Cookie header value is required.\n' >&2
        exit 2
        ;;
esac

# Read the header from stdin so the session cookie stays out of the curl arguments.
if ! status=$(printf 'Cookie: %s\n' "$session_cookie" | curl --disable \
    --silent --show-error --max-time 25 --header @- \
    --header 'Content-Type: application/json' \
    --output /dev/null --write-out '%{http_code}' "$@" "$url"); then
    printf 'The Sonos request did not return a complete response.\n' >&2
    exit 1
fi

case "$status" in
    2??)
        if [ "$action" = check ]; then
            printf 'Sonos Web accepted the session (HTTP %s).\n' "$status"
        else
            printf 'Sonos accepted the reboot request for %s (HTTP %s).\n' "$player_id" "$status"
            printf 'Confirm the player disconnects and returns online.\n' >&2
        fi
        ;;
    401|3??)
        printf 'Sonos Web session is missing or expired (HTTP %s). Refresh the cookie and try again.\n' "$status" >&2
        exit 3
        ;;
    403)
        printf 'Sonos denied the request (HTTP 403). Check the session and its permissions.\n' >&2
        exit 4
        ;;
    *)
        printf 'Sonos returned HTTP %s.\n' "$status" >&2
        exit 1
        ;;
esac
