"""
sindico_cases.py — real PHP modification tasks against sistema-sindico.

Each case asks the model to ADD a new method to an existing src/Core class.
Existing tests must keep passing (no breaking changes). Scoring is by REAL
PHPUnit (vendor/bin/phpunit) on the full suite plus a HIDDEN test (never shown
to the model) that asserts the new method's behaviour across true AND false
states. Pass == entire suite green.
"""
from __future__ import annotations

from pathlib import Path

CASES = [
    {
        "id": "password_strength",
        "target": "src/Core/PasswordPolicy.php",
        "hidden_test": "PasswordStrengthTest.php",
        "goal": (
            "Add a NEW public static method `strength(string $password): string` "
            "to App\\Core\\PasswordPolicy that classifies the password as "
            "'weak', 'medium' or 'strong'."
        ),
        "criteria": (
            "- if `violations($password)` is not empty -> return 'weak'\n"
            "- otherwise, if `strlen($password) >= 12` AND the password contains "
            "at least one character from the set `!@#$%^&*` -> return 'strong'\n"
            "- otherwise -> return 'medium'\n"
            "- exact return values, lowercase: 'weak' | 'medium' | 'strong'"
        ),
        "constraints": (
            "- additive change: keep existing MIN_LENGTH, violations(), "
            "isValid(), describe() exactly as they are\n"
            "- pure function, no I/O\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "password_require_symbol",
        "target": "src/Core/PasswordPolicy.php",
        "hidden_test": "PasswordRequireSymbolTest.php",
        "goal": (
            "Add a NEW public static method "
            "`requireSymbol(string $password): array` to App\\Core\\PasswordPolicy "
            "that reports whether the password contains a symbol."
        ),
        "criteria": (
            "- returns `['symbol']` when the password lacks every character "
            "from the set `!@#$%^&*`\n"
            "- returns `[]` when at least one such symbol is present\n"
            "- empty string returns `['symbol']`"
        ),
        "constraints": (
            "- additive change: keep existing MIN_LENGTH, violations(), "
            "isValid(), describe() exactly as they are\n"
            "- pure function, no I/O\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "env_get_int",
        "target": "src/Core/Env.php",
        "hidden_test": "EnvGetIntTest.php",
        "goal": (
            "Add a NEW public static method "
            "`getInt(string $key, int $default = 0): int` to App\\Core\\Env "
            "that reads an environment variable and returns it as an integer."
        ),
        "criteria": (
            "- reads from `$_ENV[$key]` (falling back to `getenv($key)`)\n"
            "- returns the integer value when the env var is set AND is numeric "
            "(including negative integers like '-5')\n"
            "- returns `$default` when the env var is missing, empty, or non-numeric"
        ),
        "constraints": (
            "- additive change: keep the existing `load()` method and the "
            "global `env()` function exactly as they are\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "env_get_bool",
        "target": "src/Core/Env.php",
        "hidden_test": "EnvGetBoolTest.php",
        "goal": (
            "Add a NEW public static method "
            "`getBool(string $key, bool $default = false): bool` to "
            "App\\Core\\Env that reads an environment variable and parses it "
            "as a boolean."
        ),
        "criteria": (
            "- reads from `$_ENV[$key]` (falling back to `getenv($key)`)\n"
            "- case-insensitive: '1', 'true', 'yes' -> true\n"
            "- case-insensitive: '0', 'false', 'no' -> false\n"
            "- missing, empty, or unrecognized value -> `$default`"
        ),
        "constraints": (
            "- additive change: keep the existing `load()` method and the "
            "global `env()` function exactly as they are\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "admin_only_allowed_roles",
        "target": "src/Middleware/AdminOnly.php",
        "hidden_test": "AdminOnlyAllowedRolesTest.php",
        "goal": (
            "Add a NEW public static method `allowedRoles(): array` to "
            "App\\Middleware\\AdminOnly that returns the list of roles the "
            "middleware grants access to (the roles currently hardcoded in "
            "the existing handle() method)."
        ),
        "criteria": (
            "- returns exactly `['admin', 'sindico']`, in that order\n"
            "- callable statically as `AdminOnly::allowedRoles()`\n"
            "- public visibility"
        ),
        "constraints": (
            "- additive change: keep the existing handle() method unchanged\n"
            "- final class, namespace App\\Middleware, strict_types"
        ),
    },
    {
        "id": "rate_limit_bucket_key",
        "target": "src/Middleware/RateLimit.php",
        "hidden_test": "RateLimitBucketKeyTest.php",
        "goal": (
            "Add a NEW public static method "
            "`bucketKey(string $bucket, string $key): string` to "
            "App\\Middleware\\RateLimit that returns a normalized cache key."
        ),
        "criteria": (
            "- format: `'ratelimit:' + lowercase(bucket) + ':' + trim(key)`\n"
            "- bucketKey('login', 'user@example.com') -> "
            "'ratelimit:login:user@example.com'\n"
            "- bucketKey('VERIFY-CODE', '  user  ') -> "
            "'ratelimit:verify-code:user'\n"
            "- bucketKey('Login', \"\\tuser\\n\") -> 'ratelimit:login:user'"
        ),
        "constraints": (
            "- additive: keep existing enforce(), ipKey(), setStoreForTests() "
            "and private store() methods exactly as they are\n"
            "- final class, namespace App\\Middleware, strict_types"
        ),
    },
    {
        "id": "base_repository_build_where_sql",
        "target": "src/Repositories/BaseRepository.php",
        "hidden_test": "BaseRepositoryBuildWhereSqlTest.php",
        "goal": (
            "Add a NEW public static method "
            "`buildWhereSql(array $filters): array` to "
            "App\\Repositories\\BaseRepository that converts a filter map "
            "into a WHERE clause and bound parameters."
        ),
        "criteria": (
            "- returns `[$sql, $params]` where $sql is the WHERE clause "
            "WITHOUT the WHERE keyword and $params is an associative array "
            "of placeholder values\n"
            "- empty filters -> `['', []]`\n"
            "- `['name' => 'alice']` -> `['name = :name', ['name'=>'alice']]`\n"
            "- `['a'=>1, 'b'=>2]` -> `['a = :a AND b = :b', ['a'=>1,'b'=>2]]`\n"
            "- column names must match `/^[a-zA-Z_][a-zA-Z0-9_]*$/`; "
            "invalid column throws `InvalidArgumentException`"
        ),
        "constraints": (
            "- additive: keep the existing __construct, find(), all() and "
            "the private assertColumnName/sanitizeOrderBy helpers unchanged\n"
            "- abstract class, namespace App\\Repositories, strict_types\n"
            "- static method (no instance state needed)"
        ),
    },
    {
        "id": "router_has",
        "target": "src/Core/Router.php",
        "hidden_test": "RouterHasTest.php",
        "goal": (
            "Add a NEW public INSTANCE method "
            "`has(string $method, string $path): bool` to App\\Core\\Router "
            "that returns true iff at least one registered route has the "
            "same HTTP method AND a compiled regex that matches the given path."
        ),
        "criteria": (
            "- empty router: has('GET', '/x') -> false\n"
            "- after `$r->get('/api/health', ...)`: has('GET', '/api/health') "
            "-> true, has('POST', '/api/health') -> false\n"
            "- after `$r->get('/users/{id}', ...)`: has('GET', '/users/42') "
            "-> true (parameter routes match concrete paths)\n"
            "- has('GET', '/nonexistent') -> false"
        ),
        "constraints": (
            "- additive: keep get/post/put/patch/delete/group/dispatch and "
            "the private normalize/invoke/notFound helpers unchanged\n"
            "- INSTANCE method (uses $this->routes), not static\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    # ------------------------------------------------------------------------
    # Day-to-day style tasks (more PR-realistic than pure utility additions):
    # bug fix, method composition, repo SQL builder, router param extraction.
    # ------------------------------------------------------------------------
    {
        "id": "bugfix_password_policy_lowercase",
        "target": "src/Core/PasswordPolicy.php",
        "seed_content": (Path(__file__).parent / "sindico_hidden" /
                         "_seed_PasswordPolicy_bug.php").read_text(encoding="utf-8"),
        # No new hidden test: the existing PasswordPolicyTest must pass after the fix.
        "goal": (
            "There is a bug in `App\\Core\\PasswordPolicy::violations()`. The "
            "EXISTING test `tests/unit/Core/PasswordPolicyTest.php` is failing "
            "because `violations('SenhaForte123')` returns `['lowercase']` when "
            "it should return `[]`. Find the bug and fix it so the existing "
            "test passes."
        ),
        "criteria": (
            "- after the fix, `violations('SenhaForte123')` returns `[]`\n"
            "- the lowercase rule actually checks for lowercase letters (regex "
            "/[a-z]/), not uppercase\n"
            "- all other rules (min_length, uppercase, digit) keep their "
            "current behaviour"
        ),
        "constraints": (
            "- minimal fix: change ONLY the broken regex; do not refactor or "
            "rename anything\n"
            "- keep MIN_LENGTH, isValid(), describe() exactly as they are\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "password_assess",
        "target": "src/Core/PasswordPolicy.php",
        "hidden_test": "PasswordAssessTest.php",
        "goal": (
            "Add a NEW public static method `assess(string $password): array` "
            "to App\\Core\\PasswordPolicy that returns a summary report: "
            "`['valid' => bool, 'violations' => array, 'length' => int]`. "
            "It composes the existing API."
        ),
        "criteria": (
            "- result['valid'] mirrors `isValid($password)`\n"
            "- result['violations'] mirrors `violations($password)` (same "
            "array, same order)\n"
            "- result['length'] is `strlen($password)`\n"
            "- works for the empty string (returns invalid, length 0)"
        ),
        "constraints": (
            "- additive: keep MIN_LENGTH, violations(), isValid(), describe() "
            "exactly as they are; assess() must call the existing methods "
            "rather than re-implement them\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
    {
        "id": "base_repository_build_update_sql",
        "target": "src/Repositories/BaseRepository.php",
        "hidden_test": "BaseRepositoryBuildUpdateSqlTest.php",
        "goal": (
            "Add a NEW public static method "
            "`buildUpdateSql(string $table, int $id, array $set): array` to "
            "App\\Repositories\\BaseRepository that builds a parameterized "
            "UPDATE statement for a single row."
        ),
        "criteria": (
            "- returns `[$sql, $params]` where $sql is `'UPDATE <table> SET "
            "col1 = :col1, col2 = :col2 WHERE id = :id'` and $params is an "
            "associative array of `col => value` plus `'id' => $id`\n"
            "- `buildUpdateSql('users', 42, ['name'=>'alice','email'=>'a@b.com'])` "
            "-> `['UPDATE users SET name = :name, email = :email WHERE id = :id', "
            "['name'=>'alice','email'=>'a@b.com','id'=>42]]`\n"
            "- column names must match `/^[a-zA-Z_][a-zA-Z0-9_]*$/`; invalid "
            "column or empty $set throws `InvalidArgumentException`"
        ),
        "constraints": (
            "- additive: keep __construct, find(), all() and the private "
            "assertColumnName/sanitizeOrderBy helpers unchanged\n"
            "- static method (no instance state used)\n"
            "- abstract class, namespace App\\Repositories, strict_types"
        ),
    },
    {
        "id": "router_extract_params",
        "target": "src/Core/Router.php",
        "hidden_test": "RouterExtractParamsTest.php",
        "goal": (
            "Add a NEW public INSTANCE method "
            "`extractParams(string $pattern, string $path): ?array` to "
            "App\\Core\\Router that, given a route pattern like "
            "`/users/{id}/posts/{slug}` and a concrete path, returns an "
            "associative array of param-name -> captured value, or null if "
            "the path doesn't match the pattern."
        ),
        "criteria": (
            "- `extractParams('/users/{id}', '/users/42')` -> `['id' => '42']`\n"
            "- `extractParams('/posts/{id}/comments/{slug}', "
            "'/posts/7/comments/hello-world')` -> "
            "`['id' => '7', 'slug' => 'hello-world']`\n"
            "- pattern with no params: `extractParams('/health', '/health')` "
            "-> `[]` (empty array, NOT null)\n"
            "- mismatched path: returns `null`"
        ),
        "constraints": (
            "- additive: keep get/post/put/patch/delete/group/dispatch/has and "
            "the private helpers unchanged\n"
            "- INSTANCE method (may use the same regex-compilation pattern "
            "the existing `add()` uses internally), not static\n"
            "- final class, namespace App\\Core, strict_types"
        ),
    },
]


# ---------------------------------------------------------------------------
# Structural regex checks per task — used by run_fanout.py as a CHEAP shape
# check on every subagent's generated file (complement to the real PHPUnit
# functional scoring). Each list is a small set of patterns that SHOULD appear
# in a correct solution; a subagent's "regex score" is the fraction matched.
#
# The whole point of also reporting this metric is to compare it directly
# against the PHPUnit (functional) pass-rate: where they AGREE, regex is a
# cheap proxy; where they DISAGREE (regex says PASS but phpunit says FAIL),
# regex is a misleading metric and the criticism that "regex doesn't mean
# the code works" is correct.
# ---------------------------------------------------------------------------
REGEX_CHECKS_BY_TASK: dict[str, list[str]] = {
    "password_strength": [
        r"function\s+strength\s*\(",
        r"['\"]weak['\"]",
        r"['\"]medium['\"]",
        r"['\"]strong['\"]",
        r"violations\s*\(",
    ],
    "password_require_symbol": [
        r"function\s+requireSymbol\s*\(",
        r"\[!@#\$%\^&\*\]",
        r"['\"]symbol['\"]",
    ],
    "env_get_int": [
        r"function\s+getInt\s*\(",
        r"\$_ENV|getenv\s*\(",
        r"is_numeric|\(int\)|intval",
        r"\$default",
    ],
    "env_get_bool": [
        r"function\s+getBool\s*\(",
        r"\$_ENV|getenv\s*\(",
        r"strtolower",
        r"['\"]true['\"]|['\"]yes['\"]",
        r"['\"]false['\"]|['\"]no['\"]",
    ],
    "admin_only_allowed_roles": [
        r"function\s+allowedRoles\s*\(",
        r"\bstatic\b",
        r"['\"]admin['\"]",
        r"['\"]sindico['\"]",
        r"return\s+\[",
    ],
    "rate_limit_bucket_key": [
        r"function\s+bucketKey\s*\(",
        r"['\"]ratelimit:['\"]",
        r"strtolower",
        r"trim",
    ],
    "base_repository_build_where_sql": [
        r"function\s+buildWhereSql\s*\(",
        r"InvalidArgumentException",
        r"preg_match",
        r"implode",
    ],
    "router_has": [
        r"function\s+has\s*\(",
        r"\$this->routes",
        r"foreach",
        r"preg_match",
    ],
    "bugfix_password_policy_lowercase": [
        r"!\s*preg_match\s*\(\s*['\"]/?\[a-z\]/?['\"]",
        r"MIN_LENGTH",
        r"function\s+isValid",
        r"function\s+describe",
    ],
    "password_assess": [
        r"function\s+assess\s*\(",
        r"['\"]valid['\"]",
        r"['\"]violations['\"]",
        r"['\"]length['\"]",
        r"isValid|self::violations",
    ],
    "base_repository_build_update_sql": [
        r"function\s+buildUpdateSql\s*\(",
        r"\bUPDATE\b",
        r"WHERE\s+id",
        r"InvalidArgumentException",
        r"implode",
    ],
    "router_extract_params": [
        r"function\s+extractParams\s*\(",
        r"preg_match",
        r"\{[a-zA-Z_]|preg_replace_callback",
        r"\?\s*array|null",
    ],
}
