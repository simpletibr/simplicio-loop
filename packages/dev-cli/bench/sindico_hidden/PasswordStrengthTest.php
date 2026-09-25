<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\PasswordPolicy;
use PHPUnit\Framework\TestCase;

final class PasswordStrengthTest extends TestCase
{
    public function test_weak_when_violates_existing_rules(): void
    {
        self::assertSame('weak', PasswordPolicy::strength('fraca'));
    }

    public function test_medium_when_valid_short_no_symbol(): void
    {
        // 11 chars, valid (lower+upper+digit, >=8), no symbol
        self::assertSame('medium', PasswordPolicy::strength('SenhaForte1'));
    }

    public function test_strong_when_valid_long_with_symbol(): void
    {
        // 13 chars, valid, has symbol
        self::assertSame('strong', PasswordPolicy::strength('SenhaSegura1!'));
    }

    public function test_medium_when_long_but_no_symbol(): void
    {
        // 13 chars, valid, no symbol -> medium (not strong)
        self::assertSame('medium', PasswordPolicy::strength('SenhaSegura12'));
    }

    public function test_weak_overrides_symbol_when_short(): void
    {
        // 7 chars violates min_length -> weak even with symbol
        self::assertSame('weak', PasswordPolicy::strength('Ab1!cdX'));
    }

    public function test_existing_isValid_untouched(): void
    {
        self::assertTrue(PasswordPolicy::isValid('SenhaForte123'));
        self::assertSame([], PasswordPolicy::violations('SenhaForte123'));
    }
}
