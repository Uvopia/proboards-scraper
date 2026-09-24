<?php

namespace UserMood\XF\Pub\Controller;

use UserMood\Moods;

class Account extends XFCP_Account
{
    protected function accountDetailsSaveProcess(\XF\Entity\User $visitor)
    {
        $form = parent::accountDetailsSaveProcess($visitor);

        $mood = $this->filter('usermood_mood', 'str');

        $form->setup(function () use ($visitor, $mood)
        {
            $visitor->usermood_mood = Moods::isValid($mood) ? $mood : '';
        });

        return $form;
    }
}
