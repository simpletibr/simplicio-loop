<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\PasswordPolicy;
use PHPUnit\Framework\TestCase;

final class PasswordRequireSymbolTest extends TestCase
{
    public function test_no_symbol_returns_symbol_violation(): void
    {
        self::assertSame(['symbol'], PasswordPolicy::requireSymbol('abc123'));
        self::assertSame(['symbol'], PasswordPolicy::requireSymbol(''));
    }

    public function test_has_symbol_returns_empty(): void
    {
        self::assertSame([], PasswordPolicy::requireSymbol('abc!'));
        self::assertSame([], PasswordPolicy::requireSymbol('AB@CD'));
        self::assertSame([], PasswordPolicy::requireSymbol('!'));
        self::assertSame([], PasswordPolicy::requireSymbol('x#y'));
    }

    public function test_existing_methods_untouched(): void
    {
        self::assertTrue(PasswordPolicy::isValid('SenhaForte123'));
        self::assertSame([], PasswordPolicy::violations('SenhaForte123'));
        self::assertSame(8, PasswordPolicy::MIN_LENGTH);
    }
}
