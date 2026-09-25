<?php
declare(strict_types=1);

namespace Tests\Core\Hidden;

use App\Repositories\BaseRepository;
use InvalidArgumentException;
use PHPUnit\Framework\TestCase;

final class BaseRepositoryBuildUpdateSqlTest extends TestCase
{
    public function test_basic_update(): void
    {
        [$sql, $params] = BaseRepository::buildUpdateSql('users', 42, ['name' => 'alice', 'email' => 'a@b.com']);
        self::assertSame('UPDATE users SET name = :name, email = :email WHERE id = :id', $sql);
        self::assertSame(['name' => 'alice', 'email' => 'a@b.com', 'id' => 42], $params);
    }

    public function test_single_column(): void
    {
        [$sql, $params] = BaseRepository::buildUpdateSql('bookings', 7, ['status' => 'confirmed']);
        self::assertSame('UPDATE bookings SET status = :status WHERE id = :id', $sql);
        self::assertSame(['status' => 'confirmed', 'id' => 7], $params);
    }

    public function test_invalid_column_throws(): void
    {
        $this->expectException(InvalidArgumentException::class);
        BaseRepository::buildUpdateSql('users', 1, ['1bad' => 'x']);
    }

    public function test_invalid_column_with_punctuation_throws(): void
    {
        $this->expectException(InvalidArgumentException::class);
        BaseRepository::buildUpdateSql('users', 1, ['col; DROP' => 'x']);
    }

    public function test_empty_set_throws(): void
    {
        $this->expectException(InvalidArgumentException::class);
        BaseRepository::buildUpdateSql('users', 1, []);
    }
}
