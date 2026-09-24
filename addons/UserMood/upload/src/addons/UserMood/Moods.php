<?php

namespace UserMood;

/**
 * The master list of moods. Add, remove, or reorder entries here.
 * Keys are stored in the database (max 25 chars) — don't rename a key
 * once members are using it, or their mood will reset to none.
 */
class Moods
{
    public static function getAll(): array
    {
        return [
            'happy'      => ['icon' => '😀', 'label' => 'Happy'],
            'excited'    => ['icon' => '🤩', 'label' => 'Excited'],
            'loved'      => ['icon' => '🥰', 'label' => 'Loved'],
            'chill'      => ['icon' => '😎', 'label' => 'Chill'],
            'content'    => ['icon' => '😌', 'label' => 'Content'],
            'goofy'      => ['icon' => '🤪', 'label' => 'Goofy'],
            'thoughtful' => ['icon' => '🤔', 'label' => 'Thoughtful'],
            'busy'       => ['icon' => '🤯', 'label' => 'Busy'],
            'tired'      => ['icon' => '😴', 'label' => 'Tired'],
            'bored'      => ['icon' => '😑', 'label' => 'Bored'],
            'sick'       => ['icon' => '🤒', 'label' => 'Sick'],
            'sad'        => ['icon' => '😢', 'label' => 'Sad'],
            'angry'      => ['icon' => '😠', 'label' => 'Angry'],
            'nervous'    => ['icon' => '😬', 'label' => 'Nervous'],
            'hungry'     => ['icon' => '🍕', 'label' => 'Hungry'],
            'caffeinated'=> ['icon' => '☕', 'label' => 'Caffeinated'],
        ];
    }

    public static function get(string $key): ?array
    {
        $all = self::getAll();
        return $all[$key] ?? null;
    }

    public static function isValid(string $key): bool
    {
        return $key === '' || isset(self::getAll()[$key]);
    }
}
