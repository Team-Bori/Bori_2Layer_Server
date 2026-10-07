from dataclasses import dataclass


@dataclass
class PortLink:
    usb_slot: str
    serial_code: str
    online: bool


class PortRegistry:
    limit = 5

    def __init__(self) -> None:
        self._links: dict[str, PortLink] = {}

    def apply_scan(self, found: list[tuple[str, str]]) -> bool:
        found_map = dict(found)
        changed = False

        for slot, link in self._links.items():
            if link.online and slot not in found_map:
                link.online = False
                changed = True

        for slot, serial in sorted(found_map.items()):
            link = self._links.get(slot)
            if link is None:
                if len(self._links) >= self.limit:
                    continue
                self._links[slot] = PortLink(slot, serial, True)
                changed = True
                continue
            if link.serial_code != serial or not link.online:
                link.serial_code = serial
                link.online = True
                changed = True

        return changed

    def ports(self) -> list[PortLink]:
        return [self._links[slot] for slot in sorted(self._links)]
