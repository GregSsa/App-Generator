"""Small Kotlin source templates inspired by KotlinPoet's FileSpec style."""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent


@dataclass
class KotlinFileSpec:
    package_name: str
    imports: set[str] = field(default_factory=set)
    declarations: list[str] = field(default_factory=list)

    def add_imports(self, *imports: str) -> "KotlinFileSpec":
        self.imports.update(import_path for import_path in imports if import_path)
        return self

    def add_declaration(self, declaration: str) -> "KotlinFileSpec":
        self.declarations.append(dedent(declaration).strip())
        return self

    def render(self) -> str:
        chunks = [f"package {self.package_name}"]
        if self.imports:
            chunks.append("\n".join(f"import {import_path}" for import_path in sorted(self.imports)))
        chunks.extend(self.declarations)
        return "\n\n".join(chunks).strip() + "\n"


def kotlin_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
