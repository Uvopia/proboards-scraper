<?php

namespace Uvopia\Leaderboards\Pub\Controller;

use Uvopia\Leaderboards\Entity\Leaderboard;
use Uvopia\Leaderboards\Repository\LeaderboardRepository;
use XF\Mvc\ParameterBag;
use XF\Pub\Controller\AbstractController;

class LeaderboardController extends AbstractController
{
    public function actionIndex(ParameterBag $params)
    {
        $this->assertCanViewLeaderboards();

        $repo = $this->getLeaderboardRepo();
        $leaderboards = $repo->getViewableLeaderboards();

        if (!$leaderboards->count())
        {
            return $this->view('Uvopia\Leaderboards:Leaderboard\Index', 'uvopia_leaderboard_view', [
                'leaderboards' => $leaderboards,
                'leaderboard' => null,
            ]);
        }

        if ($params->leaderboard_id)
        {
            $leaderboard = $leaderboards[$params->leaderboard_id] ?? null;
            if (!$leaderboard)
            {
                return $this->notFound(\XF::phrase('uvopia_leaderboards_requested_leaderboard_not_found'));
            }
        }
        else
        {
            $leaderboard = $leaderboards->first();
        }

        $period = $this->getRequestedPeriod($leaderboard);
        $results = $repo->getResults($leaderboard, $period);
        $entries = $repo->attachUsers($results['entries']);

        $visitorId = \XF::visitor()->user_id;
        $selfEntry = null;
        if ($visitorId)
        {
            foreach ($entries AS $entry)
            {
                if ($entry['user_id'] == $visitorId)
                {
                    $selfEntry = $entry;
                    break;
                }
            }
        }

        return $this->view('Uvopia\Leaderboards:Leaderboard\View', 'uvopia_leaderboard_view', [
            'leaderboards' => $leaderboards,
            'leaderboard' => $leaderboard,
            'period' => $period,
            'entries' => $entries,
            'generated' => $results['generated_date'],
            'selfEntry' => $selfEntry,
        ]);
    }

    public function actionPosition(ParameterBag $params)
    {
        $this->assertCanViewLeaderboards();

        $visitor = \XF::visitor();
        if (!$visitor->user_id)
        {
            return $this->noPermission();
        }

        $leaderboard = $this->assertViewableLeaderboard($params->leaderboard_id);
        $period = $this->getRequestedPeriod($leaderboard);
        $result = $this->getLeaderboardRepo()->getUserPosition($leaderboard, $period, $visitor->user_id);

        return $this->view('Uvopia\Leaderboards:Leaderboard\Position', 'uvopia_leaderboard_position', [
            'leaderboard' => $leaderboard,
            'period' => $period,
            'position' => $result['position'],
            'value' => $result['value'],
        ]);
    }

    protected function getRequestedPeriod(Leaderboard $leaderboard): string
    {
        $period = $this->filter('period', 'str');
        return in_array($period, $leaderboard->periods, true) ? $period : $leaderboard->default_period;
    }

    protected function assertCanViewLeaderboards()
    {
        if (!\XF::visitor()->canViewMemberList())
        {
            throw $this->exception($this->noPermission());
        }
    }

    /**
     * @return Leaderboard
     */
    protected function assertViewableLeaderboard($id)
    {
        /** @var Leaderboard $leaderboard */
        $leaderboard = $this->assertRecordExists(
            'Uvopia\Leaderboards:Leaderboard', $id, null, 'uvopia_leaderboards_requested_leaderboard_not_found'
        );
        if (!$leaderboard->canView() || !$this->getLeaderboardRepo()->isCriteriaAvailable($leaderboard->criteria))
        {
            throw $this->exception($this->notFound(\XF::phrase('uvopia_leaderboards_requested_leaderboard_not_found')));
        }
        return $leaderboard;
    }

    /**
     * @return LeaderboardRepository
     */
    protected function getLeaderboardRepo()
    {
        return $this->repository(LeaderboardRepository::class);
    }

    public static function getActivityDetails(array $activities)
    {
        return \XF::phrase('uvopia_leaderboards_viewing_leaderboards');
    }
}
