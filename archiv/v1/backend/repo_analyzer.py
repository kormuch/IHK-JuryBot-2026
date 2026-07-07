"""
Repository analyzer — scans, reads, and summarizes team code repos.

Pipeline:
    1. clone_repo()      — git clone --depth 1 (or pull if already cloned)
    2. scan_structure()   — walk directory, detect languages/frameworks/entry points
    3. read_key_files()   — read up to 50 key files (500 lines max each), prioritized by relevance
    4. analyze_repo()     — combines 2+3 into a structured dict for LLM evaluation

Skips: .git, node_modules, __pycache__, binaries, images, lock files.
"""

import asyncio
import os
from pathlib import Path
from collections import Counter

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea",
    ".vscode", "dist", "build", ".next", ".nuxt", "target", ".gradle",
}

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".lock", ".min.js", ".min.css", ".map",
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".sqlite", ".db",
}

LANGUAGE_MAP = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript (React)", ".jsx": "JavaScript (React)",
    ".java": "Java", ".kt": "Kotlin", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++ Header",
    ".swift": "Swift", ".dart": "Dart",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sql": "SQL", ".sh": "Shell", ".bat": "Batch",
    ".yml": "YAML", ".yaml": "YAML", ".json": "JSON",
    ".toml": "TOML", ".xml": "XML", ".md": "Markdown",
}

ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "index.py", "manage.py",
    "main.ts", "index.ts", "server.ts", "app.ts",
    "main.js", "index.js", "server.js", "app.js",
    "Main.java", "App.java",
    "main.go", "main.rs",
    "Program.cs",
}

FRAMEWORK_FILES = {
    "package.json": "Node.js",
    "requirements.txt": "Python",
    "Pipfile": "Python (Pipenv)",
    "pyproject.toml": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "pubspec.yaml": "Dart/Flutter",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "Dockerfile": "Docker",
}


async def clone_repo(url: str, target_dir: str) -> str:
    """Git clone a repo to target_dir. Return local path."""
    target = Path(target_dir)
    if target.exists():
        # Pull instead of re-cloning
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(target), "pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", url, str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {stderr.decode()}")
    return str(target)


async def scan_structure(repo_path: str) -> dict:
    """Walk the repo directory and return structure metadata."""
    root = Path(repo_path)
    file_tree = []
    lang_counter: Counter = Counter()
    frameworks = set()
    entry_points = []
    total_lines = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip ignored dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).relative_to(root)

        for fname in filenames:
            rel_path = str(rel_dir / fname) if str(rel_dir) != "." else fname
            ext = Path(fname).suffix.lower()

            if ext in SKIP_EXTENSIONS:
                continue

            file_tree.append(rel_path)

            if ext in LANGUAGE_MAP:
                lang_counter[LANGUAGE_MAP[ext]] += 1

            if fname in ENTRY_POINT_NAMES:
                entry_points.append(rel_path)

            if fname in FRAMEWORK_FILES:
                frameworks.add(FRAMEWORK_FILES[fname])

            # Rough line count
            full_path = Path(dirpath) / fname
            try:
                total_lines += sum(1 for _ in open(full_path, "r", encoding="utf-8", errors="ignore"))
            except (OSError, UnicodeDecodeError):
                pass

    # Detect frameworks from config file contents
    frameworks_from_content = await _detect_frameworks_from_files(root)
    frameworks.update(frameworks_from_content)

    return {
        "file_tree": sorted(file_tree),
        "languages": dict(lang_counter.most_common()),
        "frameworks": sorted(frameworks),
        "entry_points": entry_points,
        "total_files": len(file_tree),
        "total_lines": total_lines,
    }


async def _detect_frameworks_from_files(root: Path) -> set:
    """Read config files to detect specific frameworks."""
    detected = set()

    # package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            all_deps = {}
            all_deps.update(data.get("dependencies", {}))
            all_deps.update(data.get("devDependencies", {}))
            framework_markers = {
                "react": "React", "next": "Next.js", "vue": "Vue.js",
                "nuxt": "Nuxt.js", "angular": "Angular", "svelte": "Svelte",
                "express": "Express.js", "fastify": "Fastify", "nestjs": "NestJS",
                "@nestjs/core": "NestJS", "tailwindcss": "Tailwind CSS",
            }
            for dep, name in framework_markers.items():
                if dep in all_deps:
                    detected.add(name)
        except Exception:
            pass

    # requirements.txt
    req_txt = root / "requirements.txt"
    if req_txt.exists():
        try:
            content = req_txt.read_text(encoding="utf-8", errors="ignore").lower()
            req_markers = {
                "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
                "streamlit": "Streamlit", "gradio": "Gradio",
                "sqlalchemy": "SQLAlchemy", "pandas": "pandas",
                "torch": "PyTorch", "tensorflow": "TensorFlow",
            }
            for marker, name in req_markers.items():
                if marker in content:
                    detected.add(name)
        except Exception:
            pass

    # pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
            for marker in ["fastapi", "flask", "django"]:
                if marker in content:
                    detected.add(marker.capitalize() if marker != "fastapi" else "FastAPI")
        except Exception:
            pass

    return detected


async def read_key_files(repo_path: str, structure: dict) -> dict:
    """Read the most important files for evaluation.
    Returns dict of filepath -> content. Max 50 files, max 500 lines each.
    """
    root = Path(repo_path)
    files_to_read: list[str] = []

    file_tree = structure["file_tree"]

    # 1. README
    for name in ["README.md", "README", "readme.md", "Readme.md"]:
        if name in file_tree:
            files_to_read.append(name)

    # 2. Entry points
    for ep in structure["entry_points"]:
        if ep not in files_to_read:
            files_to_read.append(ep)

    # 3. Config files
    config_names = {
        "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
        ".env.example", "package.json", "requirements.txt",
        "pyproject.toml", "Cargo.toml", "go.mod", "tsconfig.json",
        "vite.config.ts", "vite.config.js", "next.config.js",
        "webpack.config.js",
    }
    for f in file_tree:
        if Path(f).name in config_names and f not in files_to_read:
            files_to_read.append(f)

    # 4. API routes / endpoints / controllers
    route_dirs = {"routes", "api", "endpoints", "controllers", "routers", "views"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in route_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 5. Database models / schemas
    model_dirs = {"models", "schemas", "database", "entities", "domain"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in model_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 6. Tests
    test_dirs = {"test", "tests", "__tests__", "spec"}
    for f in file_tree:
        parts = Path(f).parts
        if any(p.lower() in test_dirs for p in parts):
            if f not in files_to_read:
                files_to_read.append(f)

    # 7. Fill remaining slots with other source files (skip binary/config already added)
    source_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c"}
    for f in file_tree:
        if len(files_to_read) >= 50:
            break
        ext = Path(f).suffix.lower()
        if ext in source_exts and f not in files_to_read:
            files_to_read.append(f)

    # Trim to 50
    files_to_read = files_to_read[:50]

    # Read contents
    result = {}
    for rel_path in files_to_read:
        full_path = root / rel_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            if len(lines) > 500:
                lines = lines[:500]
                lines.append(f"\n... [TRUNCATED — {len(content.splitlines())} lines total]")
            result[rel_path] = "\n".join(lines)
        except (OSError, UnicodeDecodeError):
            pass

    return result


async def analyze_repo(repo_path: str) -> dict:
    """Full pipeline: scan structure + read key files + build analysis summary."""
    structure = await scan_structure(repo_path)
    key_files = await read_key_files(repo_path, structure)

    return {
        "structure": structure,
        "key_files": key_files,
        "summary": {
            "total_files": structure["total_files"],
            "total_lines": structure["total_lines"],
            "languages": structure["languages"],
            "frameworks": structure["frameworks"],
            "entry_points": structure["entry_points"],
            "has_readme": any(
                f.lower().startswith("readme") for f in structure["file_tree"]
            ),
            "has_tests": any(
                p.lower() in ("test", "tests", "__tests__", "spec")
                for f in structure["file_tree"]
                for p in Path(f).parts
            ),
            "has_docker": any(
                f.lower().startswith("dockerfile") or "docker-compose" in f.lower()
                for f in structure["file_tree"]
            ),
        },
    }
