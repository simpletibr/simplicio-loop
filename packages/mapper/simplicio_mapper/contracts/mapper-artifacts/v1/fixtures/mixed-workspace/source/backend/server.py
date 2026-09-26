"""Minimal backend server for mixed-workspace fixture."""


def handle_request(path: str) -> str:
    if path == "/health":
        return "ok"
    return "not found"


def main() -> None:
    print(handle_request("/health"))


if __name__ == "__main__":
    main()
