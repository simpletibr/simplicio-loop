"""Deterministic Axum CRUD route generation for scratch tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _AxumCrudSpec:
    resource: str
    item_type: str
    input_type: str
    state_field: str
    list_handler: str
    create_handler: str
    test_name: str


class RustAxumCrudExecutor(TaskExecutor):
    """Render a compact Axum CRUD API into the scaffold's main.rs."""

    name = "rust-axum-crud"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if stack.slug != "rust-axum":
            return False
        if task.target.replace("\\", "/") != "src/main.rs":
            return False
        text = _task_text(task).lower()
        return "crud" in text and any(token in text for token in ("axum", "route", "api"))

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        if task.target.replace("\\", "/") != "src/main.rs":
            return _fallback("unsupported rust-axum CRUD task shape")
        spec = _parse_spec(task)
        if spec is None:
            return _fallback("unsupported rust-axum CRUD task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")
        if target.exists() and _looks_generated(target.read_text(encoding="utf-8")):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{task.target} already has generated Axum CRUD routes",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_main(spec), encoding="utf-8", newline="\n")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"generated Axum CRUD routes for {spec.resource}",
        )


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_spec(task: Task) -> _AxumCrudSpec | None:
    text = _task_text(task)
    route_match = re.search(r"route prefix is /([A-Za-z0-9_-]+)", text, re.I)
    resource = route_match.group(1) if route_match else _resource_from_goal(task.goal)
    words = _words(resource)
    if not words:
        return None
    singular_words = _singular_words(words)
    item_type = _pascal_case(singular_words) or "Item"
    input_type = f"{item_type}Input"
    base = "_".join(word.lower() for word in words)
    singular = "_".join(word.lower() for word in singular_words) or "item"
    return _AxumCrudSpec(
        resource=base,
        item_type=item_type,
        input_type=input_type,
        state_field=base,
        list_handler=f"list_{base}",
        create_handler=f"create_{singular}",
        test_name=f"{base}_crud_routes_work",
    )


def _resource_from_goal(goal: str) -> str:
    match = re.search(
        r"for\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,2})",
        goal,
        re.I,
    )
    return match.group(1) if match else "items"


def _words(value: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.strip())
    return re.findall(r"[A-Za-z0-9]+", expanded.replace("-", " ").replace("_", " "))


def _singular_words(words: list[str]) -> list[str]:
    if not words:
        return []
    out = list(words)
    out[-1] = _singularize(out[-1])
    return out


def _singularize(word: str) -> str:
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if lower.endswith("s") and not lower.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _pascal_case(words: list[str]) -> str:
    return "".join(word.capitalize() for word in words)


def _looks_generated(text: str) -> bool:
    return "simplicio generated rust-axum CRUD" in text


def _render_main(spec: _AxumCrudSpec) -> str:
    return f"""use axum::{{
    extract::State,
    http::StatusCode,
    routing::get,
    Json, Router,
}};
use serde::{{Deserialize, Serialize}};
use std::sync::{{Arc, Mutex}};

// simplicio generated rust-axum CRUD
#[derive(Clone, Debug, Serialize)]
struct HealthResponse {{
    status: &'static str,
}}

#[derive(Clone, Debug, Serialize)]
struct {spec.item_type} {{
    id: u64,
    name: String,
}}

#[derive(Debug, Deserialize)]
struct {spec.input_type} {{
    name: String,
}}

#[derive(Clone, Default)]
struct AppState {{
    {spec.state_field}: Arc<Mutex<Vec<{spec.item_type}>>>,
}}

pub fn app() -> Router {{
    Router::new()
        .route("/health", get(health))
        .route("/{spec.resource}", get({spec.list_handler}).post({spec.create_handler}))
        .with_state(AppState::default())
}}

async fn health() -> Json<HealthResponse> {{
    Json(HealthResponse {{ status: "ok" }})
}}

async fn {spec.list_handler}(State(state): State<AppState>) -> Json<Vec<{spec.item_type}>> {{
    let items = state
        .{spec.state_field}
        .lock()
        .expect("{spec.resource} store lock poisoned")
        .clone();
    Json(items)
}}

async fn {spec.create_handler}(
    State(state): State<AppState>,
    Json(input): Json<{spec.input_type}>,
) -> (StatusCode, Json<{spec.item_type}>) {{
    let mut items = state
        .{spec.state_field}
        .lock()
        .expect("{spec.resource} store lock poisoned");
    let item = {spec.item_type} {{
        id: (items.len() as u64) + 1,
        name: input.name,
    }};
    items.push(item.clone());
    (StatusCode::CREATED, Json(item))
}}

#[tokio::main]
async fn main() {{
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .expect("bind 0.0.0.0:3000");
    axum::serve(listener, app()).await.expect("serve axum app");
}}

#[cfg(test)]
mod tests {{
    use super::*;
    use axum::{{
        body::Body,
        http::{{Method, Request, StatusCode}},
    }};
    use tower::ServiceExt;

    #[tokio::test]
    async fn health_returns_ok() {{
        let response = app()
            .oneshot(Request::builder().uri("/health").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }}

    #[tokio::test]
    async fn {spec.test_name}() {{
        let app = app();
        let create_response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method(Method::POST)
                    .uri("/{spec.resource}")
                    .header("content-type", "application/json")
                    .body(Body::from(r#"{{"name":"Sample"}}"#))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(create_response.status(), StatusCode::CREATED);

        let list_response = app
            .oneshot(Request::builder().uri("/{spec.resource}").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(list_response.status(), StatusCode::OK);
    }}
}}
"""


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
