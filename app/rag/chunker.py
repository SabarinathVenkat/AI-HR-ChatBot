"""Split policy Markdown into citable chunks: one per '##' section."""
import re
from dataclasses import dataclass
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SECTION_HEADING = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
CLAUSE_START = re.compile(r"^(\d+\.\d+)\s", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    policy_id: str
    policy_title: str
    version: str
    effective_date: str
    section_id: str
    title: str
    text: str
    clause_ids: tuple[str, ...]


def _parse_front_matter(raw: str) -> dict[str, str]:
    fields = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def chunk_policy_text(text: str) -> list[Chunk]:
    match = FRONT_MATTER.match(text)
    if match is None:
        raise ValueError("Not a policy file: missing front matter.")
    meta = _parse_front_matter(match.group(1))
    body = text[match.end():]
    policy_id = meta["policy_id"]

    headings = list(SECTION_HEADING.finditer(body))
    chunks = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section_text = body[heading.start():end].strip()
        number = heading.group(1)
        clause_ids = tuple(
            f"{policy_id} §{clause}" for clause in CLAUSE_START.findall(section_text)
        )
        chunks.append(
            Chunk(
                policy_id=policy_id,
                policy_title=meta["title"],
                version=meta["version"],
                effective_date=meta["effective_date"],
                section_id=f"{policy_id} §{number}",
                title=heading.group(2),
                text=section_text,
                clause_ids=clause_ids,
            )
        )
    return chunks


def load_policy_dir(directory: Path) -> list[Chunk]:
    """Chunk every policy file in a directory. Files without front matter (README) are skipped."""
    chunks: list[Chunk] = []
    for path in sorted(Path(directory).glob("*.md")):
        try:
            chunks.extend(chunk_policy_text(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return chunks
