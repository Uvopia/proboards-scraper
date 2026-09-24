<?php

namespace Uvopia\Leaderboards\Widget;

use Uvopia\Leaderboards\Entity\Leaderboard as LeaderboardEntity;
use Uvopia\Leaderboards\Repository\LeaderboardRepository;
use XF\Widget\AbstractWidget;

class Leaderboard extends AbstractWidget
{
    protected $defaultOptions = [
        'leaderboard_id' => 0,
        'period' => '',
        'limit' => 5,
    ];

    protected function getDefaultTemplateParams($context)
    {
        $params = parent::getDefaultTemplateParams($context);
        if ($context == 'options')
        {
            $params['leaderboards'] = $this->app->finder('Uvopia\Leaderboards:Leaderboard')->order('display_order')->fetch();
            $params['periods'] = $this->getLeaderboardRepo()->getPeriods();
        }
        return $params;
    }

    public function render()
    {
        if (!\XF::visitor()->canViewMemberList())
        {
            return '';
        }

        /** @var LeaderboardEntity|null $leaderboard */
        $leaderboard = $this->app->em()->find('Uvopia\Leaderboards:Leaderboard', $this->options['leaderboard_id']);
        $repo = $this->getLeaderboardRepo();
        if (!$leaderboard || !$leaderboard->active || !$repo->isCriteriaAvailable($leaderboard->criteria))
        {
            return '';
        }

        $period = in_array($this->options['period'], $leaderboard->periods, true)
            ? $this->options['period']
            : $leaderboard->default_period;

        $results = $repo->getResults($leaderboard, $period);
        $entries = array_slice($results['entries'], 0, max(1, (int)$this->options['limit']));
        $entries = $repo->attachUsers($entries);

        return $this->renderer('widget_uvopia_leaderboard', [
            'title' => $this->widgetConfig->title ?: $leaderboard->title,
            'leaderboard' => $leaderboard,
            'period' => $period,
            'entries' => $entries,
        ]);
    }

    public function verifyOptions(\XF\Http\Request $request, array &$options, &$error = null)
    {
        $options = $request->filter([
            'leaderboard_id' => 'uint',
            'period' => 'str',
            'limit' => 'uint',
        ]);
        if ($options['limit'] < 1)
        {
            $options['limit'] = 5;
        }
        if (!$options['leaderboard_id'])
        {
            $error = \XF::phrase('uvopia_leaderboards_requested_leaderboard_not_found');
            return false;
        }
        return true;
    }

    public function getOptionsTemplate()
    {
        return 'admin:widget_def_options_uvopia_leaderboard';
    }

    /**
     * @return LeaderboardRepository
     */
    protected function getLeaderboardRepo()
    {
        return $this->app->repository(LeaderboardRepository::class);
    }
}
