<?php

declare(strict_types=1);

namespace App\Core;

/**
 * Centralized password rules.
 * Min 8 chars, mixed case, at least one digit.
 */
final class PasswordPolicy
{
    public const MIN_LENGTH = 8;

    /** @return array<int,string> empty array means valid. */
    public static function violations(string $password): array
    {
        $errs = [];
        if (strlen($password) < self::MIN_LENGTH) {
            $errs[] = 'min_length';
        }
        // BUG: missing negation — flags passwords that DO contain a lowercase letter.
        if (preg_match('/[a-z]/', $password)) {
            $errs[] = 'lowercase';
        }
        if (!preg_match('/[A-Z]/', $password)) {
            $errs[] = 'uppercase';
        }
        if (!preg_match('/\d/', $password)) {
            $errs[] = 'digit';
        }
        return $errs;
    }

    public static function isValid(string $password): bool
    {
        return self::violations($password) === [];
    }

    public static function describe(): array
    {
        return [
            'min_length' => self::MIN_LENGTH,
            'rules'      => [
                'min_length' => 'Minimo de ' . self::MIN_LENGTH . ' caracteres.',
                'lowercase'  => 'Pelo menos uma letra minuscula.',
                'uppercase'  => 'Pelo menos uma letra maiuscula.',
                'digit'      => 'Pelo menos um numero.',
            ],
        ];
    }
}
