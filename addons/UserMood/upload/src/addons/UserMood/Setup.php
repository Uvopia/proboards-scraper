<?php

namespace UserMood;

use XF\AddOn\AbstractSetup;
use XF\AddOn\StepRunnerInstallTrait;
use XF\AddOn\StepRunnerUninstallTrait;
use XF\AddOn\StepRunnerUpgradeTrait;
use XF\Db\Schema\Alter;

class Setup extends AbstractSetup
{
    use StepRunnerInstallTrait;
    use StepRunnerUpgradeTrait;
    use StepRunnerUninstallTrait;

    public function installStep1()
    {
        $this->schemaManager()->alterTable('xf_user', function (Alter $table)
        {
            $table->addColumn('usermood_mood', 'varchar', 25)->setDefault('');
        });
    }

    public function uninstallStep1()
    {
        $this->schemaManager()->alterTable('xf_user', function (Alter $table)
        {
            $table->dropColumns(['usermood_mood']);
        });
    }
}
