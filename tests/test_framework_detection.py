"""Tests for framework detection: path-based and AST-based heuristics.

Covers:
- FrameworkHint frozen dataclass (creation, equality, immutability, hashing)
- detect_framework_from_path() for 15+ frameworks/ecosystems
- detect_framework_from_ast() for decorator/annotation-based detection
- FRAMEWORK_AST_PATTERNS dict completeness
- Edge cases (empty strings, Windows paths, very long paths)

Ported from Qode ``framework-detection.test.ts`` with additional
Python-specific and extended coverage for Kotlin, Laravel, Swift, Go,
Rust, C/C++, and AST edge cases.
"""

import dataclasses

import pytest

from qode.core.framework_detection import (
    FRAMEWORK_AST_PATTERNS,
    FrameworkHint,
    detect_framework_from_ast,
    detect_framework_from_path,
)

# ---------------------------------------------------------------------------
# 1. FrameworkHint dataclass
# ---------------------------------------------------------------------------


class TestFrameworkHint:
    """Tests for the FrameworkHint frozen dataclass."""

    def test_creation(self):
        hint = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="django-view",
        )
        assert hint.framework == "django"
        assert hint.entry_point_multiplier == 3.0
        assert hint.reason == "django-view"

    def test_frozen_immutability_framework(self):
        hint = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            hint.framework = "fastapi"  # type: ignore[misc]

    def test_frozen_immutability_multiplier(self):
        hint = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            hint.entry_point_multiplier = 9.0  # type: ignore[misc]

    def test_frozen_immutability_reason(self):
        hint = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            hint.reason = "changed"  # type: ignore[misc]

    def test_equality_same_values(self):
        a = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="view",
        )
        b = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="view",
        )
        assert a == b

    def test_inequality_different_framework(self):
        a = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="view",
        )
        b = FrameworkHint(
            framework="flask",
            entry_point_multiplier=3.0,
            reason="view",
        )
        assert a != b

    def test_inequality_different_multiplier(self):
        a = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="view",
        )
        b = FrameworkHint(
            framework="django",
            entry_point_multiplier=2.0,
            reason="view",
        )
        assert a != b

    def test_inequality_different_reason(self):
        a = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="view",
        )
        b = FrameworkHint(
            framework="django",
            entry_point_multiplier=3.0,
            reason="url",
        )
        assert a != b

    def test_hashable(self):
        hint = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        s = {hint}
        assert hint in s
        d = {hint: 42}
        assert d[hint] == 42

    def test_hash_equality_consistent(self):
        a = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        b = FrameworkHint(
            framework="express",
            entry_point_multiplier=2.5,
            reason="route",
        )
        assert hash(a) == hash(b)

    def test_repr(self):
        hint = FrameworkHint(
            framework="spring",
            entry_point_multiplier=2.5,
            reason="ctrl",
        )
        r = repr(hint)
        assert "FrameworkHint" in r
        assert "spring" in r

    def test_is_dataclass(self):
        hint = FrameworkHint(
            framework="x",
            entry_point_multiplier=1.0,
            reason="y",
        )
        assert dataclasses.is_dataclass(hint)


# ---------------------------------------------------------------------------
# 2. detect_framework_from_path — Next.js
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathNextjs:
    """Next.js Pages Router, App Router, API routes, layouts."""

    def test_detects_pages_router_pages(self):
        result = detect_framework_from_path("pages/users.tsx")
        assert result is not None
        assert result.framework == "nextjs-pages"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "nextjs-page"

    def test_ignores_underscore_app(self):
        assert detect_framework_from_path("pages/_app.tsx") is None

    def test_ignores_underscore_document(self):
        result = detect_framework_from_path("pages/_document.tsx")
        assert result is None

    def test_detects_app_router_page_tsx(self):
        result = detect_framework_from_path("app/dashboard/page.tsx")
        assert result is not None
        assert result.framework == "nextjs-app"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "nextjs-app-page"

    def test_detects_app_router_page_jsx(self):
        result = detect_framework_from_path("app/page.jsx")
        assert result is not None
        assert result.framework == "nextjs-app"
        assert result.entry_point_multiplier == 3.0

    def test_detects_api_routes_in_pages(self):
        result = detect_framework_from_path("pages/api/users.ts")
        assert result is not None
        assert result.framework == "nextjs-api"
        assert result.entry_point_multiplier == 3.0

    def test_detects_app_router_api_route_ts(self):
        result = detect_framework_from_path("app/api/users/route.ts")
        assert result is not None
        assert result.framework == "nextjs-api"
        assert result.entry_point_multiplier == 3.0

    def test_detects_layout_files(self):
        result = detect_framework_from_path("app/layout.tsx")
        assert result is not None
        assert result.framework == "nextjs-app"
        assert result.entry_point_multiplier == 2.0
        assert result.reason == "nextjs-layout"

    def test_detects_nested_layout(self):
        result = detect_framework_from_path("app/dashboard/layout.tsx")
        assert result is not None
        assert result.framework == "nextjs-app"
        assert result.entry_point_multiplier == 2.0

    def test_detects_pages_router_nested(self):
        result = detect_framework_from_path("pages/blog/[slug].tsx")
        assert result is not None
        assert result.framework == "nextjs-pages"
        assert result.entry_point_multiplier == 3.0

    def test_detects_pages_router_js_extension(self):
        result = detect_framework_from_path("pages/about.js")
        assert result is not None
        assert result.framework == "nextjs-pages"

    def test_detects_pages_router_ts_extension(self):
        result = detect_framework_from_path("pages/about.ts")
        assert result is not None
        assert result.framework == "nextjs-pages"

    def test_detects_app_router_page_ts(self):
        result = detect_framework_from_path("app/page.ts")
        assert result is not None
        assert result.framework == "nextjs-app"

    def test_detects_app_router_page_js(self):
        result = detect_framework_from_path("app/page.js")
        assert result is not None
        assert result.framework == "nextjs-app"

    def test_detects_layout_ts_variant(self):
        result = detect_framework_from_path("app/layout.ts")
        assert result is not None
        assert result.framework == "nextjs-app"
        assert result.entry_point_multiplier == 2.0

    def test_pages_api_js_extension(self):
        result = detect_framework_from_path("pages/api/health.js")
        assert result is not None
        assert result.framework == "nextjs-api"


# ---------------------------------------------------------------------------
# 3. detect_framework_from_path — Express / Node.js
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathExpress:
    """Express route files."""

    def test_detects_route_files(self):
        result = detect_framework_from_path("routes/auth.ts")
        assert result is not None
        assert result.framework == "express"
        assert result.entry_point_multiplier == 2.5

    def test_detects_nested_route_files(self):
        result = detect_framework_from_path("src/routes/users.js")
        assert result is not None
        assert result.framework == "express"
        assert result.entry_point_multiplier == 2.5


# ---------------------------------------------------------------------------
# 4. detect_framework_from_path — MVC controllers / handlers
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathMvc:
    """MVC controllers and handlers folders."""

    def test_detects_controller_folder(self):
        result = detect_framework_from_path("controllers/UserController.ts")
        assert result is not None
        assert result.framework == "mvc"
        assert result.entry_point_multiplier == 2.5

    def test_detects_handlers_folder(self):
        result = detect_framework_from_path("handlers/auth.ts")
        assert result is not None
        assert result.framework == "handlers"
        assert result.entry_point_multiplier == 2.5

    def test_detects_nested_controllers(self):
        result = detect_framework_from_path("src/controllers/orders.ts")
        assert result is not None
        assert result.framework == "mvc"
        assert result.entry_point_multiplier == 2.5


# ---------------------------------------------------------------------------
# 5. detect_framework_from_path — React
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathReact:
    """React component detection — preserves the path-lowercasing bug."""

    def test_views_folder_with_pascal_case_returns_none(self):
        """Path is lowercased before PascalCase regex check,
        so it never matches."""
        result = detect_framework_from_path("views/Button.tsx")
        assert result is None

    def test_components_folder_with_pascal_case_returns_none(self):
        result = detect_framework_from_path("components/Header.tsx")
        assert result is None


# ---------------------------------------------------------------------------
# 6. detect_framework_from_path — Python frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathPython:
    """Django, FastAPI, generic Python patterns."""

    def test_detects_django_views(self):
        result = detect_framework_from_path("myapp/views.py")
        assert result is not None
        assert result.framework == "django"
        assert result.entry_point_multiplier == 3.0

    def test_detects_django_urls(self):
        result = detect_framework_from_path("myapp/urls.py")
        assert result is not None
        assert result.framework == "django"
        assert result.entry_point_multiplier == 2.0

    def test_detects_fastapi_routers(self):
        result = detect_framework_from_path("routers/users.py")
        assert result is not None
        assert result.framework == "fastapi"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "api-routers"

    def test_detects_python_api_folder(self):
        result = detect_framework_from_path("api/endpoints.py")
        assert result is not None
        assert result.framework == "python-api"
        assert result.entry_point_multiplier == 2.0
        assert result.reason == "api-folder"

    def test_api_init_py_excluded_from_python_api(self):
        """__init__.py in api folder is excluded from python-api
        rule (impl line 126) but still matches the generic
        api-index rule (impl line 316-319)."""
        result = detect_framework_from_path("api/__init__.py")
        assert result is not None
        assert result.framework == "api"
        assert result.reason == "api-index"

    def test_detects_endpoints_folder(self):
        result = detect_framework_from_path("endpoints/users.py")
        assert result is not None
        assert result.framework == "fastapi"
        assert result.reason == "api-routers"

    def test_detects_routes_py_folder(self):
        result = detect_framework_from_path("routes/api.py")
        assert result is not None
        assert result.framework == "fastapi"
        assert result.reason == "api-routers"


# ---------------------------------------------------------------------------
# 7. detect_framework_from_path — Java frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathJava:
    """Spring, Java service layer."""

    def test_detects_spring_controllers_folder(self):
        result = detect_framework_from_path("controller/UserController.java")
        assert result is not None
        assert result.framework == "spring"
        assert result.entry_point_multiplier == 3.0

    def test_detects_spring_controller_by_filename(self):
        result = detect_framework_from_path("src/UserController.java")
        assert result is not None
        assert result.framework == "spring"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "spring-controller-file"

    def test_detects_java_service_layer(self):
        result = detect_framework_from_path("service/UserService.java")
        assert result is not None
        assert result.framework == "java-service"
        assert result.entry_point_multiplier == 1.8

    def test_detects_spring_controllers_plural_folder(self):
        result = detect_framework_from_path("controllers/OrderController.java")
        assert result is not None
        assert result.framework == "spring"
        assert result.entry_point_multiplier == 3.0

    def test_detects_java_services_plural_folder(self):
        result = detect_framework_from_path("services/PaymentService.java")
        assert result is not None
        assert result.framework == "java-service"
        assert result.entry_point_multiplier == 1.8


# ---------------------------------------------------------------------------
# 8. detect_framework_from_path — Kotlin frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathKotlin:
    """Ktor, Android, Spring-Kotlin."""

    def test_detects_ktor_routes(self):
        result = detect_framework_from_path("routes/UserRoutes.kt")
        assert result is not None
        assert result.framework == "ktor"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "ktor-routes"

    def test_detects_android_activity(self):
        result = detect_framework_from_path("ui/MainActivity.kt")
        assert result is not None
        assert result.framework == "android-kotlin"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "android-ui"

    def test_detects_spring_kotlin_controller(self):
        result = detect_framework_from_path("controller/UserController.kt")
        assert result is not None
        assert result.framework == "spring-kotlin"
        assert result.entry_point_multiplier == 3.0

    def test_detects_android_fragment(self):
        result = detect_framework_from_path("ui/HomeFragment.kt")
        assert result is not None
        assert result.framework == "android-kotlin"
        assert result.entry_point_multiplier == 2.5

    def test_detects_kotlin_main(self):
        result = detect_framework_from_path("src/main.kt")
        assert result is not None
        assert result.framework == "kotlin"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "kotlin-main"

    def test_detects_kotlin_application(self):
        result = detect_framework_from_path("src/application.kt")
        assert result is not None
        assert result.framework == "kotlin"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "kotlin-application"

    def test_detects_ktor_plugins(self):
        result = detect_framework_from_path("plugins/Routing.kt")
        assert result is not None
        assert result.framework == "ktor"
        assert result.entry_point_multiplier == 2.0
        assert result.reason == "ktor-plugin"

    def test_detects_ktor_routing_file(self):
        result = detect_framework_from_path("src/Routing.kt")
        assert result is not None
        assert result.framework == "ktor"
        assert result.reason == "ktor-routing-file"

    def test_detects_android_activity_folder(self):
        """Tests /activity/ directory (not just /ui/)."""
        result = detect_framework_from_path("activity/LoginActivity.kt")
        assert result is not None
        assert result.framework == "android-kotlin"
        assert result.reason == "android-ui"

    def test_detects_android_activity_by_filename(self):
        """activity.kt suffix without /ui/ or /activity/ dir."""
        result = detect_framework_from_path("src/SomeActivity.kt")
        assert result is not None
        assert result.framework == "android-kotlin"
        assert result.reason == "android-component"

    def test_detects_spring_kotlin_controller_by_filename(self):
        """Controller.kt file not in /controller/ directory."""
        result = detect_framework_from_path("src/UserController.kt")
        assert result is not None
        assert result.framework == "spring-kotlin"
        assert result.reason == "spring-kotlin-controller-file"


# ---------------------------------------------------------------------------
# 9. detect_framework_from_path — C# / .NET
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathCsharp:
    """ASP.NET controllers, Blazor pages."""

    def test_detects_aspnet_controllers(self):
        result = detect_framework_from_path("controllers/UsersController.cs")
        assert result is not None
        assert result.framework == "aspnet"
        assert result.entry_point_multiplier == 3.0

    def test_detects_blazor_pages(self):
        result = detect_framework_from_path("pages/Index.razor")
        assert result is not None
        assert result.framework == "blazor"
        assert result.entry_point_multiplier == 2.5

    def test_detects_aspnet_controller_by_filename(self):
        result = detect_framework_from_path("src/UsersController.cs")
        assert result is not None
        assert result.framework == "aspnet"
        assert result.entry_point_multiplier == 3.0


# ---------------------------------------------------------------------------
# 10. detect_framework_from_path — Go frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathGo:
    """Go handlers, main.go, routes, controllers."""

    def test_detects_go_handlers(self):
        result = detect_framework_from_path("handlers/user.go")
        assert result is not None
        assert result.framework == "go-http"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "go-handlers"

    def test_detects_go_main(self):
        result = detect_framework_from_path("cmd/server/main.go")
        assert result is not None
        assert result.framework == "go"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "go-main"

    def test_detects_go_routes(self):
        result = detect_framework_from_path("routes/api.go")
        assert result is not None
        assert result.framework == "go-http"
        assert result.entry_point_multiplier == 2.5

    def test_detects_go_controllers(self):
        result = detect_framework_from_path("controllers/user.go")
        assert result is not None
        assert result.framework == "go-mvc"
        assert result.entry_point_multiplier == 2.5

    def test_detects_go_main_in_root(self):
        result = detect_framework_from_path("main.go")
        assert result is not None
        assert result.framework == "go"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "go-main"

    def test_detects_go_handler_singular(self):
        """Tests /handler/ (singular) directory."""
        result = detect_framework_from_path("handler/auth.go")
        assert result is not None
        assert result.framework == "go-http"
        assert result.reason == "go-handlers"

    def test_detects_go_cmd_subdir(self):
        """Tests /cmd/ subdirectory with non-main.go file."""
        result = detect_framework_from_path("cmd/server/app.go")
        assert result is not None
        assert result.framework == "go"
        assert result.entry_point_multiplier == 3.0


# ---------------------------------------------------------------------------
# 11. detect_framework_from_path — Rust frameworks
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathRust:
    """Rust handlers, main.rs, bin folder."""

    def test_detects_rust_handlers(self):
        result = detect_framework_from_path("handlers/auth.rs")
        assert result is not None
        assert result.framework == "rust-web"
        assert result.entry_point_multiplier == 2.5

    def test_detects_main_rs(self):
        result = detect_framework_from_path("src/main.rs")
        assert result is not None
        assert result.framework == "rust"
        assert result.entry_point_multiplier == 3.0

    def test_detects_bin_folder(self):
        result = detect_framework_from_path("src/bin/cli.rs")
        assert result is not None
        assert result.framework == "rust"
        assert result.entry_point_multiplier == 2.5

    def test_detects_rust_routes(self):
        result = detect_framework_from_path("src/routes/mod.rs")
        assert result is not None
        assert result.framework == "rust-web"
        assert result.entry_point_multiplier == 2.5


# ---------------------------------------------------------------------------
# 12. detect_framework_from_path — C / C++
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathCCpp:
    """C and C++ main files and app files."""

    def test_detects_main_c(self):
        result = detect_framework_from_path("src/main.c")
        assert result is not None
        assert result.framework == "c-cpp"
        assert result.entry_point_multiplier == 3.0

    def test_detects_main_cpp(self):
        result = detect_framework_from_path("src/main.cpp")
        assert result is not None
        assert result.framework == "c-cpp"
        assert result.entry_point_multiplier == 3.0

    def test_detects_main_cc(self):
        result = detect_framework_from_path("src/main.cc")
        assert result is not None
        assert result.framework == "c-cpp"
        assert result.entry_point_multiplier == 3.0

    def test_detects_app_c(self):
        result = detect_framework_from_path("src/app.c")
        assert result is not None
        assert result.framework == "c-cpp"
        assert result.entry_point_multiplier == 2.5

    def test_detects_app_cpp(self):
        result = detect_framework_from_path("src/app.cpp")
        assert result is not None
        assert result.framework == "c-cpp"
        assert result.entry_point_multiplier == 2.5


# ---------------------------------------------------------------------------
# 13. detect_framework_from_path — PHP / Laravel
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathLaravel:
    """Laravel routes, controllers, jobs, middleware, models, etc."""

    def test_detects_laravel_routes(self):
        result = detect_framework_from_path("routes/web.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 3.0

    def test_detects_laravel_controllers(self):
        result = detect_framework_from_path("http/controllers/UserController.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 3.0

    def test_detects_laravel_jobs(self):
        result = detect_framework_from_path("jobs/SendEmail.php")
        assert result is not None
        assert result.reason == "laravel-job"

    def test_detects_laravel_middleware(self):
        result = detect_framework_from_path("http/middleware/Auth.php")
        assert result is not None
        assert result.reason == "laravel-middleware"

    def test_detects_laravel_models(self):
        result = detect_framework_from_path("models/User.php")
        assert result is not None
        assert result.entry_point_multiplier == 1.5

    def test_detects_laravel_commands(self):
        result = detect_framework_from_path("console/commands/MigrateData.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 2.5

    def test_detects_laravel_listeners(self):
        result = detect_framework_from_path("listeners/SendWelcomeEmail.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 2.5

    def test_detects_laravel_providers(self):
        result = detect_framework_from_path("providers/AppServiceProvider.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 1.8

    def test_detects_laravel_policies(self):
        result = detect_framework_from_path("policies/PostPolicy.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 2.0

    def test_detects_laravel_services(self):
        result = detect_framework_from_path("services/PaymentService.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 1.8
        assert result.reason == "laravel-service"

    def test_detects_laravel_repositories(self):
        result = detect_framework_from_path("repositories/UserRepository.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 1.5
        assert result.reason == "laravel-repository"

    def test_detects_laravel_api_routes(self):
        result = detect_framework_from_path("routes/api.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.entry_point_multiplier == 3.0

    def test_detects_laravel_controllers_without_http(self):
        """Tests /controllers/ + .php without /http/ prefix."""
        result = detect_framework_from_path("controllers/OrderController.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.reason == "laravel-controller"

    def test_detects_laravel_commands_without_console(self):
        """Tests /commands/ + .php without /console/ prefix."""
        result = detect_framework_from_path("commands/ImportData.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.reason == "laravel-command"

    def test_detects_laravel_controller_by_filename(self):
        """Tests controller.php suffix detection."""
        result = detect_framework_from_path("src/UserController.php")
        assert result is not None
        assert result.framework == "laravel"
        assert result.reason == "laravel-controller-file"


# ---------------------------------------------------------------------------
# 14. detect_framework_from_path — Swift / iOS
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathSwift:
    """AppDelegate, ViewControllers, Coordinators, SwiftUI, etc."""

    def test_detects_app_delegate(self):
        result = detect_framework_from_path("Sources/AppDelegate.swift")
        assert result is not None
        assert result.framework == "ios"
        assert result.entry_point_multiplier == 3.0

    def test_detects_viewcontrollers_folder(self):
        result = detect_framework_from_path("ViewControllers/LoginVC.swift")
        assert result is not None
        assert result.framework == "uikit"
        assert result.entry_point_multiplier == 2.5

    def test_detects_coordinator_pattern(self):
        result = detect_framework_from_path("Coordinators/AppCoordinator.swift")
        assert result is not None
        assert result.framework == "ios-coordinator"
        assert result.entry_point_multiplier == 2.5

    def test_detects_swiftui_views_folder(self):
        result = detect_framework_from_path("views/ContentView.swift")
        assert result is not None
        assert result.framework == "swiftui"
        assert result.entry_point_multiplier == 1.8

    def test_detects_scene_delegate(self):
        result = detect_framework_from_path("Sources/SceneDelegate.swift")
        assert result is not None
        assert result.framework == "ios"
        assert result.entry_point_multiplier == 3.0

    def test_detects_coordinator_by_filename(self):
        result = detect_framework_from_path("src/MainCoordinator.swift")
        assert result is not None
        assert result.framework == "ios-coordinator"
        assert result.entry_point_multiplier == 2.5
        assert result.reason == "ios-coordinator-file"

    def test_detects_swift_service_layer(self):
        result = detect_framework_from_path("services/NetworkService.swift")
        assert result is not None
        assert result.framework == "ios-service"
        assert result.entry_point_multiplier == 1.8
        assert result.reason == "ios-service"

    def test_detects_swift_router(self):
        result = detect_framework_from_path("router/AppRouter.swift")
        assert result is not None
        assert result.framework == "ios-router"
        assert result.entry_point_multiplier == 2.0

    def test_detects_swiftui_scenes_folder(self):
        """Tests /scenes/ directory for SwiftUI views."""
        result = detect_framework_from_path("scenes/HomeScene.swift")
        assert result is not None
        assert result.framework == "swiftui"
        assert result.reason == "swiftui-view"

    def test_detects_uikit_screens_folder(self):
        """Tests /screens/ directory for UIKit."""
        result = detect_framework_from_path("screens/LoginScreen.swift")
        assert result is not None
        assert result.framework == "uikit"
        assert result.reason == "uikit-viewcontroller"

    def test_app_swift_returns_ios_not_swiftui(self):
        """app.swift always matches iOS entry point (impl line
        274) before SwiftUI rule (impl line 282), documenting
        the dead code at implementation line 282."""
        result = detect_framework_from_path("Sources/App.swift")
        assert result is not None
        # iOS entry-point rule at line 274 catches /app.swift
        # first; the SwiftUI rule at line 282 is dead code for
        # paths containing /sources/.
        assert result.framework == "ios"
        assert result.reason == "ios-app-entry"


# ---------------------------------------------------------------------------
# 15. detect_framework_from_path — Generic patterns
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromPathGeneric:
    """Unknown paths, Windows backslashes, edge cases."""

    def test_returns_none_for_unknown_paths(self):
        result = detect_framework_from_path("src/internal/crypto.ts")
        assert result is None

    def test_normalizes_windows_backslashes(self):
        result = detect_framework_from_path("routes\\auth.ts")
        assert result is not None
        assert result.framework == "express"

    def test_empty_string_returns_none(self):
        assert detect_framework_from_path("") is None

    def test_very_long_path_no_crash(self):
        long_path = "a/" * 500 + "file.ts"
        # Should not raise; may return None or a hint
        result = detect_framework_from_path(long_path)
        # Just ensure no exception — result may be None
        assert result is None or isinstance(result, FrameworkHint)

    def test_just_filename_no_directory(self):
        assert detect_framework_from_path("utils.ts") is None

    def test_api_index_files(self):
        result = detect_framework_from_path("api/index.ts")
        assert result is not None
        assert result.framework == "api"
        assert result.entry_point_multiplier == 1.8
        assert result.reason == "api-index"

    def test_dot_only_path(self):
        assert detect_framework_from_path(".") is None

    def test_path_with_spaces(self):
        result = detect_framework_from_path("routes/my route.ts")
        assert result is not None
        assert result.framework == "express"

    def test_deeply_nested_pages(self):
        result = detect_framework_from_path("pages/a/b/c/d.tsx")
        assert result is not None
        assert result.framework == "nextjs-pages"

    def test_api_index_js(self):
        result = detect_framework_from_path("api/index.js")
        assert result is not None
        assert result.framework == "api"
        assert result.reason == "api-index"

    def test_non_matching_extension(self):
        """Files with non-code extensions in framework dirs
        return None."""
        result = detect_framework_from_path("routes/README.md")
        assert result is None

    def test_test_files_in_framework_dirs(self):
        """Test files in routes/ with .ts extension still match
        (framework detection doesn't exclude test files)."""
        result = detect_framework_from_path("routes/auth.test.ts")
        assert result is not None
        assert result.framework == "express"


# ---------------------------------------------------------------------------
# 16. detect_framework_from_ast
# ---------------------------------------------------------------------------


class TestDetectFrameworkFromAst:
    """AST-based detection using decorators/annotations."""

    # --- Empty / invalid inputs ---

    def test_returns_none_for_empty_language_and_text(self):
        assert detect_framework_from_ast("", "") is None

    def test_returns_none_for_empty_text(self):
        result = detect_framework_from_ast("typescript", "")
        assert result is None

    def test_returns_none_for_empty_language(self):
        result = detect_framework_from_ast("", "some code")
        assert result is None

    # --- NestJS ---

    def test_detects_nestjs_controller_decorator_typescript(
        self,
    ):
        result = detect_framework_from_ast("typescript", '@Controller("/users")')
        assert result is not None
        assert result.framework == "nestjs"
        assert result.entry_point_multiplier == 3.2

    def test_detects_nestjs_get_decorator_javascript(self):
        result = detect_framework_from_ast("javascript", '@Get("/")')
        assert result is not None
        assert result.framework == "nestjs"

    def test_detects_nestjs_post_decorator(self):
        result = detect_framework_from_ast("typescript", '@Post("/items")')
        assert result is not None
        assert result.framework == "nestjs"

    def test_nestjs_injectable_not_detected(self):
        """@Injectable is NOT in the NestJS patterns list."""
        result = detect_framework_from_ast("typescript", "@Injectable()")
        assert result is None

    # --- FastAPI ---

    def test_detects_fastapi_decorators_python(self):
        result = detect_framework_from_ast("python", '@app.get("/users")')
        assert result is not None
        assert result.framework == "fastapi"

    def test_detects_fastapi_post_python(self):
        result = detect_framework_from_ast("python", '@app.post("/users")')
        assert result is not None
        assert result.framework == "fastapi"

    # --- Flask ---

    def test_detects_flask_decorators_python(self):
        result = detect_framework_from_ast("python", '@app.route("/users")')
        assert result is not None
        assert result.framework == "flask"

    def test_detects_flask_blueprint_bp_short(self):
        """@bp.route doesn't match @blueprint.route pattern
        — returns None."""
        result = detect_framework_from_ast("python", '@bp.route("/items")')
        assert result is None

    def test_detects_flask_blueprint_route(self):
        """@blueprint.route (full word) should match."""
        result = detect_framework_from_ast("python", '@blueprint.route("/items")')
        assert result is not None
        assert result.framework == "flask"
        assert result.entry_point_multiplier == 2.8
        assert result.reason == "flask-decorator"

    # --- Spring / Java ---

    def test_detects_spring_rest_controller_java(self):
        result = detect_framework_from_ast("java", "@RestController")
        assert result is not None
        assert result.framework == "spring"

    def test_detects_spring_request_mapping(self):
        result = detect_framework_from_ast("java", '@RequestMapping("/api")')
        assert result is not None
        assert result.framework == "spring"

    def test_detects_spring_get_mapping(self):
        result = detect_framework_from_ast("java", '@GetMapping("/users")')
        assert result is not None
        assert result.framework == "spring"

    # --- JAX-RS (Java) ---

    def test_detects_jaxrs_path_annotation(self):
        result = detect_framework_from_ast("java", '@Path("/users")')
        assert result is not None
        assert result.framework == "jaxrs"
        assert result.entry_point_multiplier == 3.0
        assert result.reason == "jaxrs-annotation"

    def test_detects_jaxrs_get_annotation(self):
        result = detect_framework_from_ast("java", "@GET")
        assert result is not None
        assert result.framework == "jaxrs"

    # --- Spring first-match priority over JAX-RS ---

    def test_spring_matched_before_jaxrs_in_java(self):
        """Spring configs come before JAX-RS in Java, so
        @Controller matches spring, not jaxrs."""
        result = detect_framework_from_ast("java", "@Controller")
        assert result is not None
        assert result.framework == "spring"

    # --- ASP.NET / C# ---

    def test_detects_aspnet_api_controller_csharp(self):
        result = detect_framework_from_ast("csharp", "[ApiController]")
        assert result is not None
        assert result.framework == "aspnet"

    def test_detects_aspnet_http_get(self):
        result = detect_framework_from_ast(
            "csharp",
            "[HttpGet] public IActionResult Get()",
        )
        assert result is not None
        assert result.framework == "aspnet"

    # --- Laravel / PHP ---

    def test_detects_laravel_route_definitions_php(self):
        result = detect_framework_from_ast(
            "php",
            "Route::get('/users', [UserController::class, 'index'])",
        )
        assert result is not None
        assert result.framework == "laravel"

    def test_detects_laravel_post_route(self):
        result = detect_framework_from_ast(
            "php",
            "Route::post('/users', [UserController::class, 'store'])",
        )
        assert result is not None
        assert result.framework == "laravel"

    # --- Kotlin ---

    def test_detects_spring_kotlin_annotations(self):
        result = detect_framework_from_ast("kotlin", "@RestController")
        assert result is not None
        assert result.framework in {"spring", "spring-kotlin"}

    def test_detects_ktor_routing(self):
        result = detect_framework_from_ast("kotlin", "routing {")
        assert result is not None
        assert result.framework == "ktor"

    def test_detects_ktor_embedded_server(self):
        result = detect_framework_from_ast(
            "kotlin",
            "embeddedServer(Netty, port = 8080)",
        )
        assert result is not None
        assert result.framework == "ktor"
        assert result.reason == "ktor-routing"

    def test_android_composable_not_detected(self):
        """@Composable is NOT in the android-kotlin AST
        patterns."""
        result = detect_framework_from_ast("kotlin", "@Composable")
        assert result is None

    # --- Android-Kotlin positive tests ---

    def test_detects_android_entry_point_kotlin(self):
        result = detect_framework_from_ast("kotlin", "@AndroidEntryPoint")
        assert result is not None
        assert result.framework == "android-kotlin"
        assert result.entry_point_multiplier == 2.5

    def test_detects_app_compat_activity_kotlin(self):
        result = detect_framework_from_ast(
            "kotlin",
            "class MainActivity : AppCompatActivity()",
        )
        assert result is not None
        assert result.framework == "android-kotlin"

    def test_detects_fragment_kotlin(self):
        result = detect_framework_from_ast(
            "kotlin",
            "class HomeFragment : Fragment(R.layout.home)",
        )
        assert result is not None
        assert result.framework == "android-kotlin"

    # --- Kotlin JAX-RS ---

    def test_detects_jaxrs_in_kotlin(self):
        result = detect_framework_from_ast("kotlin", '@Path("/api/users")')
        assert result is not None
        assert result.framework == "jaxrs"

    # --- Unsupported language ---

    def test_returns_none_for_unsupported_language(self):
        result = detect_framework_from_ast("rust", '#[get("/")]')
        assert result is None

    # --- Swift not in AST map ---

    def test_swift_not_in_ast_language_map(self):
        """Swift is not mapped in the AST language config."""
        result = detect_framework_from_ast("swift", "viewDidLoad()")
        assert result is None

    # --- Case insensitivity ---

    def test_language_is_case_insensitive(self):
        result = detect_framework_from_ast("TypeScript", '@Controller("/")')
        assert result is not None

    def test_language_uppercase(self):
        result = detect_framework_from_ast("PYTHON", '@app.get("/users")')
        assert result is not None
        assert result.framework == "fastapi"

    # --- Go HTTP patterns ---

    def test_go_not_in_ast_language_map(self):
        """Go is not in the AST language mapping."""
        result = detect_framework_from_ast("go", "http.HandleFunc")
        assert result is None

    # --- Express middleware ---

    def test_express_router_not_in_typescript_ast(self):
        """Express router.get is not in TypeScript AST
        patterns."""
        result = detect_framework_from_ast("typescript", "router.get('/users')")
        assert result is None

    # --- Multiline / partial code ---

    def test_decorator_in_longer_text(self):
        code = """
class UsersController:
    @app.get("/users")
    def list_users(self):
        pass
"""
        result = detect_framework_from_ast("python", code)
        assert result is not None
        assert result.framework == "fastapi"


# ---------------------------------------------------------------------------
# 17. FRAMEWORK_AST_PATTERNS
# ---------------------------------------------------------------------------


class TestFrameworkAstPatterns:
    """Verify the exported pattern dict has all expected frameworks."""

    def test_has_patterns_for_all_expected_frameworks(self):
        expected_frameworks = [
            "nestjs",
            "express",
            "fastapi",
            "flask",
            "spring",
            "jaxrs",
            "aspnet",
            "go-http",
            "laravel",
            "actix",
            "axum",
            "rocket",
            "uikit",
            "swiftui",
            "combine",
        ]
        for fw in expected_frameworks:
            assert fw in FRAMEWORK_AST_PATTERNS, f"Missing framework: {fw}"
            assert len(FRAMEWORK_AST_PATTERNS[fw]) > 0, f"Empty patterns for: {fw}"

    def test_patterns_are_lists_of_strings(self):
        for fw, patterns in FRAMEWORK_AST_PATTERNS.items():
            assert isinstance(patterns, list), f"{fw} patterns should be a list"
            for pat in patterns:
                assert isinstance(pat, str), f"{fw} has non-string pattern: {pat}"

    def test_is_a_dict(self):
        assert isinstance(FRAMEWORK_AST_PATTERNS, dict)

    def test_not_empty(self):
        assert len(FRAMEWORK_AST_PATTERNS) > 0

    def test_nestjs_has_controller_pattern(self):
        patterns = FRAMEWORK_AST_PATTERNS["nestjs"]
        # At least one pattern should match @Controller
        assert any("Controller" in p or "controller" in p.lower() for p in patterns)

    def test_spring_has_rest_controller_pattern(self):
        patterns = FRAMEWORK_AST_PATTERNS["spring"]
        assert any("RestController" in p or "RequestMapping" in p for p in patterns)

    def test_fastapi_has_app_pattern(self):
        patterns = FRAMEWORK_AST_PATTERNS["fastapi"]
        assert any("app" in p.lower() for p in patterns)

    def test_laravel_has_route_pattern(self):
        patterns = FRAMEWORK_AST_PATTERNS["laravel"]
        assert any("Route" in p for p in patterns)
