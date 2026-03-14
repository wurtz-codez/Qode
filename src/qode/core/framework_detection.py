"""Framework detection: path and AST patterns for entry-point scoring.

Detects 50+ framework conventions (Next.js, Express, Django, FastAPI,
Spring, Laravel, Go, Rust, Swift, etc.) from file paths and AST text.
Used by the entry-point scorer and parse engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "FRAMEWORK_AST_PATTERNS",
    "FrameworkHint",
    "detect_framework_from_ast",
    "detect_framework_from_path",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameworkHint:
    """A detected framework hint with scoring multiplier and reason tag."""

    framework: str
    entry_point_multiplier: float
    reason: str


# ---------------------------------------------------------------------------
# Path-based detection
# ---------------------------------------------------------------------------

# Pre-compiled regex for React PascalCase filename check.
_PASCAL_CASE_RE = re.compile(r"^[A-Z]")


def _ends_with_web_ext(p: str) -> bool:
    """Return *True* if *p* ends with a JS/TS web extension."""
    return p.endswith((".tsx", ".ts", ".jsx", ".js"))


def detect_framework_from_path(file_path: str) -> FrameworkHint | None:
    """Detect a framework from a file path using 60+ convention patterns.

    The path is normalised to lower-case with forward slashes before
    matching so that the checks are case- and OS-insensitive.

    Returns a :class:`FrameworkHint` or ``None`` when no pattern matches.
    """
    p = file_path.lower().replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p

    # -- Next.js - Pages Router (high confidence) -------------------------
    if "/pages/" in p and "/_" not in p and "/api/" not in p and _ends_with_web_ext(p):
        return FrameworkHint("nextjs-pages", 3.0, "nextjs-page")

    # -- Next.js - App Router (page.tsx files) -----------------------------
    if "/app/" in p and (
        p.endswith("page.tsx")
        or p.endswith("page.ts")
        or p.endswith("page.jsx")
        or p.endswith("page.js")
    ):
        return FrameworkHint("nextjs-app", 3.0, "nextjs-app-page")

    # -- Next.js - API Routes ----------------------------------------------
    if "/pages/api/" in p or ("/app/" in p and "/api/" in p and p.endswith("route.ts")):
        return FrameworkHint("nextjs-api", 3.0, "nextjs-api-route")

    # -- Next.js - Layout files --------------------------------------------
    if "/app/" in p and (p.endswith("layout.tsx") or p.endswith("layout.ts")):
        return FrameworkHint("nextjs-app", 2.0, "nextjs-layout")

    # -- Express / Node.js routes ------------------------------------------
    if "/routes/" in p and (p.endswith(".ts") or p.endswith(".js")):
        return FrameworkHint("express", 2.5, "routes-folder")

    # -- Generic controllers (MVC pattern) ---------------------------------
    if "/controllers/" in p and (p.endswith(".ts") or p.endswith(".js")):
        return FrameworkHint("mvc", 2.5, "controllers-folder")

    # -- Generic handlers --------------------------------------------------
    if "/handlers/" in p and (p.endswith(".ts") or p.endswith(".js")):
        return FrameworkHint("handlers", 2.5, "handlers-folder")

    # -- React components --------------------------------------------------
    # NOTE: The TS original lowercases the path *before* checking PascalCase
    # on the filename, so the regex ^[A-Z] can never match.  We faithfully
    # replicate that bug here.
    if ("/components/" in p or "/views/" in p) and (
        p.endswith(".tsx") or p.endswith(".jsx")
    ):
        file_name = p.rsplit("/", 1)[-1]
        if _PASCAL_CASE_RE.search(file_name):
            return FrameworkHint("react", 1.5, "react-component")

    # -- Django views ------------------------------------------------------
    if p.endswith("views.py"):
        return FrameworkHint("django", 3.0, "django-views")

    # -- Django URL configs ------------------------------------------------
    if p.endswith("urls.py"):
        return FrameworkHint("django", 2.0, "django-urls")

    # -- FastAPI / Flask routers -------------------------------------------
    if ("/routers/" in p or "/endpoints/" in p or "/routes/" in p) and p.endswith(
        ".py"
    ):
        return FrameworkHint("fastapi", 2.5, "api-routers")

    # -- Python API folder -------------------------------------------------
    if "/api/" in p and p.endswith(".py") and not p.endswith("__init__.py"):
        return FrameworkHint("python-api", 2.0, "api-folder")

    # -- Spring Boot controllers -------------------------------------------
    if ("/controller/" in p or "/controllers/" in p) and p.endswith(".java"):
        return FrameworkHint("spring", 3.0, "spring-controller")

    # -- Spring Boot - files ending in Controller.java ---------------------
    if p.endswith("controller.java"):
        return FrameworkHint("spring", 3.0, "spring-controller-file")

    # -- Java service layer ------------------------------------------------
    if ("/service/" in p or "/services/" in p) and p.endswith(".java"):
        return FrameworkHint("java-service", 1.8, "java-service")

    # -- Spring Boot Kotlin controllers ------------------------------------
    if ("/controller/" in p or "/controllers/" in p) and p.endswith(".kt"):
        return FrameworkHint("spring-kotlin", 3.0, "spring-kotlin-controller")

    # -- Spring Boot - files ending in Controller.kt -----------------------
    if p.endswith("controller.kt"):
        return FrameworkHint("spring-kotlin", 3.0, "spring-kotlin-controller-file")

    # -- Ktor routes -------------------------------------------------------
    if "/routes/" in p and p.endswith(".kt"):
        return FrameworkHint("ktor", 2.5, "ktor-routes")

    # -- Ktor plugins folder -----------------------------------------------
    if "/plugins/" in p and p.endswith(".kt"):
        return FrameworkHint("ktor", 2.0, "ktor-plugin")

    if p.endswith("routing.kt") or p.endswith("routes.kt"):
        return FrameworkHint("ktor", 2.5, "ktor-routing-file")

    # -- Android Activities, Fragments -------------------------------------
    if ("/activity/" in p or "/ui/" in p) and p.endswith(".kt"):
        return FrameworkHint("android-kotlin", 2.5, "android-ui")

    if p.endswith("activity.kt") or p.endswith("fragment.kt"):
        return FrameworkHint("android-kotlin", 2.5, "android-component")

    # -- Kotlin main entry point -------------------------------------------
    if p.endswith("/main.kt"):
        return FrameworkHint("kotlin", 3.0, "kotlin-main")

    # -- Kotlin Application entry point ------------------------------------
    if p.endswith("/application.kt"):
        return FrameworkHint("kotlin", 2.5, "kotlin-application")

    # -- ASP.NET Controllers -----------------------------------------------
    if "/controllers/" in p and p.endswith(".cs"):
        return FrameworkHint("aspnet", 3.0, "aspnet-controller")

    # -- ASP.NET - files ending in Controller.cs ---------------------------
    if p.endswith("controller.cs"):
        return FrameworkHint("aspnet", 3.0, "aspnet-controller-file")

    # -- Blazor pages ------------------------------------------------------
    if "/pages/" in p and p.endswith(".razor"):
        return FrameworkHint("blazor", 2.5, "blazor-page")

    # -- Go handlers -------------------------------------------------------
    if ("/handlers/" in p or "/handler/" in p) and p.endswith(".go"):
        return FrameworkHint("go-http", 2.5, "go-handlers")

    # -- Go routes ---------------------------------------------------------
    if "/routes/" in p and p.endswith(".go"):
        return FrameworkHint("go-http", 2.5, "go-routes")

    # -- Go controllers ----------------------------------------------------
    if "/controllers/" in p and p.endswith(".go"):
        return FrameworkHint("go-mvc", 2.5, "go-controller")

    # -- Go main.go --------------------------------------------------------
    # NOTE: faithfully ported from TS which has an operator-precedence quirk
    # (the `&&` binds tighter than `||`).
    if p.endswith("/main.go") or ("/cmd/" in p and p.endswith(".go")):
        return FrameworkHint("go", 3.0, "go-main")

    # -- Rust handlers/routes ----------------------------------------------
    if ("/handlers/" in p or "/routes/" in p) and p.endswith(".rs"):
        return FrameworkHint("rust-web", 2.5, "rust-handlers")

    # -- Rust main.rs ------------------------------------------------------
    if p.endswith("/main.rs"):
        return FrameworkHint("rust", 3.0, "rust-main")

    # -- Rust bin folder ---------------------------------------------------
    if "/bin/" in p and p.endswith(".rs"):
        return FrameworkHint("rust", 2.5, "rust-bin")

    # -- C/C++ main files --------------------------------------------------
    if p.endswith("/main.c") or p.endswith("/main.cpp") or p.endswith("/main.cc"):
        return FrameworkHint("c-cpp", 3.0, "c-main")

    # -- C/C++ src folder app ----------------------------------------------
    if "/src/" in p and (p.endswith("/app.c") or p.endswith("/app.cpp")):
        return FrameworkHint("c-cpp", 2.5, "c-app")

    # -- Laravel routes ----------------------------------------------------
    if "/routes/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 3.0, "laravel-routes")

    # -- Laravel controllers -----------------------------------------------
    if ("/http/controllers/" in p or "/controllers/" in p) and p.endswith(".php"):
        return FrameworkHint("laravel", 3.0, "laravel-controller")

    # -- Laravel controller by file name -----------------------------------
    if p.endswith("controller.php"):
        return FrameworkHint("laravel", 3.0, "laravel-controller-file")

    # -- Laravel console commands ------------------------------------------
    if ("/console/commands/" in p or "/commands/" in p) and p.endswith(".php"):
        return FrameworkHint("laravel", 2.5, "laravel-command")

    # -- Laravel jobs ------------------------------------------------------
    if "/jobs/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 2.5, "laravel-job")

    # -- Laravel listeners -------------------------------------------------
    if "/listeners/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 2.5, "laravel-listener")

    # -- Laravel middleware ------------------------------------------------
    if "/http/middleware/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 2.5, "laravel-middleware")

    # -- Laravel service providers -----------------------------------------
    if "/providers/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 1.8, "laravel-provider")

    # -- Laravel policies --------------------------------------------------
    if "/policies/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 2.0, "laravel-policy")

    # -- Laravel models ----------------------------------------------------
    if "/models/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 1.5, "laravel-model")

    # -- Laravel services --------------------------------------------------
    if "/services/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 1.8, "laravel-service")

    # -- Laravel repositories ----------------------------------------------
    if "/repositories/" in p and p.endswith(".php"):
        return FrameworkHint("laravel", 1.5, "laravel-repository")

    # -- iOS App entry points ----------------------------------------------
    if (
        p.endswith("/appdelegate.swift")
        or p.endswith("/scenedelegate.swift")
        or p.endswith("/app.swift")
    ):
        return FrameworkHint("ios", 3.0, "ios-app-entry")

    # -- SwiftUI App entry -------------------------------------------------
    if p.endswith("app.swift") and "/sources/" in p:
        return FrameworkHint("swiftui", 3.0, "swiftui-app")

    # -- UIKit ViewControllers ---------------------------------------------
    if (
        "/viewcontrollers/" in p or "/controllers/" in p or "/screens/" in p
    ) and p.endswith(".swift"):
        return FrameworkHint("uikit", 2.5, "uikit-viewcontroller")

    # -- ViewController by filename ----------------------------------------
    if p.endswith("viewcontroller.swift") or p.endswith("vc.swift"):
        return FrameworkHint("uikit", 2.5, "uikit-viewcontroller-file")

    # -- Coordinator pattern -----------------------------------------------
    if "/coordinators/" in p and p.endswith(".swift"):
        return FrameworkHint("ios-coordinator", 2.5, "ios-coordinator")

    # -- Coordinator by filename -------------------------------------------
    if p.endswith("coordinator.swift"):
        return FrameworkHint("ios-coordinator", 2.5, "ios-coordinator-file")

    # -- SwiftUI Views -----------------------------------------------------
    if ("/views/" in p or "/scenes/" in p) and p.endswith(".swift"):
        return FrameworkHint("swiftui", 1.8, "swiftui-view")

    # -- Service layer (Swift) ---------------------------------------------
    if "/services/" in p and p.endswith(".swift"):
        return FrameworkHint("ios-service", 1.8, "ios-service")

    # -- Router / navigation (Swift) ---------------------------------------
    if "/router/" in p and p.endswith(".swift"):
        return FrameworkHint("ios-router", 2.0, "ios-router")

    # -- Generic: API index files ------------------------------------------
    if "/api/" in p and (
        p.endswith("/index.ts") or p.endswith("/index.js") or p.endswith("/__init__.py")
    ):
        return FrameworkHint("api", 1.8, "api-index")

    return None


# ---------------------------------------------------------------------------
# AST-based detection
# ---------------------------------------------------------------------------

FRAMEWORK_AST_PATTERNS: dict[str, list[str]] = {
    "nestjs": [
        "@Controller",
        "@Get",
        "@Post",
        "@Put",
        "@Delete",
        "@Patch",
    ],
    "express": [
        "app.get",
        "app.post",
        "app.put",
        "app.delete",
        "router.get",
        "router.post",
    ],
    "fastapi": [
        "@app.get",
        "@app.post",
        "@app.put",
        "@app.delete",
        "@router.get",
    ],
    "flask": [
        "@app.route",
        "@blueprint.route",
    ],
    "spring": [
        "@RestController",
        "@Controller",
        "@GetMapping",
        "@PostMapping",
        "@RequestMapping",
    ],
    "jaxrs": [
        "@Path",
        "@GET",
        "@POST",
        "@PUT",
        "@DELETE",
    ],
    "aspnet": [
        "[ApiController]",
        "[HttpGet]",
        "[HttpPost]",
        "[Route]",
    ],
    "go-http": [
        "http.Handler",
        "http.HandlerFunc",
        "ServeHTTP",
    ],
    "laravel": [
        "Route::get",
        "Route::post",
        "Route::put",
        "Route::delete",
        "Route::resource",
        "Route::apiResource",
        "#[Route(",
    ],
    "actix": [
        "#[get",
        "#[post",
        "#[put",
        "#[delete",
    ],
    "axum": [
        "Router::new",
    ],
    "rocket": [
        "#[get",
        "#[post",
    ],
    "uikit": [
        "viewDidLoad",
        "viewWillAppear",
        "viewDidAppear",
        "UIViewController",
    ],
    "swiftui": [
        "@main",
        "WindowGroup",
        "ContentView",
        "@StateObject",
        "@ObservedObject",
    ],
    "combine": [
        "sink",
        "assign",
        "Publisher",
        "Subscriber",
    ],
}


@dataclass(frozen=True)
class _AstPatternConfig:
    """Internal: a single AST pattern config entry (pre-lowercased)."""

    framework: str
    entry_point_multiplier: float
    reason: str
    patterns: list[str]


def _build_ast_patterns() -> dict[str, list[_AstPatternConfig]]:
    """Build the language -> pattern-config mapping, pre-lowercasing patterns."""

    def _lower(patterns: list[str]) -> list[str]:
        return [p.lower() for p in patterns]

    return {
        "javascript": [
            _AstPatternConfig(
                "nestjs",
                3.2,
                "nestjs-decorator",
                _lower(FRAMEWORK_AST_PATTERNS["nestjs"]),
            ),
        ],
        "typescript": [
            _AstPatternConfig(
                "nestjs",
                3.2,
                "nestjs-decorator",
                _lower(FRAMEWORK_AST_PATTERNS["nestjs"]),
            ),
        ],
        "python": [
            _AstPatternConfig(
                "fastapi",
                3.0,
                "fastapi-decorator",
                _lower(FRAMEWORK_AST_PATTERNS["fastapi"]),
            ),
            _AstPatternConfig(
                "flask",
                2.8,
                "flask-decorator",
                _lower(FRAMEWORK_AST_PATTERNS["flask"]),
            ),
        ],
        "java": [
            _AstPatternConfig(
                "spring",
                3.2,
                "spring-annotation",
                _lower(FRAMEWORK_AST_PATTERNS["spring"]),
            ),
            _AstPatternConfig(
                "jaxrs",
                3.0,
                "jaxrs-annotation",
                _lower(FRAMEWORK_AST_PATTERNS["jaxrs"]),
            ),
        ],
        "kotlin": [
            _AstPatternConfig(
                "spring-kotlin",
                3.2,
                "spring-kotlin-annotation",
                _lower(FRAMEWORK_AST_PATTERNS["spring"]),
            ),
            _AstPatternConfig(
                "jaxrs",
                3.0,
                "jaxrs-annotation",
                _lower(FRAMEWORK_AST_PATTERNS["jaxrs"]),
            ),
            _AstPatternConfig(
                "ktor",
                2.8,
                "ktor-routing",
                _lower(["routing", "embeddedServer", "Application.module"]),
            ),
            _AstPatternConfig(
                "android-kotlin",
                2.5,
                "android-annotation",
                _lower(["@AndroidEntryPoint", "AppCompatActivity", "Fragment("]),
            ),
        ],
        "csharp": [
            _AstPatternConfig(
                "aspnet",
                3.2,
                "aspnet-attribute",
                _lower(FRAMEWORK_AST_PATTERNS["aspnet"]),
            ),
        ],
        "php": [
            _AstPatternConfig(
                "laravel",
                3.0,
                "php-route-attribute",
                _lower(FRAMEWORK_AST_PATTERNS["laravel"]),
            ),
        ],
    }


# Pre-compute at module load time (same optimisation as the TS version).
_AST_PATTERNS_BY_LANGUAGE: dict[str, list[_AstPatternConfig]] = _build_ast_patterns()


def detect_framework_from_ast(
    language: str, definition_text: str
) -> FrameworkHint | None:
    """Detect a framework from AST definition text and language identifier.

    Searches pre-lowercased pattern strings inside the lowercased
    *definition_text* and returns the first match as a
    :class:`FrameworkHint`, or ``None`` if nothing matches.
    """
    if not language or not definition_text:
        return None

    configs = _AST_PATTERNS_BY_LANGUAGE.get(language.lower())
    if not configs:
        return None

    normalized = definition_text.lower()
    for cfg in configs:
        for pattern in cfg.patterns:
            if pattern in normalized:
                return FrameworkHint(
                    cfg.framework,
                    cfg.entry_point_multiplier,
                    cfg.reason,
                )
    return None
