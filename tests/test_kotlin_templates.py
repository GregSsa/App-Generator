from ai_android_app_generator.kotlin_templates import KotlinFileSpec, kotlin_string


def test_kotlin_file_spec_renders_package_sorted_imports_and_declarations() -> None:
    source = (
        KotlinFileSpec("com.example")
        .add_imports("z.Import", "a.Import")
        .add_declaration(
            """
            class Demo
            """
        )
        .render()
    )

    assert source == "package com.example\n\nimport a.Import\nimport z.Import\n\nclass Demo\n"


def test_kotlin_string_escapes_values() -> None:
    assert kotlin_string('Hello "Android"') == '"Hello \\"Android\\""'
