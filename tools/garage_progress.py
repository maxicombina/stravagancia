"""Read-only local Garage board. Run: python tools/garage_progress.py [--port 8765]."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
ISSUES_PATH = ROOT / ".beads" / "issues.jsonl"
SNAPSHOT_PATH = ROOT / "docs" / "garage-progress-state.json"
HTML_PATH = Path(__file__).with_suffix(".html")
STATES = ("completed", "in_progress", "pending", "future", "not_applicable")
# Beads hierarchical sub-tasks (garage-031.1, garage-031.1.2) are ordinary rows.
ID = re.compile(r"garage-\d{3}(?:\.\d+)*\Z", re.ASCII)
ID_MAX_LENGTH = 64


class StateError(ValueError):
    """Invalid or unavailable local state, without leaking paths or content."""


def public_text(value, limit=300):
    if not isinstance(value, str):
        raise StateError("El estado contiene un campo de texto inválido.")
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", value)
    def redact_url(match):
        try:
            parsed = urlsplit(match.group())
            hostname = parsed.hostname or ""
            if parsed.port:
                hostname += f":{parsed.port}"
            query = [(key, "[omitido]" if any(word in key.lower() for word in ("token", "key", "secret", "password")) else content)
                     for key, content in parse_qsl(parsed.query, keep_blank_values=True)]
            return urlunsplit((parsed.scheme, hostname, parsed.path, urlencode(query), parsed.fragment))
        except ValueError:
            return "[URL inválida omitida]"
    value = re.sub(r"https?://[^\s<>\]\)]+", redact_url, value)
    value = re.sub(r"(?<![\w<])(?:/(?:Users|home|private|tmp|var|etc|opt|usr|root|Volumes)(?:/[^\s,;\]\)]*)?|[A-Za-z]:[\\/][^\s,;\]\)]+)", "[ruta omitida]", value)
    value = re.sub(r"(?i)\b([\w]*(?:access_token|refresh_token|api_key|password|secret|DATABASE_URL))\s*[:=]\s*[^\s,;]+", r"\1=[omitido]", value)
    clean = "".join(c for c in value if c.isprintable() or c == "\n")
    marker = "… [texto truncado]"
    return clean if len(clean) <= limit else clean[:max(0, limit - len(marker))] + marker


def identifier(value):
    if not isinstance(value, str) or len(value) > ID_MAX_LENGTH or not ID.fullmatch(value):
        raise StateError("El estado contiene un identificador inválido.")
    return value


def optional_text(value, limit=300):
    return "" if value is None else public_text(value, limit)


def dependency_graph(tasks, epics=()):
    """Deterministic DAG columns; cyclic components remain visible in one column."""
    ids = {task["id"] for task in tasks}
    epic_ids = {epic["id"] for epic in epics}
    parents = {task["id"]: set(task["dependencies"]) & ids for task in tasks}
    edges = [{"from": parent, "to": child} for child in sorted(ids) for parent in sorted(parents[child])]
    missing = [{"from": dep, "to": task["id"]} for task in tasks
               for dep in task["dependencies"] if dep not in ids | epic_ids]
    levels, remaining = {}, set(ids)
    while remaining:
        ready = sorted(node for node in remaining if parents[node].issubset(levels))
        if not ready:
            break
        for node in ready:
            levels[node] = max((levels[parent] + 1 for parent in parents[node]), default=0)
            remaining.remove(node)
    cycles = set()
    for node in sorted(ids):
        frontier, visited = list(parents[node]), set()
        while frontier:
            parent = frontier.pop()
            if parent == node:
                cycles.add(node)
                break
            if parent not in visited:
                visited.add(parent)
                frontier.extend(parents[parent])
    cycle_column = max(levels.values(), default=-1) + 1
    for node in remaining:
        levels[node] = cycle_column
    rows, nodes = {}, []
    for node in sorted(ids, key=lambda value: (levels[value], value)):
        column = levels[node]
        row = rows.get(column, 0)
        rows[column] = row + 1
        nodes.append({"id": node, "column": column, "row": row})
    return {"nodes": nodes, "edges": edges, "cycle_nodes": sorted(cycles),
            "cycle_affected": sorted(remaining), "missing": sorted(missing, key=lambda value: (value["to"], value["from"]))}


def parse_issues(content):
    rows, seen = [], set()
    try:
        for line in content.splitlines():
            if not line.strip():
                continue
            issue = json.loads(line)
            if not isinstance(issue, dict):
                raise StateError("La exportación de tareas contiene un registro inválido.")
            issue_id = issue.get("id")
            if isinstance(issue_id, str) and not issue_id.startswith("garage-"):
                continue
            identifier(issue_id)
            if issue_id in seen:
                raise StateError("La exportación de tareas contiene identificadores repetidos.")
            seen.add(issue_id)
            rows.append(issue)
    except json.JSONDecodeError:
        raise StateError("La exportación de tareas no contiene JSON válido.") from None
    if not rows:
        raise StateError("La exportación no contiene tareas Garage.")
    return rows


def parse_snapshot(content):
    try:
        snapshot = json.loads(content)
    except json.JSONDecodeError:
        raise StateError("El snapshot del coordinador no contiene JSON válido.") from None
    if not isinstance(snapshot, dict):
        raise StateError("El snapshot del coordinador no es un objeto.")
    return snapshot


def build_state(issues, snapshot):
    not_applicable = snapshot.get("not_applicable", [])
    if not isinstance(not_applicable, list):
        raise StateError("La lista de tareas no aplicables es inválida.")
    excluded = {identifier(value) for value in not_applicable}
    tasks, epics = [], []
    resolved = {}
    for row in issues:
        issue_id = identifier(row.get("id"))
        status = row.get("status")
        if not isinstance(status, str) or status not in {"open", "in_progress", "closed", "blocked", "deferred"}:
            raise StateError("Una tarea contiene un estado desconocido.")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            raise StateError("Una tarea contiene metadatos inválidos.")
        phase = metadata.get("phase", "initial")
        if not isinstance(phase, str) or phase not in {"initial", "future"}:
            raise StateError("Una tarea contiene una fase desconocida.")
        if issue_id in excluded and status != "closed":
            raise StateError("Una tarea no aplicable debe estar cerrada.")
        board_status = ("not_applicable" if issue_id in excluded else
                        "completed" if status == "closed" else
                        "in_progress" if status == "in_progress" else
                        "future" if phase == "future" else "pending")
        resolved[issue_id] = board_status
        dependencies = row.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise StateError("Una tarea contiene dependencias inválidas.")
        deps = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise StateError("Una tarea contiene una dependencia inválida.")
            if dependency.get("type") == "blocks":
                deps.add(identifier(dependency.get("depends_on_id")))
        task = {"id": issue_id, "title": public_text(row.get("title")),
                "status": board_status, "phase": phase, "dependencies": sorted(deps),
                "explicitly_blocked": status == "blocked"}
        priority = row.get("priority")
        if priority is not None and (type(priority) is not int or not 0 <= priority <= 4):
            raise StateError("Una tarea contiene una prioridad inválida.")
        requested_model = optional_text(metadata.get("requested_model"), 100)
        suggested_model = optional_text(metadata.get("suggested_model"), 100)
        task.update({"priority": priority, "type": public_text(row.get("issue_type", "task"), 40),
                     "description": optional_text(row.get("description"), 20000),
                     "acceptance_criteria": optional_text(row.get("acceptance_criteria"), 20000),
                     "notes": optional_text(row.get("notes"), 20000),
                     "close_reason": optional_text(row.get("close_reason"), 20000),
                     "model": requested_model or suggested_model})
        for key in ("created_at", "updated_at", "closed_at"):
            task[key] = optional_text(row.get(key), 100)
        (epics if row.get("issue_type") == "epic" else tasks).append(task)
    if not excluded.issubset(resolved):
        raise StateError("Hay tareas no aplicables ausentes de la exportación.")
    for task in tasks + epics:
        terminal = task["status"] in {"completed", "not_applicable"}
        task["blockers"] = [] if terminal else [dep for dep in task["dependencies"]
                                               if resolved.get(dep) not in {"completed", "not_applicable"}]
        if terminal:
            task["explicitly_blocked"] = False
        task["missing_dependencies"] = [dep for dep in task["dependencies"] if dep not in resolved]
    agents = snapshot.get("agents", [])
    if not isinstance(agents, list):
        raise StateError("La lista de agentes es inválida.")
    public_agents = []
    for agent in agents:
        if not isinstance(agent, dict):
            raise StateError("El snapshot contiene un agente inválido.")
        public_agents.append({key: public_text(agent.get(key, ""))
                              for key in ("name", "role", "status", "task")})
    validation = snapshot.get("validation")
    if not isinstance(validation, dict):
        raise StateError("Falta el último resultado de validación.")
    public_validation = {}
    for key in ("tests", "passed", "failed", "skipped"):
        value = validation.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise StateError("Un recuento de validación es inválido.")
        public_validation[key] = value
    for key in ("postgres", "checked_at"):
        public_validation[key] = public_text(validation.get(key, ""))
    return {"updated_at": public_text(snapshot.get("updated_at", "")),
            "focus": public_text(snapshot.get("focus", "")),
            "tasks": sorted(tasks, key=lambda row: row["id"]),
            "epics": sorted(epics, key=lambda row: row["id"]),
            "counts": {state: sum(task["status"] == state for task in tasks) for state in STATES},
            "agents": public_agents, "validation": public_validation,
            "graph": dependency_graph(tasks, epics)}


def load_state(issues_path=ISSUES_PATH, snapshot_path=SNAPSHOT_PATH):
    try:
        issues = parse_issues(issues_path.read_text(encoding="utf-8"))
        snapshot = parse_snapshot(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        raise StateError("No se pueden leer los archivos locales de progreso.") from None
    return build_state(issues, snapshot)


def route_response(method, target, state_loader=load_state, html_loader=None):
    """Pure routing permits isolated tests without opening HTTP sockets."""
    if method != "GET":
        return 405, "text/plain; charset=utf-8", b"Metodo no permitido."
    if target == "/":
        try:
            content = (html_loader or (lambda: HTML_PATH.read_bytes()))()
        except OSError:
            return 503, "text/plain; charset=utf-8", b"Tablero local no disponible."
        revision = hashlib.sha256(content).hexdigest().encode("ascii")
        content = content.replace(b"__GARAGE_UI_REVISION__", revision)
        return 200, "text/html; charset=utf-8", content
    if target == "/state.json":
        try:
            state = state_loader()
            template = (html_loader or (lambda: HTML_PATH.read_bytes()))()
            state = {**state, "ui_revision": hashlib.sha256(template).hexdigest()}
        except StateError as error:
            return 503, "application/json; charset=utf-8", json.dumps({"error": str(error)}).encode()
        except OSError:
            return 503, "application/json; charset=utf-8", json.dumps({"error": "No se puede leer la interfaz local del tablero."}).encode()
        return 200, "application/json; charset=utf-8", json.dumps(state, ensure_ascii=False).encode()
    return 404, "text/plain; charset=utf-8", b"Ruta no encontrada."


class ProgressHandler(BaseHTTPRequestHandler):
    def respond(self):
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            status, content_type, body = 403, "text/plain; charset=utf-8", b"Host local requerido."
        else:
            status, content_type, body = route_response(self.command, self.path)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; frame-ancestors 'none'")
        if status == 405:
            self.send_header("Allow", "GET")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = respond
    do_POST = respond
    do_PUT = respond
    do_DELETE = respond
    do_PATCH = respond
    do_HEAD = respond
    do_OPTIONS = respond

    def log_message(self, format, *args):
        # Request targets may contain secrets; do not print arbitrary paths.
        pass


def create_server(port=8765):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535.")
    return ThreadingHTTPServer(("127.0.0.1", port), ProgressHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with create_server(args.port) as server:
        print(f"Garage: http://127.0.0.1:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
