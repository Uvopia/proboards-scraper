<?php

namespace UserMood;

use XF\Mvc\Entity\Entity;
use XF\Mvc\Entity\Manager;
use XF\Mvc\Entity\Structure;

class Listener
{
    public static function userEntityStructure(Manager $em, Structure &$structure)
    {
        $structure->columns['usermood_mood'] = [
            'type' => Entity::STR,
            'maxLength' => 25,
            'default' => '',
            'allowedValues' => array_merge([''], array_keys(Moods::getAll()))
        ];

        $structure->getters['mood_info'] = true;
        $structure->getters['mood_select_options'] = true;
    }
}
