<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Repositories\BaseRepository;
use InvalidArgumentException;
use PHPUnit\Framework\TestCase;

final class BaseRepositoryBuildWhereSqlTest extends TestCase
{
    public function test_empty_filters_returns_empty(): void
    {
        self::assertSame(['', []], BaseRepository::buildWhereSql([]));
    }

    public function test_single_filter(): void
    {
        self::assertSame(
            ['name = :name', ['name' => 'alice']],
            BaseRepository::buildWhereSql(['name' => 'alice'])
        );
    }

    public function test_multiple_filters_anded(): void
    {
        self::assertSame(
            ['a = :a AND b = :b', ['a' => 1, 'b' => 2]],
            BaseRepository::buildWhereSql(['a' => 1, 'b' => 2])
        );
    }

    public function test_invalid_column_throws(): void
    {
        $this->expectException(InvalidArgumentException::class);
        BaseRepository::buildWhereSql(['1bad' => 'x']);
    }

    public function test_invalid_column_with_punctuation_throws(): void
    {
        $this->expectException(InvalidArgumentException::class);
        BaseRepository::buildWhereSql(['col; DROP' => 'x']);
    }

    public function test_is_static_public(): void
    {
        $rm = new \ReflectionMethod(BaseRepository::class, 'buildWhereSql');
        self::assertTrue($rm->isStatic());
        self::assertTrue($rm->isPublic());
    }
}
