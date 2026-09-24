<?php

namespace Uvopia\Leaderboards\Alert;

use XF\Alert\AbstractHandler;

class Leaderboard extends AbstractHandler
{
    public function getOptOutActions()
    {
        return ['top', 'near'];
    }

    public function getOptOutDisplayOrder()
    {
        return 90000;
    }
}
