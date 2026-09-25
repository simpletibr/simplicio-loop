<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Core\Env;
use PHPUnit\Framework\TestCase;

final class EnvGetBoolTest extends TestCase
{
    private const KEY = 'BENCH_HIDDEN_BOOL';

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

    public function test_true_values(): void
    {
        foreach (['1', 'true', 'TRUE', 'True', 'yes', 'YES', 'Yes'] as $v) {
            $this->setVar($v);
            self::assertTrue(Env::getBool(self::KEY), "value=[$v] should be true");
        }
    }

    public function test_false_values(): void
    {
        foreach (['0', 'false', 'FALSE', 'False', 'no', 'NO', 'No'] as $v) {
            $this->setVar($v);
            self::assertFalse(Env::getBool(self::KEY, true), "value=[$v] should be false");
        }
    }

    public function test_missing_uses_default(): void
    {
        $this->clearVar();
        self::assertFalse(Env::getBool(self::KEY));
        self::assertTrue(Env::getBool(self::KEY, true));
    }

    public function test_unrecognized_uses_default(): void
    {
        $this->setVar('maybe');
        self::assertTrue(Env::getBool(self::KEY, true));
        self::assertFalse(Env::getBool(self::KEY, false));
    }
}
