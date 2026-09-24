<?php

namespace UserMood\XF\Entity;

use UserMood\Moods;

class User extends XFCP_User
{
    /** The member's current mood (icon + label), or null if none set. */
    public function getMoodInfo(): ?array
    {
        if (!$this->usermood_mood)
        {
            return null;
        }
        return Moods::get($this->usermood_mood);
    }

    /** key => "emoji Label" pairs for the dropdown. */
    public function getMoodSelectOptions(): array
    {
        $options = [];
        foreach (Moods::getAll() AS $key => $mood)
        {
            $options[$key] = $mood['icon'] . ' ' . $mood['label'];
        }
        return $options;
    }
}
