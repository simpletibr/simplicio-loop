<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Middleware\RateLimit;
use PHPUnit\Framework\TestCase;

final class RateLimitBucketKeyTest extends TestCase
{
    public function test_basic_format(): void
    {
        self::assertSame(
            'ratelimit:login:user@example.com',
            RateLimit::bucketKey('login', 'user@example.com')
        );
    }

    public function test_bucket_lowercased(): void
    {
        self::assertSame(
            'ratelimit:verify-code:abc',
            RateLimit::bucketKey('VERIFY-CODE', 'abc')
        );
        self::assertSame(
            'ratelimit:login:abc',
            RateLimit::bucketKey('Login', 'abc')
        );
    }

    public function test_key_trimmed(): void
    {
        self::assertSame(
            'ratelimit:login:user',
            RateLimit::bucketKey('login', '  user  ')
        );
        self::assertSame(
            'ratelimit:login:user',
            RateLimit::bucketKey('login', "\tuser\n")
        );
    }

    public function test_is_static_public(): void
    {
        $rm = new \ReflectionMethod(RateLimit::class, 'bucketKey');
        self::assertTrue($rm->isStatic());
        self::assertTrue($rm->isPublic());
    }
}
