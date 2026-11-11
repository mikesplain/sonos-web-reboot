"""Constants for Sonos Web Reboot."""

DOMAIN = "sonos_web_reboot"
CONF_HOUSEHOLD = "household_id"
CONF_PLAYERS = "players"
CONF_SESSION_COOKIE = "session_cookie"

ORIGIN = "https://play.sonos.com"
BASE_URL = f"{ORIGIN}/api/control"
REQUEST_TIMEOUT = 20
RESTART_COOLDOWN = 120
