# User Mood (XenForo 2.2 / 2.3)

Members pick a mood from 16 emoji icons under Account > Account details.
It shows as a pill under their name on their profile page.

## Install
1. ACP > Add-ons > Install/upgrade from archive > upload UserMood-1.0.0.zip
   (or copy upload/src/addons/UserMood to your server and run
   `php cmd.php xf-addon:install UserMood`)
2. Done. Uninstalling removes the database column.

## Customize
- Moods: edit src/addons/UserMood/Moods.php (add/remove/reorder).
- Styling: the CSS lives in the `usermood_macros` template.
- If a template modification shows 0 matches in ACP > Appearance >
  Template modifications, your style has altered that template — adjust
  the "find" pattern there.
