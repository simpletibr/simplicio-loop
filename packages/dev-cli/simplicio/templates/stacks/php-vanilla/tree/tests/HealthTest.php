<?php

declare(strict_types=1);

namespace Tests;

use App\Health;
use PHPUnit\Framework\TestCase;

final class HealthTest extends TestCase
{
    public function testOk(): void
    {
        self::assertTrue((new Health())->ok());
    }
}
