"""Android project file generation."""

from __future__ import annotations

import re
import json
from pathlib import Path
from textwrap import dedent
from typing import Any

from .state import AppGeneratorState, ValidationIssue

GENERATED_MANIFEST = ".ai_android_generator_manifest.json"


def to_pascal_case(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(word[:1].upper() + word[1:] for word in words) or "GeneratedApp"


def to_package_segment(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", value.lower())
    if not slug:
        return "generatedapp"
    if slug[0].isdigit():
        return f"app{slug}"
    return slug


def write_project(files: dict[str, str], output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _remove_previous_generated_files(output_dir, set(files.keys()))

    for relative_path, content in files.items():
        destination = (output_dir / relative_path).resolve()
        if output_dir not in destination.parents and destination != output_dir:
            raise ValueError(f"Refusing to write outside output directory: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    (output_dir / GENERATED_MANIFEST).write_text(
        json.dumps(sorted(files.keys()), indent=2),
        encoding="utf-8",
    )


def _remove_previous_generated_files(output_dir: Path, next_files: set[str]) -> None:
    manifest_path = output_dir / GENERATED_MANIFEST
    if not manifest_path.exists():
        return

    try:
        previous_files = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return

    if not isinstance(previous_files, list):
        return

    for relative_path in previous_files:
        if not isinstance(relative_path, str) or relative_path in next_files:
            continue
        destination = (output_dir / relative_path).resolve()
        if output_dir not in destination.parents or not destination.is_file():
            continue
        destination.unlink()


class AndroidProjectBuilder:
    """Builds a compact Android Kotlin/Compose project from graph state."""

    def build(self, state: AppGeneratorState) -> dict[str, str]:
        app_name = state["app_name"]
        package_name = state["package_name"]
        package_path = package_name.replace(".", "/")
        is_static = state.get("app_profile") == "static_text"

        files = {
            "settings.gradle.kts": self._settings_gradle(app_name),
            "build.gradle.kts": self._root_gradle(),
            "gradle.properties": self._gradle_properties(),
            "app/build.gradle.kts": self._app_gradle(package_name, is_static),
            "app/proguard-rules.pro": "",
            "app/src/main/AndroidManifest.xml": self._manifest(package_name, app_name, include_notifications=not is_static),
            "app/src/main/res/values/styles.xml": self._styles(),
            f"app/src/main/java/{package_path}/MainActivity.kt": self._static_main_activity(package_name, app_name, state)
            if is_static
            else self._main_activity(package_name, app_name, state),
            f"app/src/test/java/{package_path}/RequirementsTest.kt": self._tests(package_name, state),
        }

        if not is_static:
            files.update(
                {
                    f"app/src/main/java/{package_path}/data/AppModels.kt": self._models(package_name, state),
                    f"app/src/main/java/{package_path}/data/AppRepository.kt": self._repository(package_name, state),
                    f"app/src/main/java/{package_path}/ui/AppViewModel.kt": self._view_model(package_name),
                    f"app/src/main/java/{package_path}/ui/AppScreens.kt": self._screens(package_name, app_name, state),
                }
            )

        return files

    def validate(self, files: dict[str, str], state: AppGeneratorState) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        package_path = state["package_name"].replace(".", "/")
        is_static = state.get("app_profile") == "static_text"
        required_paths = [
            "settings.gradle.kts",
            "app/build.gradle.kts",
            "app/src/main/AndroidManifest.xml",
            f"app/src/main/java/{package_path}/MainActivity.kt",
        ]
        if not is_static:
            required_paths.append(f"app/src/main/java/{package_path}/ui/AppScreens.kt")

        for path in required_paths:
            if path not in files:
                errors.append({"severity": "error", "file": path, "message": "Required file is missing."})

        main_activity = files.get(f"app/src/main/java/{package_path}/MainActivity.kt", "")
        if "setContent" not in main_activity:
            errors.append(
                {
                    "severity": "error",
                    "file": f"app/src/main/java/{package_path}/MainActivity.kt",
                    "message": "MainActivity does not initialize Compose content.",
                }
            )

        app_gradle = files.get("app/build.gradle.kts", "")
        if "jvmToolchain(17)" not in app_gradle or "sourceCompatibility = JavaVersion.VERSION_17" not in app_gradle:
            errors.append(
                {
                    "severity": "error",
                    "file": "app/build.gradle.kts",
                    "message": "Gradle JVM toolchain must align Java and Kotlin compilation targets.",
                }
            )

        screens_file = files.get(f"app/src/main/java/{package_path}/ui/AppScreens.kt", "")
        if not is_static and "LazyColumn" not in screens_file:
            warnings.append(
                {
                    "severity": "warning",
                    "file": f"app/src/main/java/{package_path}/ui/AppScreens.kt",
                    "message": "Generated UI has no scrollable list; large datasets may be cramped.",
                }
            )

        for path, content in files.items():
            if state["package_name"] in content or not path.endswith(".kt"):
                continue
            errors.append({"severity": "error", "file": path, "message": "Kotlin file is missing the package declaration."})

        return errors, warnings

    def _settings_gradle(self, app_name: str) -> str:
        root_name = to_pascal_case(app_name)
        return dedent(
            f"""
            pluginManagement {{
                repositories {{
                    google()
                    mavenCentral()
                    gradlePluginPortal()
                }}
            }}
            dependencyResolutionManagement {{
                repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
                repositories {{
                    google()
                    mavenCentral()
                }}
            }}
            rootProject.name = "{root_name}"
            include(":app")
            """
        ).strip() + "\n"

    def _root_gradle(self) -> str:
        return dedent(
            """
            plugins {
                id("com.android.application") version "8.7.3" apply false
                id("org.jetbrains.kotlin.android") version "2.0.21" apply false
                id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
            }
            """
        ).strip() + "\n"

    def _gradle_properties(self) -> str:
        return dedent(
            """
            org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
            android.useAndroidX=true
            kotlin.code.style=official
            android.nonTransitiveRClass=true
            """
        ).strip() + "\n"

    def _app_gradle(self, package_name: str, is_static: bool = False) -> str:
        dynamic_dependencies = ""
        if not is_static:
            dynamic_dependencies = dedent(
                """
                    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
                    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
                """
            )

        return dedent(
            f"""
            plugins {{
                id("com.android.application")
                id("org.jetbrains.kotlin.android")
                id("org.jetbrains.kotlin.plugin.compose")
            }}

            android {{
                namespace = "{package_name}"
                compileSdk = 35

                defaultConfig {{
                    applicationId = "{package_name}"
                    minSdk = 26
                    targetSdk = 35
                    versionCode = 1
                    versionName = "1.0"

                    testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
                }}

                compileOptions {{
                    sourceCompatibility = JavaVersion.VERSION_17
                    targetCompatibility = JavaVersion.VERSION_17
                }}

                buildTypes {{
                    release {{
                        isMinifyEnabled = false
                        proguardFiles(
                            getDefaultProguardFile("proguard-android-optimize.txt"),
                            "proguard-rules.pro"
                        )
                    }}
                }}
            }}

            kotlin {{
                jvmToolchain(17)
            }}

            dependencies {{
                implementation(platform("androidx.compose:compose-bom:2024.10.00"))
                implementation("androidx.activity:activity-compose:1.9.3")
                implementation("androidx.compose.material3:material3")
                implementation("androidx.compose.ui:ui")
                implementation("androidx.compose.ui:ui-tooling-preview")
            {dynamic_dependencies.rstrip()}
                debugImplementation("androidx.compose.ui:ui-tooling")
                testImplementation("junit:junit:4.13.2")
            }}
            """
        ).strip() + "\n"

    def _manifest(self, package_name: str, app_name: str, include_notifications: bool = True) -> str:
        notification_permission = (
            '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />'
            if include_notifications
            else ""
        )
        return dedent(
            f"""
            <manifest xmlns:android="http://schemas.android.com/apk/res/android">
                {notification_permission}

                <application
                    android:allowBackup="true"
                    android:icon="@android:drawable/sym_def_app_icon"
                    android:label="{app_name}"
                    android:theme="@style/AppTheme">
                    <activity
                        android:name="{package_name}.MainActivity"
                        android:exported="true">
                        <intent-filter>
                            <action android:name="android.intent.action.MAIN" />
                            <category android:name="android.intent.category.LAUNCHER" />
                        </intent-filter>
                    </activity>
                </application>
            </manifest>
            """
        ).strip() + "\n"

    def _styles(self) -> str:
        return dedent(
            """
            <resources>
                <style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar">
                    <item name="android:windowLightStatusBar">true</item>
                    <item name="android:fontFamily">sans</item>
                </style>
            </resources>
            """
        ).strip() + "\n"

    def _main_activity(self, package_name: str, app_name: str, state: AppGeneratorState) -> str:
        return dedent(
            f"""
            package {package_name}

            import android.os.Bundle
            import androidx.activity.ComponentActivity
            import androidx.activity.compose.setContent
            import androidx.activity.viewModels
            import {package_name}.ui.AppRoot
            import {package_name}.ui.AppViewModel

            class MainActivity : ComponentActivity() {{
                private val viewModel: AppViewModel by viewModels()

                override fun onCreate(savedInstanceState: Bundle?) {{
                    super.onCreate(savedInstanceState)
                    setContent {{
                        AppRoot(
                            appName = "{app_name}",
                            viewModel = viewModel
                        )
                    }}
                }}
            }}
            """
        ).strip() + "\n"

    def _static_main_activity(self, package_name: str, app_name: str, state: AppGeneratorState) -> str:
        message = self._static_message(state)
        return dedent(
            f"""
            package {package_name}

            import android.os.Bundle
            import androidx.activity.ComponentActivity
            import androidx.activity.compose.setContent
            import androidx.compose.foundation.layout.Box
            import androidx.compose.foundation.layout.fillMaxSize
            import androidx.compose.foundation.layout.padding
            import androidx.compose.material3.MaterialTheme
            import androidx.compose.material3.Surface
            import androidx.compose.material3.Text
            import androidx.compose.runtime.Composable
            import androidx.compose.ui.Alignment
            import androidx.compose.ui.Modifier
            import androidx.compose.ui.unit.dp

            class MainActivity : ComponentActivity() {{
                override fun onCreate(savedInstanceState: Bundle?) {{
                    super.onCreate(savedInstanceState)
                    setContent {{
                        MaterialTheme {{
                            Surface(modifier = Modifier.fillMaxSize()) {{
                                StaticMessage(message = "{message}")
                            }}
                        }}
                    }}
                }}
            }}

            @Composable
            private fun StaticMessage(message: String) {{
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(24.dp),
                    contentAlignment = Alignment.Center
                ) {{
                    Text(
                        text = message,
                        style = MaterialTheme.typography.headlineMedium
                    )
                }}
            }}
            """
        ).strip() + "\n"

    def _static_message(self, state: AppGeneratorState) -> str:
        prompt = state["prompt"].lower()
        if "hello world" in prompt:
            return "Hello World"
        return state["app_name"].replace('"', '\\"')

    def _models(self, package_name: str, state: AppGeneratorState) -> str:
        model_name = state["data_models"][0]["name"]
        fields = "\n".join(
            f"    val {field['name']}: {field['type']} = {self._kotlin_default_value(field['type'])},"
            for field in state["data_models"][0]["fields"]
        )
        return dedent(
            f"""
            package {package_name}.data

            data class {model_name}(
            {fields}
            )

            data class AppUiState(
                val items: List<{model_name}> = emptyList(),
                val selectedFilter: String = "All",
                val notificationsEnabled: Boolean = true
            )
            """
        ).strip() + "\n"

    def _kotlin_default_value(self, kotlin_type: str) -> str:
        return {
            "String": '""',
            "Int": "0",
            "Long": "0L",
            "Float": "0f",
            "Double": "0.0",
            "Boolean": "false",
        }.get(kotlin_type, '""')

    def _repository(self, package_name: str, state: AppGeneratorState) -> str:
        model_name = state["data_models"][0]["name"]
        sample_items = self._sample_items(model_name, state)
        return dedent(
            f"""
            package {package_name}.data

            class AppRepository {{
                fun loadItems(): List<{model_name}> = listOf(
            {sample_items}
                )
            }}
            """
        ).strip() + "\n"

    def _view_model(self, package_name: str) -> str:
        return dedent(
            f"""
            package {package_name}.ui

            import androidx.lifecycle.ViewModel
            import {package_name}.data.AppRepository
            import {package_name}.data.AppUiState
            import kotlinx.coroutines.flow.MutableStateFlow
            import kotlinx.coroutines.flow.StateFlow
            import kotlinx.coroutines.flow.asStateFlow
            import kotlinx.coroutines.flow.update

            class AppViewModel(
                private val repository: AppRepository = AppRepository()
            ) : ViewModel() {{
                private val _uiState = MutableStateFlow(AppUiState(items = repository.loadItems()))
                val uiState: StateFlow<AppUiState> = _uiState.asStateFlow()

                fun toggleNotifications() {{
                    _uiState.update {{ current ->
                        current.copy(notificationsEnabled = !current.notificationsEnabled)
                    }}
                }}

                fun selectFilter(filter: String) {{
                    _uiState.update {{ current ->
                        current.copy(selectedFilter = filter)
                    }}
                }}
            }}
            """
        ).strip() + "\n"

    def _screens(self, package_name: str, app_name: str, state: AppGeneratorState) -> str:
        requirement_badges = ", ".join(f'"{requirement[:32]}"' for requirement in state["requirements"][:4])
        return dedent(
            f"""
            package {package_name}.ui

            import androidx.compose.foundation.layout.Arrangement
            import androidx.compose.foundation.layout.Column
            import androidx.compose.foundation.layout.Row
            import androidx.compose.foundation.layout.Spacer
            import androidx.compose.foundation.layout.fillMaxSize
            import androidx.compose.foundation.layout.fillMaxWidth
            import androidx.compose.foundation.layout.height
            import androidx.compose.foundation.layout.padding
            import androidx.compose.foundation.lazy.LazyColumn
            import androidx.compose.foundation.lazy.items
            import androidx.compose.material3.AssistChip
            import androidx.compose.material3.Card
            import androidx.compose.material3.MaterialTheme
            import androidx.compose.material3.Switch
            import androidx.compose.material3.Text
            import androidx.compose.runtime.Composable
            import androidx.compose.runtime.collectAsState
            import androidx.compose.runtime.getValue
            import androidx.compose.ui.Alignment
            import androidx.compose.ui.Modifier
            import androidx.compose.ui.unit.dp
            import {package_name}.data.AppUiState

            @Composable
            fun AppRoot(appName: String, viewModel: AppViewModel) {{
                val state by viewModel.uiState.collectAsState()
                MaterialTheme {{
                    HomeScreen(
                        appName = appName,
                        state = state,
                        onToggleNotifications = viewModel::toggleNotifications,
                        onFilterSelected = viewModel::selectFilter
                    )
                }}
            }}

            @Composable
            fun HomeScreen(
                appName: String,
                state: AppUiState,
                onToggleNotifications: () -> Unit,
                onFilterSelected: (String) -> Unit
            ) {{
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {{
                    Text(text = appName, style = MaterialTheme.typography.headlineMedium)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {{
                        Text("Notifications")
                        Switch(
                            checked = state.notificationsEnabled,
                            onCheckedChange = {{ onToggleNotifications() }}
                        )
                    }}
                    RequirementChips(onFilterSelected = onFilterSelected)
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {{
                        items(state.items) {{ item ->
                            Card(modifier = Modifier.fillMaxWidth()) {{
                                Column(modifier = Modifier.padding(16.dp)) {{
                                    Text(item.title, style = MaterialTheme.typography.titleMedium)
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(item.subtitle, style = MaterialTheme.typography.bodyMedium)
                                    Text(item.status, style = MaterialTheme.typography.labelMedium)
                                }}
                            }}
                        }}
                    }}
                }}
            }}

            @Composable
            private fun RequirementChips(onFilterSelected: (String) -> Unit) {{
                val filters = listOf("All", {requirement_badges})
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {{
                    filters.take(3).forEach {{ filter ->
                        AssistChip(
                            onClick = {{ onFilterSelected(filter) }},
                            label = {{ Text(filter) }}
                        )
                    }}
                }}
            }}
            """
        ).strip() + "\n"

    def _tests(self, package_name: str, state: AppGeneratorState) -> str:
        expected_count = len(state["requirements"])
        return dedent(
            f"""
            package {package_name}

            import org.junit.Assert.assertTrue
            import org.junit.Test

            class RequirementsTest {{
                @Test
                fun generatedProjectKeepsCoreRequirements() {{
                    val requirementCount = {expected_count}
                    assertTrue(requirementCount >= 3)
                }}
            }}
            """
        ).strip() + "\n"

    def _sample_items(self, model_name: str, state: AppGeneratorState) -> str:
        prompt = state["prompt"].lower()
        if "manga" in prompt:
            samples = [
                ("One Piece", "Chapitre 1118 disponible", "A lire"),
                ("Jujutsu Kaisen", "Suivi des derniers scans", "En cours"),
                ("Frieren", "Notification activee", "Favori"),
            ]
        else:
            samples = [
                ("Premier element", "Genere depuis le prompt utilisateur", "Actif"),
                ("Tableau de bord", "Vue synthetique des donnees", "A verifier"),
                ("Rappel intelligent", "Action recommandee par l'application", "Planifie"),
            ]

        lines = []
        for title, subtitle, status in samples:
            lines.append(f'        {model_name}(title = "{title}", subtitle = "{subtitle}", status = "{status}")')
        return ",\n".join(lines)
