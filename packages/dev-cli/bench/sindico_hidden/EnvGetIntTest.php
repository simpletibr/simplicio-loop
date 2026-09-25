<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\Env;
use PHPUnit\Framework\TestCase;

final class EnvGetIntTest extends TestCase
{
    private const KEY = 'BENCH_HIDDEN_INT';

    private function setVar(string $v): void
    {
        $_ENV[self::KEY] = $v;
        putenv(self::KEY . '=' . $v);
    }

    private function clearVar(): void
    {
        unset($_ENV[self::KEY]);
        putenv(self::KEY);
    }

    protected function setUp(): void
    {
        $this->clearVar();
    }

    protected function tearDown(): void
    {
        $this->clearVar();
    }

    public function test_numeric_string_returns_int(): void
    {
        $this->setVar('42');
        self::assertSame(42, Env::getInt(self::KEY));
    }

    public function test_negative_numeric(): void
    {
        $this->setVar('-5');
        self::assertSame(-5, Env::getInt(self::KEY));
    }

    public function test_non_numeric_returns_default(): void
    {
        $this->setVar('abc');
        self::assertSame(7, Env::getInt(self::KEY, 7));
    }

    public function test_missing_returns_default(): void
    {
        $this->clearVar();
        self::assertSame(0, Env::getInt(self::KEY));
        self::assertSame(99, Env::getInt(self::KEY, 99));
    }
}
