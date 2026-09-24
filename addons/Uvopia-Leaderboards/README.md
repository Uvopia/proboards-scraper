# Leaderboards for XenForo 2.2 / 2.3

Community leaderboards that rank members by activity, with period filters,
position changes, top-3 trophies, "find own position", widgets and alerts.

## Install
1. Upload the contents of `upload/` to your forum root (so files land in `src/addons/Uvopia/Leaderboards`).
2. ACP → Add-ons → find **Leaderboards** under "Installable add-ons" → Install.
   (Or use "Install/upgrade from archive" with this zip.)
3. Four starter leaderboards are created: messages, reactions, thread starters, achievements.

## Where things are
- Public page: `/leaderboards/` (also a "Leaderboards" link under the Members tab)
- ACP: Users → Leaderboards (direct URL: `admin.php?leaderboards/`)
- Widgets: ACP → Appearance → Widgets → Add widget → "Leaderboard". Pick any widget position
  (forum list sidebar, thread view, member view, What's new, etc.).
- Alerts: cron "Leaderboards: send position alerts" runs hourly. Members can turn the two
  alert types off in Account → Preferences.

## Criteria
Messages, threads started, reaction score, trophy points (achievements),
resources (needs XFRM), media (needs XFMG).

## Notes
- Viewing uses the existing "View member list" permission.
- Periods are calendar-based in the board's default time zone (weeks start Monday).
- Position change arrows compare against a snapshot about 24 hours old, and reset
  when a new period starts.
- Rankings are cached per leaderboard/period for the configured number of minutes.
- Donations aren't included since XenForo has no core donations system.
