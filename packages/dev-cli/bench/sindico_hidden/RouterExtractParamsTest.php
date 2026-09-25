<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\Router;
use PHPUnit\Framework\TestCase;

final class RouterExtractParamsTest extends TestCase
{
    public function test_single_param(): void
    {
        $r = new Router();
        self::assertSame(['id' => '42'], $r->extractParams('/users/{id}', '/users/42'));
    }

    public function test_multiple_params(): void
    {
        $r = new Router();
        self::assertSame(
            ['id' => '7', 'slug' => 'hello-world'],
            $r->extractParams('/posts/{id}/comments/{slug}', '/posts/7/comments/hello-world')
        );
    }

    public function test_no_params_in_pattern(): void
    {
        $r = new Router();
        self::assertSame([], $r->extractParams('/health', '/health'));
    }

    public function test_path_does_not_match_returns_null(): void
    {
        $r = new Router();
        self::assertNull($r->extractParams('/users/{id}', '/posts/42'));
        self::assertNull($r->extractParams('/users/{id}', '/users/42/extra'));
    }

    public function test_is_instance_method(): void
    {
        $rm = new \ReflectionMethod(Router::class, 'extractParams');
        self::assertFalse($rm->isStatic());
        self::assertTrue($rm->isPublic());
    }
}
