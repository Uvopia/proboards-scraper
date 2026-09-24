<?php

namespace Uvopia\Leaderboards\Admin\Controller;

use Uvopia\Leaderboards\Entity\Leaderboard;
use Uvopia\Leaderboards\Repository\LeaderboardRepository;
use XF\Admin\Controller\AbstractController;
use XF\Mvc\ParameterBag;

class LeaderboardController extends AbstractController
{
    public function actionIndex()
    {
        $this->assertAdminPermission('user');

        $leaderboards = $this->finder('Uvopia\Leaderboards:Leaderboard')->order('display_order')->fetch();

        return $this->view('Uvopia\Leaderboards:Leaderboard\Listing', 'uvopia_leaderboard_list', [
            'leaderboards' => $leaderboards,
        ]);
    }

    protected function leaderboardAddEdit(Leaderboard $leaderboard)
    {
        $repo = $this->getLeaderboardRepo();

        return $this->view('Uvopia\Leaderboards:Leaderboard\Edit', 'uvopia_leaderboard_edit', [
            'leaderboard' => $leaderboard,
            'criteria' => $repo->getCriteriaDefinitions(),
            'periods' => $repo->getPeriods(),
        ]);
    }

    public function actionAdd()
    {
        $this->assertAdminPermission('user');

        /** @var Leaderboard $leaderboard */
        $leaderboard = $this->em()->create('Uvopia\Leaderboards:Leaderboard');
        $leaderboard->periods = $this->getLeaderboardRepo()->getPeriods();

        return $this->leaderboardAddEdit($leaderboard);
    }

    public function actionEdit(ParameterBag $params)
    {
        $this->assertAdminPermission('user');
        return $this->leaderboardAddEdit($this->assertLeaderboardExists($params->leaderboard_id));
    }

    public function actionSave(ParameterBag $params)
    {
        $this->assertAdminPermission('user');
        $this->assertPostOnly();

        if ($params->leaderboard_id)
        {
            $leaderboard = $this->assertLeaderboardExists($params->leaderboard_id);
        }
        else
        {
            $leaderboard = $this->em()->create('Uvopia\Leaderboards:Leaderboard');
        }

        $input = $this->filter([
            'title' => 'str',
            'criteria' => 'str',
            'periods' => 'array-str',
            'default_period' => 'str',
            'user_limit' => 'uint',
            'cache_minutes' => 'uint',
            'alerts_enabled' => 'bool',
            'near_threshold' => 'uint',
            'display_order' => 'uint',
            'active' => 'bool',
        ]);

        $form = $this->formAction();
        $form->basicEntitySave($leaderboard, $input);
        $form->run();

        return $this->redirect($this->buildLink('leaderboards') . $this->buildLinkHash($leaderboard->leaderboard_id));
    }

    public function actionDelete(ParameterBag $params)
    {
        $this->assertAdminPermission('user');
        $leaderboard = $this->assertLeaderboardExists($params->leaderboard_id);

        /** @var \XF\ControllerPlugin\Delete $plugin */
        $plugin = $this->plugin('XF:Delete');
        return $plugin->actionDelete(
            $leaderboard,
            $this->buildLink('leaderboards/delete', $leaderboard),
            $this->buildLink('leaderboards/edit', $leaderboard),
            $this->buildLink('leaderboards'),
            $leaderboard->title
        );
    }

    public function actionToggle()
    {
        $this->assertAdminPermission('user');

        /** @var \XF\ControllerPlugin\Toggle $plugin */
        $plugin = $this->plugin('XF:Toggle');
        return $plugin->actionToggle('Uvopia\Leaderboards:Leaderboard', 'active');
    }

    public function actionClearCache()
    {
        $this->assertAdminPermission('user');
        $this->assertPostOnly();

        $this->app()->db()->emptyTable('xf_uvopia_leaderboard_cache');

        return $this->redirect($this->buildLink('leaderboards'));
    }

    /**
     * @return Leaderboard
     */
    protected function assertLeaderboardExists($id)
    {
        return $this->assertRecordExists(
            'Uvopia\Leaderboards:Leaderboard', $id, null, 'uvopia_leaderboards_requested_leaderboard_not_found'
        );
    }

    /**
     * @return LeaderboardRepository
     */
    protected function getLeaderboardRepo()
    {
        return $this->repository(LeaderboardRepository::class);
    }
}
