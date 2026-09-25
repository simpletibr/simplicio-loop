<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\PasswordPolicy;
use PHPUnit\Framework\TestCase;

final class PasswordAssessTest extends TestCase
{
    public function test_valid_password(): void
    {
        $result = PasswordPolicy::assess('SenhaForte123');
        self::assertSame(true, $result['valid']);
        self::assertSame([], $result['violations']);
        self::assertSame(13, $result['length']);
    }

    public function test_invalid_password(): void
    {
        $result = PasswordPolicy::assess('fraca');
        self::assertSame(false, $result['valid']);
        self::assertContains('min_length', $result['violations']);
        self::assertContains('uppercase', $result['violations']);
        self::assertContains('digit', $result['violations']);
        self::assertSame(5, $result['length']);
    }

    public function test_empty_password(): void
    {
        $result = PasswordPolicy::assess('');
        self::assertSame(false, $result['valid']);
        self::assertSame(0, $result['length']);
    }

    public function test_existing_methods_untouched(): void
    {
        self::assertTrue(PasswordPolicy::isValid('SenhaForte123'));
        self::assertSame([], PasswordPolicy::violations('SenhaForte123'));
    }
}
