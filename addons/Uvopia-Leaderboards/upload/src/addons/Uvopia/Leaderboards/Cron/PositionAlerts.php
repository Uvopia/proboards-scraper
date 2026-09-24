<?php

namespace Uvopia\Leaderboards\Cron;

use Uvopia\Leaderboards\Repository\LeaderboardRepository;

class PositionAlerts
{
    public static function run()
    {
        /** @var LeaderboardRepository $repo */
        $repo = \XF::repository(LeaderboardRepository::class);
        $repo->sendPositionAlerts();
    }
}
