<?php

namespace Uvopia\Leaderboards\Repository;

use Uvopia\Leaderboards\Entity\Leaderboard;
use XF\Mvc\Entity\Repository;

class LeaderboardRepository extends Repository
{
    public function getPeriods(): array
    {
        return ['daily', 'weekly', 'monthly', 'yearly', 'all'];
    }

    /**
     * @param bool $includeUnavailable include criteria whose add-on (XFRM/XFMG) is not active
     */
    public function getCriteriaDefinitions(bool $includeUnavailable = false): array
    {
        $criteria = [];
        foreach (['messages', 'threads', 'reactions', 'trophy_points', 'resources', 'media'] AS $key)
        {
            if ($includeUnavailable || $this->isCriteriaAvailable($key))
            {
                $criteria[$key] = \XF::phrase('uvopia_leaderboards_criteria_' . $key);
            }
        }
        return $criteria;
    }

    public function isCriteriaAvailable(string $criteria): bool
    {
        switch ($criteria)
        {
            case 'resources': return \XF::isAddOnActive('XFRM');
            case 'media': return \XF::isAddOnActive('XFMG');
            case 'messages':
            case 'threads':
            case 'reactions':
            case 'trophy_points':
                return true;
            default:
                return false;
        }
    }

    /**
     * Active leaderboards whose criteria can currently be computed, keyed by ID.
     */
    public function getViewableLeaderboards()
    {
        return $this->finder('Uvopia\Leaderboards:Leaderboard')
            ->where('active', 1)
            ->order('display_order')
            ->fetch()
            ->filter(function (Leaderboard $lb)
            {
                return $this->isCriteriaAvailable($lb->criteria);
            });
    }

    /**
     * Calendar-based period boundaries in the board's default time zone.
     */
    public function getPeriodRange(string $period): array
    {
        if ($period === 'all')
        {
            return ['start' => 0, 'end' => 0, 'key' => 'all', 'all' => true];
        }

        try
        {
            $tz = new \DateTimeZone(\XF::options()->guestTimeZone ?: 'UTC');
        }
        catch (\Exception $e)
        {
            $tz = new \DateTimeZone('UTC');
        }

        $now = new \DateTime('@' . \XF::$time);
        $now->setTimezone($tz);
        $start = clone $now;
        $start->setTime(0, 0, 0);

        switch ($period)
        {
            case 'daily':
                $end = (clone $start)->modify('+1 day');
                $key = $start->format('Y-m-d');
                break;

            case 'weekly':
                $dow = (int)$start->format('N'); // 1 = Monday
                if ($dow > 1)
                {
                    $start->modify('-' . ($dow - 1) . ' days');
                }
                $end = (clone $start)->modify('+7 days');
                $key = $start->format('o-\WW');
                break;

            case 'monthly':
                $start->setDate((int)$start->format('Y'), (int)$start->format('n'), 1);
                $end = (clone $start)->modify('+1 month');
                $key = $start->format('Y-m');
                break;

            case 'yearly':
                $start->setDate((int)$start->format('Y'), 1, 1);
                $end = (clone $start)->modify('+1 year');
                $key = $start->format('Y');
                break;

            default:
                throw new \InvalidArgumentException("Unknown leaderboard period '$period'");
        }

        return [
            'start' => $start->getTimestamp(),
            'end' => $end->getTimestamp(),
            'key' => $period . ':' . $key,
            'all' => false,
        ];
    }

    /**
     * Returns ['entries' => [...], 'generated_date' => int, 'period_key' => string].
     * Each entry: user_id, value, position, change_type (up|down|same|new|''), change_abs.
     */
    public function getResults(Leaderboard $leaderboard, string $period): array
    {
        $db = $this->db();
        $range = $this->getPeriodRange($period);
        $now = \XF::$time;

        if (!$this->isCriteriaAvailable($leaderboard->criteria))
        {
            return ['entries' => [], 'generated_date' => $now, 'period_key' => $range['key']];
        }

        $row = $db->fetchRow(
            'SELECT * FROM xf_uvopia_leaderboard_cache WHERE leaderboard_id = ? AND period = ?',
            [$leaderboard->leaderboard_id, $period]
        );

        $samePeriod = $row && $row['period_key'] === $range['key'];
        $cacheFresh = $samePeriod
            && $leaderboard->cache_minutes > 0
            && $row['generated_date'] > $now - ($leaderboard->cache_minutes * 60);

        if ($cacheFresh)
        {
            $ranked = json_decode($row['results'], true) ?: [];
            $previous = json_decode($row['previous'], true) ?: [];
            $generated = (int)$row['generated_date'];
        }
        else
        {
            $ranked = $this->computeRankings($leaderboard->criteria, $range, $leaderboard->user_limit);
            $generated = $now;

            // Position changes are measured against a snapshot roughly a day old,
            // reset whenever a new calendar period begins.
            $previous = [];
            $snapshotDate = $now;
            if ($samePeriod)
            {
                if ($row['snapshot_date'] > $now - 86400)
                {
                    $previous = json_decode($row['previous'], true) ?: [];
                    $snapshotDate = (int)$row['snapshot_date'];
                }
                else
                {
                    foreach (json_decode($row['results'], true) ?: [] AS $old)
                    {
                        $previous[$old['user_id']] = $old['position'];
                    }
                }
            }

            $db->query(
                'INSERT INTO xf_uvopia_leaderboard_cache
                    (leaderboard_id, period, period_key, results, previous, generated_date, snapshot_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    period_key = VALUES(period_key),
                    results = VALUES(results),
                    previous = VALUES(previous),
                    generated_date = VALUES(generated_date),
                    snapshot_date = VALUES(snapshot_date)',
                [
                    $leaderboard->leaderboard_id, $period, $range['key'],
                    json_encode($ranked), json_encode((object)$previous), $generated, $snapshotDate
                ]
            );
        }

        $hasSnapshot = !empty($previous);
        $entries = [];
        foreach ($ranked AS $entry)
        {
            $entry['change_type'] = '';
            $entry['change_abs'] = 0;
            if ($hasSnapshot)
            {
                $old = $previous[$entry['user_id']] ?? null;
                if ($old === null)
                {
                    $entry['change_type'] = 'new';
                }
                else
                {
                    $diff = (int)$old - (int)$entry['position'];
                    $entry['change_type'] = $diff > 0 ? 'up' : ($diff < 0 ? 'down' : 'same');
                    $entry['change_abs'] = abs($diff);
                }
            }
            $entries[] = $entry;
        }

        return ['entries' => $entries, 'generated_date' => $generated, 'period_key' => $range['key']];
    }

    public function clearCache(int $leaderboardId)
    {
        $this->db()->delete('xf_uvopia_leaderboard_cache', 'leaderboard_id = ?', $leaderboardId);
    }

    /**
     * Live lookup for users outside the cached top list.
     * Uses competition ranking (1, 2, 2, 4) to match the list.
     */
    public function getUserPosition(Leaderboard $leaderboard, string $period, int $userId): array
    {
        if (!$userId || !$this->isCriteriaAvailable($leaderboard->criteria))
        {
            return ['position' => null, 'value' => 0];
        }

        $db = $this->db();
        $range = $this->getPeriodRange($period);

        [$sql, $params] = $this->getAggregateQuery($leaderboard->criteria, $range, $userId);
        $value = (int)$db->fetchOne("SELECT agg.value FROM ($sql) AS agg", $params);
        if ($value <= 0)
        {
            return ['position' => null, 'value' => 0];
        }

        [$sql, $params] = $this->getAggregateQuery($leaderboard->criteria, $range);
        $params[] = $value;
        $higher = (int)$db->fetchOne(
            "SELECT COUNT(*)
            FROM ($sql) AS agg
            INNER JOIN xf_user AS u ON (u.user_id = agg.user_id)
            WHERE u.user_state = 'valid' AND u.is_banned = 0 AND agg.value > ?",
            $params
        );

        return ['position' => $higher + 1, 'value' => $value];
    }

    protected function computeRankings(string $criteria, array $range, int $limit): array
    {
        [$sql, $params] = $this->getAggregateQuery($criteria, $range);

        $rows = $this->db()->fetchAll(
            "SELECT agg.user_id, agg.value
            FROM ($sql) AS agg
            INNER JOIN xf_user AS u ON (u.user_id = agg.user_id)
            WHERE u.user_state = 'valid' AND u.is_banned = 0 AND agg.value > 0
            ORDER BY agg.value DESC, agg.user_id ASC
            LIMIT " . max(1, (int)$limit),
            $params
        );

        $ranked = [];
        $position = 0;
        $lastValue = null;
        foreach ($rows AS $i => $row)
        {
            $value = (int)$row['value'];
            if ($value !== $lastValue)
            {
                $position = $i + 1;
                $lastValue = $value;
            }
            $ranked[] = ['user_id' => (int)$row['user_id'], 'value' => $value, 'position' => $position];
        }

        return $ranked;
    }

    /**
     * Builds a query returning (user_id, value) rows for the given criteria and range.
     */
    protected function getAggregateQuery(string $criteria, array $range, ?int $userId = null): array
    {
        $allTime = !empty($range['all']);

        // All-time totals XenForo already maintains on xf_user are used directly.
        $userColumns = [
            'messages' => 'message_count',
            'reactions' => 'reaction_score',
            'trophy_points' => 'trophy_points',
        ];
        if ($allTime && isset($userColumns[$criteria]))
        {
            $sql = "SELECT user_id, {$userColumns[$criteria]} AS value FROM xf_user WHERE user_id > 0";
            $params = [];
            if ($userId)
            {
                $sql .= ' AND user_id = ?';
                $params[] = $userId;
            }
            return [$sql, $params];
        }

        switch ($criteria)
        {
            case 'messages':
                $spec = ['from' => 'xf_post AS post', 'user' => 'post.user_id', 'value' => 'COUNT(*)',
                    'where' => ["post.message_state = 'visible'"], 'date' => 'post.post_date'];
                break;

            case 'threads':
                $spec = ['from' => 'xf_thread AS thread', 'user' => 'thread.user_id', 'value' => 'COUNT(*)',
                    'where' => ["thread.discussion_state = 'visible'", "thread.discussion_type <> 'redirect'"],
                    'date' => 'thread.post_date'];
                break;

            case 'reactions':
                $spec = ['from' => 'xf_reaction_content AS rc INNER JOIN xf_reaction AS r ON (r.reaction_id = rc.reaction_id)',
                    'user' => 'rc.content_user_id', 'value' => 'SUM(r.reaction_score)',
                    'where' => ['rc.is_counted = 1'], 'date' => 'rc.reaction_date'];
                break;

            case 'trophy_points':
                $spec = ['from' => 'xf_user_trophy AS ut INNER JOIN xf_trophy AS t ON (t.trophy_id = ut.trophy_id)',
                    'user' => 'ut.user_id', 'value' => 'SUM(t.trophy_points)',
                    'where' => [], 'date' => 'ut.award_date'];
                break;

            case 'resources':
                $spec = ['from' => 'xf_rm_resource AS res', 'user' => 'res.user_id', 'value' => 'COUNT(*)',
                    'where' => ["res.resource_state = 'visible'"], 'date' => 'res.resource_date'];
                break;

            case 'media':
                $spec = ['from' => 'xf_mg_media_item AS media', 'user' => 'media.user_id', 'value' => 'COUNT(*)',
                    'where' => ["media.media_state = 'visible'"], 'date' => 'media.media_date'];
                break;

            default:
                throw new \InvalidArgumentException("Unknown leaderboard criteria '$criteria'");
        }

        $where = $spec['where'];
        $where[] = "{$spec['user']} > 0";
        $params = [];

        if (!$allTime)
        {
            $where[] = "{$spec['date']} >= ?";
            $where[] = "{$spec['date']} < ?";
            $params[] = $range['start'];
            $params[] = $range['end'];
        }
        if ($userId)
        {
            $where[] = "{$spec['user']} = ?";
            $params[] = $userId;
        }

        $sql = "SELECT {$spec['user']} AS user_id, {$spec['value']} AS value
            FROM {$spec['from']}
            WHERE " . implode(' AND ', $where) . "
            GROUP BY {$spec['user']}";

        return [$sql, $params];
    }

    /**
     * Adds a 'user' entity to each entry, dropping entries whose user no longer exists.
     */
    public function attachUsers(array $entries): array
    {
        if (!$entries)
        {
            return [];
        }

        $users = $this->em->findByIds('XF:User', array_column($entries, 'user_id'));
        $output = [];
        foreach ($entries AS $entry)
        {
            if (isset($users[$entry['user_id']]))
            {
                $entry['user'] = $users[$entry['user_id']];
                $output[] = $entry;
            }
        }
        return $output;
    }

    /**
     * Called by cron: alerts members who reach the top 3 ("top") or get
     * within the configured range of it ("near"), once per period.
     */
    public function sendPositionAlerts()
    {
        $db = $this->db();
        /** @var \XF\Repository\UserAlert $alertRepo */
        $alertRepo = $this->repository('XF:UserAlert');

        $leaderboards = $this->finder('Uvopia\Leaderboards:Leaderboard')
            ->where('active', 1)
            ->where('alerts_enabled', 1)
            ->fetch();

        foreach ($leaderboards AS $leaderboard)
        {
            if (!$this->isCriteriaAvailable($leaderboard->criteria))
            {
                continue;
            }

            $period = $leaderboard->default_period;
            $results = $this->getResults($leaderboard, $period);
            $nearLimit = max(3, $leaderboard->near_threshold);

            $candidates = [];
            foreach ($results['entries'] AS $entry)
            {
                if ($entry['position'] > $nearLimit)
                {
                    break;
                }
                $candidates[$entry['user_id']] = $entry;
            }
            if (!$candidates)
            {
                continue;
            }

            $logged = [];
            $logRows = $db->fetchAll(
                'SELECT user_id, alert_action FROM xf_uvopia_leaderboard_alert_log
                WHERE leaderboard_id = ? AND period_key = ? AND user_id IN (' . $db->quote(array_keys($candidates)) . ')',
                [$leaderboard->leaderboard_id, $results['period_key']]
            );
            foreach ($logRows AS $logRow)
            {
                $logged[$logRow['user_id']][$logRow['alert_action']] = true;
            }

            $users = $this->em->findByIds('XF:User', array_keys($candidates), ['Option']);

            foreach ($candidates AS $userId => $entry)
            {
                $action = $entry['position'] <= 3 ? 'top' : 'near';
                if (!empty($logged[$userId]['top']) || ($action === 'near' && !empty($logged[$userId]['near'])))
                {
                    continue;
                }

                /** @var \XF\Entity\User|null $user */
                $user = $users[$userId] ?? null;
                if (!$user)
                {
                    continue;
                }

                // Log first so an opted-out user isn't re-checked every run.
                $db->query(
                    'INSERT IGNORE INTO xf_uvopia_leaderboard_alert_log
                        (leaderboard_id, period_key, user_id, alert_action, logged_date)
                    VALUES (?, ?, ?, ?, ?)',
                    [$leaderboard->leaderboard_id, $results['period_key'], $userId, $action, \XF::$time]
                );

                if ($user->Option && !$user->Option->doesReceiveAlert('uvopia_leaderboard', $action))
                {
                    continue;
                }

                $alertRepo->alert(
                    $user, 0, '', 'uvopia_leaderboard', $leaderboard->leaderboard_id, $action,
                    ['position' => $entry['position'], 'period' => $period]
                );
            }
        }

        // Prune old alert log rows.
        $db->delete('xf_uvopia_leaderboard_alert_log', 'logged_date < ?', \XF::$time - 400 * 86400);
    }
}
