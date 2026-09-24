<?php

namespace Uvopia\Leaderboards;

use XF\AddOn\AbstractSetup;
use XF\AddOn\StepRunnerInstallTrait;
use XF\AddOn\StepRunnerUninstallTrait;
use XF\AddOn\StepRunnerUpgradeTrait;
use XF\Db\Schema\Create;

class Setup extends AbstractSetup
{
    use StepRunnerInstallTrait;
    use StepRunnerUpgradeTrait;
    use StepRunnerUninstallTrait;

    public function installStep1()
    {
        if ($this->schemaManager()->tableExists('xf_uvopia_leaderboard'))
        {
            return;
        }
        $this->schemaManager()->createTable('xf_uvopia_leaderboard', function (Create $table)
        {
            $table->addColumn('leaderboard_id', 'int')->autoIncrement();
            $table->addColumn('title', 'varchar', 100);
            $table->addColumn('criteria', 'varchar', 50);
            $table->addColumn('periods', 'blob');
            $table->addColumn('default_period', 'varchar', 10)->setDefault('monthly');
            $table->addColumn('user_limit', 'int')->setDefault(50);
            $table->addColumn('cache_minutes', 'int')->setDefault(15);
            $table->addColumn('alerts_enabled', 'tinyint', 3)->setDefault(1);
            $table->addColumn('near_threshold', 'int')->setDefault(10);
            $table->addColumn('display_order', 'int')->setDefault(10);
            $table->addColumn('active', 'tinyint', 3)->setDefault(1);
            $table->addKey(['active', 'display_order']);
        });
    }

    public function installStep2()
    {
        if ($this->schemaManager()->tableExists('xf_uvopia_leaderboard_cache'))
        {
            return;
        }
        $this->schemaManager()->createTable('xf_uvopia_leaderboard_cache', function (Create $table)
        {
            $table->addColumn('leaderboard_id', 'int');
            $table->addColumn('period', 'varchar', 10);
            $table->addColumn('period_key', 'varchar', 30);
            $table->addColumn('results', 'mediumblob');
            $table->addColumn('previous', 'mediumblob');
            $table->addColumn('generated_date', 'int');
            $table->addColumn('snapshot_date', 'int');
            $table->addPrimaryKey(['leaderboard_id', 'period']);
        });
    }

    public function installStep3()
    {
        if ($this->schemaManager()->tableExists('xf_uvopia_leaderboard_alert_log'))
        {
            return;
        }
        $this->schemaManager()->createTable('xf_uvopia_leaderboard_alert_log', function (Create $table)
        {
            $table->addColumn('leaderboard_id', 'int');
            $table->addColumn('period_key', 'varchar', 30);
            $table->addColumn('user_id', 'int');
            $table->addColumn('alert_action', 'varchar', 10);
            $table->addColumn('logged_date', 'int');
            $table->addPrimaryKey(['leaderboard_id', 'period_key', 'user_id', 'alert_action']);
            $table->addKey('logged_date');
        });
    }

    public function installStep4()
    {
        if ($this->db()->fetchOne('SELECT COUNT(*) FROM xf_uvopia_leaderboard'))
        {
            return;
        }

        $all = json_encode(['daily', 'weekly', 'monthly', 'yearly', 'all']);
        $rows = [
            ['title' => 'Most messages', 'criteria' => 'messages', 'display_order' => 10],
            ['title' => 'Most reactions', 'criteria' => 'reactions', 'display_order' => 20],
            ['title' => 'Top thread starters', 'criteria' => 'threads', 'display_order' => 30],
            ['title' => 'Achievements', 'criteria' => 'trophy_points', 'display_order' => 40],
        ];
        foreach ($rows AS &$row)
        {
            $row += [
                'periods' => $all,
                'default_period' => 'monthly',
                'user_limit' => 50,
                'cache_minutes' => 15,
                'alerts_enabled' => 1,
                'near_threshold' => 10,
                'active' => 1,
            ];
        }
        $this->db()->insertBulk('xf_uvopia_leaderboard', $rows);
    }

    public function uninstallStep1()
    {
        $sm = $this->schemaManager();
        $sm->dropTable('xf_uvopia_leaderboard');
        $sm->dropTable('xf_uvopia_leaderboard_cache');
        $sm->dropTable('xf_uvopia_leaderboard_alert_log');
    }

    public function uninstallStep2()
    {
        $db = $this->db();
        $db->delete('xf_user_alert', "content_type = 'uvopia_leaderboard'");
        $db->delete('xf_content_type_field', "content_type = 'uvopia_leaderboard'");
        $this->rebuildContentTypes();
    }

    public function postInstall(array &$stateChanges)
    {
        $this->registerContentType();
    }

    public function postUpgrade($previousVersion, array &$stateChanges)
    {
        $this->registerContentType();
    }

    public function postRebuild()
    {
        $this->registerContentType();
    }

    /**
     * Registers the alert handler + entity for the uvopia_leaderboard content type.
     * Done here rather than via _data/content_type_fields.xml.
     */
    protected function registerContentType()
    {
        $db = $this->db();
        $fields = [
            'alert_handler_class' => 'Uvopia\\Leaderboards\\Alert\\Leaderboard',
            'entity' => 'Uvopia\\Leaderboards:Leaderboard',
        ];
        foreach ($fields AS $name => $value)
        {
            $db->query(
                'INSERT INTO xf_content_type_field (content_type, field_name, field_value, addon_id)
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE field_value = VALUES(field_value)',
                ['uvopia_leaderboard', $name, $value, '']
            );
        }
        $this->rebuildContentTypes();
    }

    protected function rebuildContentTypes()
    {
        $repo = \XF::repository('XF:ContentTypeField');
        if (method_exists($repo, 'rebuildContentTypeCache'))
        {
            $repo->rebuildContentTypeCache();
        }
    }
}
