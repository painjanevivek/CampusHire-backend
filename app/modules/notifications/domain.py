from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    recipient_id: str
    event_key: str
    title: str
    deep_link: str


def deduplicate(notifications: list[Notification]) -> list[Notification]:
    seen: set[tuple[str, str]] = set()
    result: list[Notification] = []
    for item in notifications:
        key = (item.recipient_id, item.event_key)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def safe_deep_link(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise ValueError("Notification deep links must be local paths")
    return path
