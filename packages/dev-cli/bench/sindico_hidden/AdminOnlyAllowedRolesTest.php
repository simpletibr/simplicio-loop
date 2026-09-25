<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Middleware\AdminOnly;
use PHPUnit\Framework\TestCase;

final class AdminOnlyAllowedRolesTest extends TestCase
{
    public function test_returns_exact_role_list(): void
    {
        self::assertSame(['admin', 'sindico'], AdminOnly::allowedRoles());
    }

    public function test_is_static(): void
    {
        $rm = new \ReflectionMethod(AdminOnly::class, 'allowedRoles');
        self::assertTrue($rm->isStatic(), 'allowedRoles must be a static method');
        self::assertTrue($rm->isPublic(), 'allowedRoles must be public');
    }
}
