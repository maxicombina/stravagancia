"""The local progress board never needs Django, a database, HTTP or Beads CLI."""
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from tools import garage_progress as board


def issue(identifier="garage-001", status="open", phase="initial", **extra):
    return {"id": identifier, "title": "Una tarea", "status": status, "issue_type": "task",
            "metadata": {"phase": phase}, **extra}


def snapshot(**extra):
    return {"updated_at": "2026-10-04T12:00:00Z", "focus": "Inventario",
            "agents": [{"name": "Sol", "role": "Implementador", "status": "Activo", "task": "garage-005"}],
            "validation": {"tests": 4, "passed": 4, "failed": 0, "skipped": 0,
                           "postgres": "18.6", "checked_at": "2026-10-04T11:00:00Z"},
            "not_applicable": [], **extra}


def test_board_resolves_dependencies_phases_cancelled_and_counts_epics_separately():
    rows = [issue(status="closed"), issue("garage-013", status="closed"),
            issue("garage-021", status="closed"), issue("garage-005", status="in_progress"),
            issue("garage-006", dependencies=[{"type": "blocks", "depends_on_id": "garage-005"},
                                              {"type": "blocks", "depends_on_id": "garage-001"},
                                              {"type": "blocks", "depends_on_id": "garage-013"},
                                              {"type": "blocks", "depends_on_id": "garage-099"},
                                              {"type": "parent-child", "depends_on_id": "garage-000"}]),
            issue("garage-024", phase="future"), issue("garage-000", issue_type="epic")]
    result = board.build_state(rows, snapshot(not_applicable=["garage-013", "garage-021"]))
    assert result["counts"] == {"completed": 1, "in_progress": 1, "pending": 1, "future": 1, "not_applicable": 2}
    assert len(result["epics"]) == 1 and len(result["tasks"]) == 6
    task = next(t for t in result["tasks"] if t["id"] == "garage-006")
    assert task["blockers"] == ["garage-005", "garage-099"]
    assert task["missing_dependencies"] == ["garage-099"]
    assert "garage-000" not in task["dependencies"]


@pytest.mark.parametrize("not_applicable", [[], ["garage-013"]])
def test_terminal_tasks_keep_dependency_information_without_active_blockers(not_applicable):
    rows = [issue("garage-013", status="closed", dependencies=[{"type": "blocks", "depends_on_id": "garage-011"}]),
            issue("garage-011")]
    task = board.build_state(rows, snapshot(not_applicable=not_applicable))["tasks"][1]
    assert task["id"] == "garage-013" and task["dependencies"] == ["garage-011"]
    assert task["blockers"] == [] and task["explicitly_blocked"] is False


def test_whitelist_omits_private_nested_fields_and_redacts_paths_and_email():
    private = "private@example.com"
    result = board.build_state([issue(title="Task " + private + " /Users/private/.env", owner=private,
                                     description="SECRET", notes="SECRET", metadata={"phase": "initial", "token": "SECRET"})],
                              snapshot(agents=[{"name": "Sol", "role": "Revisor", "status": "Activo", "task": "garage-001",
                                                "email": private, "notes": "SECRET"}], notes="SECRET"))
    serialized = json.dumps(result)
    assert private not in serialized and "/Users/private" not in serialized
    assert "owner" not in result["tasks"][0] and "token" not in serialized
    assert set(result) == {"updated_at", "focus", "tasks", "epics", "counts", "agents", "validation", "graph"}
    assert set(result["tasks"][0]) == {"id", "title", "status", "phase", "dependencies", "explicitly_blocked", "blockers", "missing_dependencies",
                                       "priority", "type", "description", "acceptance_criteria", "notes", "close_reason", "model", "created_at", "updated_at", "closed_at"}
    assert set(result["agents"][0]) == {"name", "role", "status", "task"}


@pytest.mark.parametrize("content", ["{bad", "[]", '{"title":"missing id"}', '{"id":"garage-abc"}', ""])
def test_malformed_issue_export_is_honest_error(content):
    with pytest.raises(board.StateError):
        board.parse_issues(content)


def test_non_garage_issues_ignored_but_duplicate_garage_rejected():
    rows = board.parse_issues(json.dumps({"id": "other-001", "owner": "SECRET"}) + "\n" + json.dumps(issue()))
    assert len(rows) == 1
    with pytest.raises(board.StateError):
        board.parse_issues("\n".join([json.dumps(issue())] * 2))


def subtask_rows():
    """Beads sub-tasks (16-17 oct export): parent-child to the parent task, blocks to a sibling."""
    return [issue("garage-000", issue_type="epic"),
            issue("garage-031", dependencies=[{"type": "parent-child", "depends_on_id": "garage-000"}]),
            issue("garage-031.1", status="closed", dependencies=[{"type": "parent-child", "depends_on_id": "garage-031"}]),
            issue("garage-031.2", status="closed", dependencies=[{"type": "parent-child", "depends_on_id": "garage-031"},
                                                                 {"type": "blocks", "depends_on_id": "garage-031.1"}])]


@pytest.mark.parametrize("not_applicable", [[], ["garage-031.1"]])
def test_closed_subtasks_are_normal_rows_with_sibling_edges_and_no_parent_dependency(not_applicable):
    result = board.build_state(subtask_rows(), snapshot(not_applicable=not_applicable))
    assert [task["id"] for task in result["tasks"]] == ["garage-031", "garage-031.1", "garage-031.2"]
    assert [epic["id"] for epic in result["epics"]] == ["garage-000"]
    expected = {"completed": 2, "in_progress": 0, "pending": 1, "future": 0, "not_applicable": 0}
    if not_applicable:
        expected.update(completed=1, not_applicable=1)
    assert result["counts"] == expected
    child = next(task for task in result["tasks"] if task["id"] == "garage-031.2")
    assert child["dependencies"] == ["garage-031.1"] and child["blockers"] == [] and child["missing_dependencies"] == []
    # parent-child stays out of the DAG, as for epics: only blocks edges are drawn.
    assert result["graph"]["edges"] == [{"from": "garage-031.1", "to": "garage-031.2"}]
    assert result["graph"]["missing"] == [] and result["graph"]["cycle_nodes"] == []
    assert {node["id"] for node in result["graph"]["nodes"]} == {"garage-031", "garage-031.1", "garage-031.2"}


def test_parse_issues_accepts_subtask_export_and_still_rejects_duplicate_subtasks():
    content = "\n".join(json.dumps(row) for row in subtask_rows())
    assert [row["id"] for row in board.parse_issues(content)] == ["garage-000", "garage-031", "garage-031.1", "garage-031.2"]
    with pytest.raises(board.StateError):
        board.parse_issues(content + "\n" + json.dumps(issue("garage-031.2")))


@pytest.mark.parametrize("value", ["garage-031", "garage-031.1", "garage-031.1.2", "garage-032.4", "garage-031.10"])
def test_identifier_accepts_task_and_hierarchical_subtask_ids(value):
    assert board.identifier(value) == value


@pytest.mark.parametrize("value", ["garage-1", "garage-0311", "garage-031.", "garage-031.a", "garage-031..1",
                                   "garage-.1", "garage-031.1 ", "garage-031.1\n", "garage-031.\u0661",
                                   "garage-031" + ".1" * 40, "other-031.1", None, 31.1])
def test_identifier_rejects_malformed_or_oversized_ids(value):
    with pytest.raises(board.StateError):
        board.identifier(value)


@pytest.mark.parametrize("dependency", ["garage-031.", "garage-031..1"])
def test_malformed_subtask_dependency_is_honest_error(dependency):
    rows = [issue("garage-031.2", dependencies=[{"type": "blocks", "depends_on_id": dependency}])]
    status, _, body = board.route_response("GET", "/state.json", state_loader=lambda: board.build_state(rows, snapshot()))
    assert status == 503 and json.loads(body)["error"] == "El estado contiene un identificador inválido."


def test_detail_hash_route_accepts_subtask_ids():
    html = board.HTML_PATH.read_text()
    assert r"/^#garage-\d{3}(?:\.\d+)*$/.test(hash)" in html


@pytest.mark.parametrize("content", ["{bad", "[]", "null"])
def test_malformed_snapshot_is_honest_error(content):
    with pytest.raises(board.StateError):
        board.parse_snapshot(content)


def test_missing_files_and_partial_writes_return_honest_503_without_paths(tmp_path):
    issues = tmp_path / "issues.jsonl"
    snap = tmp_path / "snapshot.json"
    load = lambda: board.load_state(issues, snap)
    for write in [False, True]:
        if write:
            issues.write_text(json.dumps(issue()))
            snap.write_text("{")
        status, content_type, body = board.route_response("GET", "/state.json", state_loader=load)
        assert status == 503 and content_type.startswith("application/json")
        assert "error" in json.loads(body) and str(tmp_path).encode() not in body


def test_valid_local_files_load_and_endpoint_payload_is_sanitized(tmp_path):
    issues, snap = tmp_path / "tasks", tmp_path / "snapshot"
    issues.write_text(json.dumps(issue(owner="SECRET")))
    snap.write_text(json.dumps(snapshot(secret="SECRET")))
    status, content_type, body = board.route_response("GET", "/state.json", state_loader=lambda: board.load_state(issues, snap))
    assert status == 200 and content_type.startswith("application/json")
    assert json.loads(body)["counts"]["pending"] == 1 and b"SECRET" not in body


@pytest.mark.parametrize("target", ["/.env", "/../.env", "/%2e%2e/.env", "/tools/garage_progress.py", "/docs/", "/state.json?path=.env", "//", "/?file=.env"])
def test_unknown_and_traversal_routes_never_read_files(target):
    def forbidden():
        raise AssertionError("Unknown routes cannot read files")
    status, _, _ = board.route_response("GET", target, state_loader=forbidden, html_loader=forbidden)
    assert status == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def test_non_get_methods_never_read_files(method):
    def forbidden():
        raise AssertionError("Unsupported methods cannot read files")
    assert board.route_response(method, "/state.json", state_loader=forbidden)[0] == 405


def test_html_route_and_no_script_injection_from_dynamic_titles():
    assert board.route_response("GET", "/", html_loader=lambda: b"STATIC")[2] == b"STATIC"
    html = board.HTML_PATH.read_text()
    assert "textContent" in html and "innerHTML" not in html
    assert "setInterval(refresh,5000)" in html and "https://" not in html
    assert "<html lang=\"es\">" in html
    title = '</script><img src=x onerror="alert(1)">'
    result = board.build_state([issue(title=title)], snapshot())
    assert result["tasks"][0]["title"] == title
    # Untrusted strings are JSON data; the static page only assigns textContent.
    assert title not in html


@pytest.mark.parametrize("change", [{"agents": "invalid"}, {"validation": None}, {"not_applicable": "invalid"},
                                    {"not_applicable": ["garage-999"]}, {"validation": {"tests": True}}])
def test_invalid_snapshot_fields_are_not_silently_fabricated(change):
    with pytest.raises(board.StateError):
        board.build_state([issue()], snapshot(**change))


def test_server_factory_is_strict_numeric_loopback(monkeypatch):
    observed = []
    monkeypatch.setattr(board, "ThreadingHTTPServer", lambda address, handler: observed.append((address, handler)))
    board.create_server()
    board.create_server(8766)
    assert [entry[0] for entry in observed] == [("127.0.0.1", 8765), ("127.0.0.1", 8766)]
    assert all(entry[1] is board.ProgressHandler for entry in observed)
    for port in (0, -1, 65536, True, "8765"):
        with pytest.raises(ValueError):
            board.create_server(port)


def test_http_handler_sets_private_no_cache_headers_without_a_socket(monkeypatch):
    monkeypatch.setattr(board, "route_response", lambda method, target: (405, "text/plain; charset=utf-8", b"Denied"))
    handler = object.__new__(board.ProgressHandler)
    handler.command, handler.path, handler.wfile = "POST", "/", BytesIO()
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = {"Host": "127.0.0.1:8765"}
    captured = {}
    handler.send_response = lambda value: captured.update(status=value)
    handler.send_header = lambda key, value: captured.update({key: value})
    handler.end_headers = lambda: None
    handler.respond()
    assert captured["status"] == 405 and captured["Allow"] == "GET"
    assert captured["Cache-Control"] == "no-store"
    assert captured["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in captured["Content-Security-Policy"]
    assert captured["Content-Length"] == "6" and handler.wfile.getvalue() == b"Denied"


@pytest.mark.parametrize("changes", [{"status": []}, {"metadata": []}, {"metadata": {"phase": []}}])
def test_valid_json_with_malformed_schema_returns_json_503(changes):
    status, _, body = board.route_response("GET", "/state.json", state_loader=lambda: board.build_state([issue(**changes)], snapshot()))
    assert status == 503 and "error" in json.loads(body)


def test_handler_rejects_remote_host_before_reading_state(monkeypatch):
    def forbidden(*args):
        raise AssertionError("A nonlocal Host must not read local state")
    monkeypatch.setattr(board, "route_response", forbidden)
    handler = object.__new__(board.ProgressHandler)
    handler.command, handler.path, handler.wfile = "GET", "/state.json", BytesIO()
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = {"Host": "attacker.example:8765"}
    captured = {}
    handler.send_response = lambda value: captured.update(status=value)
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.respond()
    assert captured["status"] == 403


def test_detail_fields_are_whitelisted_redacted_multiline_and_not_truncated_at_300():
    text = "Línea de alcance\n" * 100 + "private@example.com /Users/private/.env"
    task = board.build_state([issue(description=text, acceptance_criteria="Criterio\nDos usuarios",
                                    notes="Revisión\nSin producción", priority=1, created_at="2026-10-04T12:00:00Z",
                                    metadata={"phase": "initial", "requested_model": "gpt-6.1-sol", "private": "TOKEN"},
                                    credentials="SECRET")], snapshot())["tasks"][0]
    assert len(task["description"]) > 300 and "\n" in task["description"]
    assert "private@example.com" not in task["description"] and "/Users/private" not in task["description"]
    assert task["acceptance_criteria"] == "Criterio\nDos usuarios" and task["notes"] == "Revisión\nSin producción"
    assert task["priority"] == 1 and task["model"] == "gpt-6.1-sol"
    assert "credentials" not in task and "private" not in task


@pytest.mark.parametrize("changes", [{"description": []}, {"acceptance_criteria": {}}, {"notes": True},
                                     {"priority": "P1"}, {"priority": True}, {"issue_type": []},
                                     {"created_at": []}, {"metadata": {"phase": "initial", "requested_model": []}}])
def test_malformed_detail_fields_return_honest_error(changes):
    status, _, body = board.route_response("GET", "/state.json", state_loader=lambda: board.build_state([issue(**changes)], snapshot()))
    assert status == 503 and "error" in json.loads(body)


def test_detail_ui_uses_hash_navigation_dialog_and_text_only():
    html = board.HTML_PATH.read_text()
    assert '<dialog id="detail"' in html and 'aria-labelledby="detail-title"' in html
    assert "hashchange" in html and "showModal()" in html and "cancel" in html
    assert "acceptance_criteria" in html and "notes" in html and "textContent" in html
    assert "innerHTML" not in html


@pytest.mark.parametrize("not_applicable", [[], ["garage-013"]])
def test_close_reason_is_public_detail_separate_from_planning_notes(not_applicable):
    task = board.build_state([issue("garage-013", status="closed", notes="Plan previo",
                                    close_reason="478 pruebas pasan\nMotivo private@example.com /Users/private/.env")],
                             snapshot(not_applicable=not_applicable))["tasks"][0]
    assert task["notes"] == "Plan previo" and "478 pruebas pasan\nMotivo" in task["close_reason"]
    assert "private@example.com" not in task["close_reason"] and "/Users/private" not in task["close_reason"]
    html = board.HTML_PATH.read_text()
    assert "Resultado del cierre" in html and "close_reason" in html


def test_public_text_preserves_public_urls_and_app_routes_while_redacting_secrets():
    text = "https://example.com/docs /garage/ docs/garage.md /Users/private/.env /tmp/secret C:\\Users\\private\\.env access_token=PRIVATE https://example.com/docs?token=PRIVATE"
    clean = board.public_text(text, 20000)
    assert "https://example.com/docs" in clean and "/garage/" in clean and "docs/garage.md" in clean
    assert "PRIVATE" not in clean and "/Users/private" not in clean and "/tmp/secret" not in clean
    assert "texto truncado" in board.public_text("x" * 30000, 20000)


def test_dependency_graph_layout_is_topological_deterministic_and_excludes_epics():
    tasks = [{"id": "garage-003", "dependencies": ["garage-001", "garage-002", "garage-000"]},
             {"id": "garage-001", "dependencies": []},
             {"id": "garage-002", "dependencies": ["garage-001"]},
             {"id": "garage-004", "dependencies": ["garage-999"]}]
    graph = board.dependency_graph(tasks, [{"id": "garage-000"}])
    assert graph == board.dependency_graph(list(reversed(tasks)), [{"id": "garage-000"}])
    positions = {node["id"]: node for node in graph["nodes"]}
    assert positions["garage-001"]["column"] == 0
    assert positions["garage-002"]["column"] == 1 and positions["garage-003"]["column"] == 2
    assert graph["edges"] == [{"from": "garage-001", "to": "garage-002"},
                              {"from": "garage-001", "to": "garage-003"},
                              {"from": "garage-002", "to": "garage-003"}]
    assert graph["missing"] == [{"from": "garage-999", "to": "garage-004"}]
    assert graph["cycle_nodes"] == [] and "garage-000" not in positions


def test_dependency_graph_detects_cycle_and_affected_descendants_without_hanging():
    graph = board.dependency_graph([{"id": "garage-001", "dependencies": ["garage-002"]},
                                    {"id": "garage-002", "dependencies": ["garage-001"]},
                                    {"id": "garage-003", "dependencies": ["garage-002"]},
                                    {"id": "garage-004", "dependencies": []}])
    assert graph["cycle_nodes"] == ["garage-001", "garage-002"]
    assert graph["cycle_affected"] == ["garage-001", "garage-002", "garage-003"]
    assert len(graph["nodes"]) == 4


def test_dependency_graph_cycle_cross_edges_include_all_members_not_downstream():
    graph = board.dependency_graph([{"id": "garage-001", "dependencies": ["garage-002", "garage-003"]},
                                    {"id": "garage-002", "dependencies": ["garage-001"]},
                                    {"id": "garage-003", "dependencies": ["garage-002"]},
                                    {"id": "garage-004", "dependencies": ["garage-003"]}])
    assert graph["cycle_nodes"] == ["garage-001", "garage-002", "garage-003"]
    assert graph["cycle_affected"] == ["garage-001", "garage-002", "garage-003", "garage-004"]


def test_graph_html_has_local_svg_and_accessible_view_switch():
    html = board.HTML_PATH.read_text()
    assert 'id="show-graph"' in html and 'id="show-list"' in html
    assert 'aria-pressed="true"' in html and "createElementNS" in html
    assert "Requisitos → tareas dependientes" in html and "marker-end" in html
    assert "los filtros de la lista no ocultan dependencias" in html


def test_html_revision_injected_matches_state_and_changes_with_template():
    template = b"STATIC const revision='__GARAGE_UI_REVISION__';"
    status, _, body = board.route_response("GET", "/", html_loader=lambda: template)
    assert status == 200 and b"__GARAGE_UI_REVISION__" not in body
    _, _, state_body = board.route_response("GET", "/state.json", state_loader=lambda: {"tasks": []}, html_loader=lambda: template)
    revision = json.loads(state_body)["ui_revision"]
    assert len(revision) == 64 and revision.encode() in body
    _, _, other_state = board.route_response("GET", "/state.json", state_loader=lambda: {"tasks": [], "focus": "Nueva tarea"}, html_loader=lambda: template)
    assert json.loads(other_state)["ui_revision"] == revision
    _, _, changed = board.route_response("GET", "/state.json", state_loader=lambda: {"tasks": []}, html_loader=lambda: template + b"NEW")
    assert json.loads(changed)["ui_revision"] != revision
    assert "STATIC" not in state_body.decode()


def test_template_revision_read_failure_is_honest_json_error_without_paths():
    def missing():
        raise FileNotFoundError("/Users/private/.env")
    status, _, body = board.route_response("GET", "/state.json", state_loader=lambda: {}, html_loader=missing)
    assert status == 503 and "/Users" not in body.decode()


def test_ui_revision_reload_and_dag_deep_link_are_visible_in_static_template():
    html = board.HTML_PATH.read_text()
    assert "__GARAGE_UI_REVISION__" in html and "data.ui_revision !== UI_REVISION" in html
    assert "location.reload()" in html and 'href="#dag"' in html
    assert "Ver DAG" in html and "DAG de dependencias" in html
    assert "Revisión de interfaz inválida" in html
    assert "sessionStorage.getItem('garage-progress-view')==='graph'" in html
    assert "switchView(restoredGraph)" in html
    assert "location.pathname+($('graph-view').hidden?'':'#dag')" in html
