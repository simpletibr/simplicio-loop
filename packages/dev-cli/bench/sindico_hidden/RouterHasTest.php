<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\Router;
use PHPUnit\Framework\TestCase;

final class RouterHasTest extends TestCase
{
    public function test_fresh_router_has_nothing(): void
    {
        $r = new Router();
        self::assertFalse($r->has('GET', '/anything'));
    }

    public function test_registered_literal_route_is_found(): void
    {
        $r = new Router();
        $r->get('/api/health', fn() => null);
        self::assertTrue($r->has('GET', '/api/health'));
    }

    public function test_wrong_method_misses(): void
    {
        $r = new Router();
        $r->get('/api/health', fn() => null);
        self::assertFalse($r->has('POST', '/api/health'));
    }

    public function test_parameterized_route_matches_concrete_path(): void
    {
        $r = new Router();
        $r->get('/users/{id}', fn() => null);
        self::assertTrue($r->has('GET', '/users/42'));
        self::assertTrue($r->has('GET', '/users/abc'));
    }

    public function test_unknown_path_misses(): void
    {
        $r = new Router();
        $r->get('/api/health', fn() => null);
        self::assertFalse($r->has('GET', '/nope'));
    }

    public function test_is_instance_public(): void
    {
        $rm = new \ReflectionMethod(Router::class, 'has');
        self::assertFalse($rm->isStatic(), 'has must be an instance method');
        self::assertTrue($rm->isPublic());
    }
}
