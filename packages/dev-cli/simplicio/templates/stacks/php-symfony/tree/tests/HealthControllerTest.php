<?php

declare(strict_types=1);

namespace Tests;

use App\Controller\HealthController;
use PHPUnit\Framework\TestCase;

final class HealthControllerTest extends TestCase
{
    public function testHealth(): void
    {
        $response = (new HealthController())();

        self::assertSame(200, $response->getStatusCode());
        self::assertSame('{"ok":true}', $response->getContent());
    }
}
