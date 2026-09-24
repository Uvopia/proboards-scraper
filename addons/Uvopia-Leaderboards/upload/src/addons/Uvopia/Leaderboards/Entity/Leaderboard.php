<?php

namespace Uvopia\Leaderboards\Entity;

use Uvopia\Leaderboards\Repository\LeaderboardRepository;
use XF\Mvc\Entity\Entity;
use XF\Mvc\Entity\Structure;

/**
 * COLUMNS
 * @property int|null $leaderboard_id
 * @property string $title
 * @property string $criteria
 * @property array $periods
 * @property string $default_period
 * @property int $user_limit
 * @property int $cache_minutes
 * @property bool $alerts_enabled
 * @property int $near_threshold
 * @property int $display_order
 * @property bool $active
 *
 * GETTERS
 * @property \XF\Phrase $criteria_title
 * @property \XF\Phrase $unit_phrase
 */
class Leaderboard extends Entity
{
    public function canView(&$error = null)
    {
        return $this->active && \XF::visitor()->canViewMemberList();
    }

    public function getCriteriaTitle()
    {
        return \XF::phrase('uvopia_leaderboards_criteria_' . $this->criteria);
    }

    public function getUnitPhrase()
    {
        return \XF::phrase('uvopia_leaderboards_unit_' . $this->criteria);
    }

    protected function _preSave()
    {
        $repo = $this->getLeaderboardRepo();

        if (!array_key_exists($this->criteria, $repo->getCriteriaDefinitions(true)))
        {
            $this->error(\XF::phrase('uvopia_leaderboards_invalid_criteria'), 'criteria');
        }

        $periods = array_values(array_intersect($repo->getPeriods(), $this->periods ?: []));
        if (!$periods)
        {
            $this->error(\XF::phrase('uvopia_leaderboards_select_at_least_one_period'), 'periods');
            return;
        }
        if ($periods !== $this->periods)
        {
            $this->periods = $periods;
        }
        if (!in_array($this->default_period, $periods, true))
        {
            $this->default_period = $periods[0];
        }
    }

    protected function _postSave()
    {
        if ($this->isUpdate())
        {
            $this->getLeaderboardRepo()->clearCache($this->leaderboard_id);
        }
    }

    protected function _postDelete()
    {
        $id = $this->leaderboard_id;
        $db = $this->db();
        $db->delete('xf_uvopia_leaderboard_cache', 'leaderboard_id = ?', $id);
        $db->delete('xf_uvopia_leaderboard_alert_log', 'leaderboard_id = ?', $id);
        $this->repository('XF:UserAlert')->fastDeleteAlertsForContent('uvopia_leaderboard', $id);
    }

    public static function getStructure(Structure $structure)
    {
        $structure->table = 'xf_uvopia_leaderboard';
        $structure->shortName = 'Uvopia\Leaderboards:Leaderboard';
        $structure->contentType = 'uvopia_leaderboard';
        $structure->primaryKey = 'leaderboard_id';
        $structure->columns = [
            'leaderboard_id' => ['type' => self::UINT, 'autoIncrement' => true, 'nullable' => true],
            'title' => ['type' => self::STR, 'maxLength' => 100, 'required' => true],
            'criteria' => ['type' => self::STR, 'maxLength' => 50, 'required' => true],
            'periods' => ['type' => self::JSON_ARRAY, 'default' => []],
            'default_period' => ['type' => self::STR, 'default' => 'monthly',
                'allowedValues' => ['daily', 'weekly', 'monthly', 'yearly', 'all']
            ],
            'user_limit' => ['type' => self::UINT, 'default' => 50, 'min' => 1, 'max' => 500],
            'cache_minutes' => ['type' => self::UINT, 'default' => 15, 'max' => 10080],
            'alerts_enabled' => ['type' => self::BOOL, 'default' => true],
            'near_threshold' => ['type' => self::UINT, 'default' => 10, 'min' => 3, 'max' => 100],
            'display_order' => ['type' => self::UINT, 'default' => 10],
            'active' => ['type' => self::BOOL, 'default' => true],
        ];
        $structure->getters = [
            'criteria_title' => true,
            'unit_phrase' => true,
        ];
        $structure->relations = [];

        return $structure;
    }

    /**
     * @return LeaderboardRepository
     */
    protected function getLeaderboardRepo()
    {
        return $this->repository(LeaderboardRepository::class);
    }
}
