from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

from mech_pipeline.decl_validation import prevalidate_theorem_decl
from mech_pipeline.utils import ensure_dir, normalize_lean_text, safe_stem, truncate

_SUBPROCESS_TEXT_ENCODING = "utf-8"
_SUBPROCESS_TEXT_ERRORS = "replace"
_LEAN_ERROR_LOC_RE = re.compile(r":(?P<line>\d+):(?P<col>\d+):\s*error:\s*(?P<msg>[^\n]+)")


def _indent(text: str, n: int = 2) -> str:
    prefix = " " * n
    return "\n".join(prefix + line if line.strip() else prefix for line in text.splitlines())


def _strip_code_fence(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    return out


def _declaration_only(theorem_decl: str) -> str:
    out = _strip_code_fence(theorem_decl)
    if ":=" in out:
        out = out.split(":=", 1)[0].rstrip()
    if out.endswith(" by"):
        out = out[:-3].rstrip()
    return out


def _is_decl_shape_valid(theorem_decl: str) -> bool:
    decl = _declaration_only(theorem_decl)
    if not re.match(r"^\s*(theorem|lemma)\s+", decl):
        return False
    return ":" in decl


def _strip_pipeline_markers(text: str) -> str:
    out = normalize_lean_text(str(text or ""))
    out = out.replace("[PIPELINE_TIMEOUT]", "")
    out = re.sub(r"\[PIPELINE_EXCEPTION][^\n]*", "", out)
    return out.strip()


def _warning_lines(stdout: str, stderr: str) -> list[str]:
    merged = normalize_lean_text("\n".join(part for part in [stderr, stdout] if part).strip())
    lines: list[str] = []
    for raw in merged.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if "warning:" in lowered or "local changes" in lowered:
            lines.append(line)
    return lines


def classify_timeout_sub_error(stdout: str, stderr: str) -> str:
    body = _strip_pipeline_markers(stderr or stdout)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return "empty_stderr_timeout"
    lowered = [line.lower() for line in lines]
    warning_only = all("warning:" in line or "local changes" in line for line in lowered)
    if warning_only:
        return "timeout_after_warning"
    return "timeout_or_tooling_block"


def _timeout_failure_details(
    *,
    stdout: str,
    stderr: str,
    timeout_s: int,
    backend: str | None,
    route_fallback_used: bool,
) -> dict[str, object]:
    body = _strip_pipeline_markers(stderr or stdout)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    lowered = [line.lower() for line in lines]
    return {
        "timeout_s": timeout_s,
        "backend_used": backend,
        "stderr_was_empty": not bool(lines),
        "stderr_had_warning_before_timeout": bool(lines)
        and all("warning:" in line or "local changes" in line for line in lowered),
        "route_fallback_used": route_fallback_used,
    }

def classify_lean_error(stderr: str) -> tuple[bool, bool, str]:
    text = stderr.lower()
    if "pipeline_timeout" in text:
        return (True, False, "elaboration_failure")
    if any(token in text for token in ["unexpected token", "parse error", "invalid syntax"]):
        return (False, False, "invalid_lean_syntax")
    if any(
        token in text
        for token in ["unknown namespace", "unknown constant", "unknown package", "invalid field"]
    ):
        return (True, False, "missing_import_or_namespace")
    return (True, False, "elaboration_failure")


def is_strict_clean(code: str, blocklist: list[str]) -> bool:
    lowered = code.lower()
    for token in blocklist:
        if re.search(rf"\b{re.escape(token.lower())}\b", lowered):
            return False
    return True


def _stderr_excerpt(stdout: str, stderr: str, limit: int = 240) -> str:
    merged = (stderr or "").strip()
    if not merged:
        merged = (stdout or "").strip()
    return truncate(normalize_lean_text(merged), limit)


def extract_lean_error_details(stdout: str, stderr: str) -> dict[str, str | int | None]:
    normalized = normalize_lean_text((stderr or "").strip() or (stdout or "").strip())
    excerpt = truncate(normalized, 240)
    line: int | None = None
    message: str | None = None
    snippet: str | None = None

    match = _LEAN_ERROR_LOC_RE.search(normalized)
    if match:
        line = int(match.group("line"))
        message = match.group("msg").strip()
        snippet = truncate(match.group(0).strip(), 240)
    else:
        first_line = next((part.strip() for part in normalized.splitlines() if part.strip()), "")
        if first_line:
            message = truncate(first_line, 240)
            snippet = message

    return {
        "stderr_excerpt": excerpt or None,
        "error_line": line,
        "error_message": message,
        "error_snippet": snippet,
    }


def classify_compile_sub_error(error_type: str | None, stderr: str) -> str | None:
    text = (stderr or "").lower()
    if "[pipeline_timeout]" in text:
        return classify_timeout_sub_error("", stderr)
    if "[pipeline_exception]" in text:
        return "timeout_or_tooling_block"
    if error_type == "invalid_lean_syntax":
        return "invalid_decl_shape"
    if any(token in text for token in ["unknown namespace", "unknown package", "unknown module prefix"]) and "error:" in text:
        return "namespace_or_import_issue"
    if "unknown constant" in text or "unknown identifier" in text:
        return "symbol_hallucination"
    if "function expected at" in text or "invalid field notation" in text:
        return "wrong_api_shape"
    if "application type mismatch" in text or "type mismatch" in text:
        return "type_mismatch"
    if error_type == "missing_import_or_namespace":
        return "namespace_or_import_issue"
    if error_type == "elaboration_failure":
        return "type_mismatch"
    return None


class LeanRunner:
    def __init__(
        self,
        physlean_dir: Path,
        timeout_s: int,
        strict_blocklist: list[str],
        lean_header: str,
        enabled: bool = True,
        mechlib_dir: Path | None = None,
        route_policy: str = "auto_by_import",
        default_backend: str = "physlean",
        route_fallback: bool = True,
    ) -> None:
        self.physlean_dir = Path(physlean_dir)
        self.mechlib_dir = Path(mechlib_dir) if mechlib_dir else None
        self.timeout_s = timeout_s
        self.strict_blocklist = strict_blocklist
        self.lean_header = lean_header
        self.enabled = enabled
        self.route_policy = route_policy
        self.default_backend = default_backend
        self.route_fallback = route_fallback
        self._mechlib_ready = bool(self.mechlib_dir and self.mechlib_dir.exists())

    def _run_lean(self, *, root_dir: Path, rel_file: Path) -> tuple[bool, str, str]:
        root = root_dir.resolve()
        target = rel_file.resolve() if rel_file.is_absolute() else (root / rel_file).resolve()
        try:
            arg_path = target.relative_to(root)
        except ValueError:
            arg_path = target
        arg = arg_path.as_posix()
        try:
            proc = subprocess.run(
                ["lake", "env", "lean", arg],
                cwd=root,
                capture_output=True,
                text=True,
                encoding=_SUBPROCESS_TEXT_ENCODING,
                errors=_SUBPROCESS_TEXT_ERRORS,
                timeout=self.timeout_s,
                check=False,
            )
            return (proc.returncode == 0, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return (False, stdout, f"{stderr}\n[PIPELINE_TIMEOUT]")
        except Exception as exc:  # pragma: no cover
            return (False, "", f"[PIPELINE_EXCEPTION] {type(exc).__name__}: {exc}")

    def _stderr_digest(self, stdout: str, stderr: str) -> str:
        merged = (stderr or "").strip()
        if not merged:
            merged = (stdout or "").strip()
        return truncate(normalize_lean_text(merged), 800)

    def _backend_root(self, backend: str) -> Path:
        if backend == "mechlib":
            if self.mechlib_dir is None:
                raise RuntimeError("mechlib_dir is not configured")
            return self.mechlib_dir
        return self.physlean_dir

    def _backend_probe(self, backend: str) -> Path:
        if backend == "mechlib":
            return Path("MechLib/Mechanics/Dynamics.lean")
        return Path("PhysLean/ClassicalMechanics/Basic.lean")

    def _backend_exists(self, backend: str) -> bool:
        try:
            root = self._backend_root(backend)
        except RuntimeError:
            return False
        return root.exists() and (root / "lakefile.toml").exists() and (root / "lean-toolchain").exists()

    def _uses_mechlib(self, lean_header: str, theorem_decl: str) -> bool:
        header = lean_header or ""
        if "import MechLib" in header or "open MechLib" in header:
            return True
        return "MechLib." in theorem_decl

    def _uses_physlean(self, lean_header: str, theorem_decl: str) -> bool:
        header = lean_header or ""
        if "import PhysLean" in header or "open PhysLean" in header:
            return True
        return "PhysLean." in theorem_decl

    def _route_backend(self, lean_header: str, theorem_decl: str) -> tuple[str, str]:
        if self.route_policy == "force_mechlib":
            return ("mechlib", "force_mechlib")
        if self.route_policy == "force_physlean":
            return ("physlean", "force_physlean")
        # auto_by_import
        if self._uses_mechlib(lean_header, theorem_decl):
            return ("mechlib", "auto_import_mechlib")
        if self._uses_physlean(lean_header, theorem_decl):
            return ("physlean", "auto_import_physlean")
        return (self.default_backend, f"auto_default_{self.default_backend}")

    def _effective_header(self, lean_header: str, backend: str) -> str:
        header = (lean_header or self.lean_header).strip()
        if backend == "mechlib" and "import MechLib" not in header:
            return f"import MechLib\n{header}".strip()
        if backend == "physlean" and "import PhysLean" not in header:
            return f"import PhysLean\n{header}".strip()
        return header

    def preflight(self) -> tuple[bool, str | None, str]:
        details = self.preflight_details()
        return (
            bool(details["ok"]),
            str(details["error_type"]) if details.get("error_type") else None,
            str(details["message"]),
        )

    def preflight_details(self) -> dict[str, object]:
        if not self.enabled:
            return {
                "ok": True,
                "error_type": None,
                "message": "lean disabled by config",
                "environment_health": "clean",
                "environment_warnings": [],
            }
        if not self._backend_exists("physlean"):
            return {
                "ok": False,
                "error_type": "physlean_missing",
                "message": f"missing or invalid path: {self.physlean_dir}",
                "environment_health": "warning_only",
                "environment_warnings": [],
            }

        ok, stdout, stderr = self._run_lean(
            root_dir=self.physlean_dir,
            rel_file=self._backend_probe("physlean"),
        )
        warnings = _warning_lines(stdout, stderr)
        if not ok:
            return {
                "ok": False,
                "error_type": "physlean_env_error",
                "message": f"physlean preflight failed: {truncate(stderr, 800)}",
                "environment_health": "dirty_packages"
                if any("local changes" in line.lower() for line in warnings)
                else ("warning_only" if warnings else "clean"),
                "environment_warnings": warnings,
            }

        if self.route_policy == "force_mechlib":
            if not self._backend_exists("mechlib"):
                return {
                    "ok": False,
                    "error_type": "physlean_env_error",
                    "message": f"mechlib backend required but missing: {self.mechlib_dir}",
                    "environment_health": "warning_only" if warnings else "clean",
                    "environment_warnings": warnings,
                }
            ok_m, stdout_m, stderr_m = self._run_lean(
                root_dir=self._backend_root("mechlib"),
                rel_file=self._backend_probe("mechlib"),
            )
            warnings.extend(_warning_lines(stdout_m, stderr_m))
            if not ok_m:
                return {
                    "ok": False,
                    "error_type": "physlean_env_error",
                    "message": f"mechlib preflight failed: {truncate(stderr_m, 800)}",
                    "environment_health": "dirty_packages"
                    if any("local changes" in line.lower() for line in warnings)
                    else ("warning_only" if warnings else "clean"),
                    "environment_warnings": warnings,
                }
            self._mechlib_ready = True
            return {
                "ok": True,
                "error_type": None,
                "message": "ok: physlean+mechlib",
                "environment_health": "dirty_packages"
                if any("local changes" in line.lower() for line in warnings)
                else ("warning_only" if warnings else "clean"),
                "environment_warnings": warnings,
            }

        if self._backend_exists("mechlib"):
            ok_m, stdout_m, stderr_m = self._run_lean(
                root_dir=self._backend_root("mechlib"),
                rel_file=self._backend_probe("mechlib"),
            )
            warnings.extend(_warning_lines(stdout_m, stderr_m))
            self._mechlib_ready = ok_m
        else:
            self._mechlib_ready = False

        message = "ok: physlean+mechlib" if self._mechlib_ready else "ok: physlean (mechlib unavailable)"
        return {
            "ok": True,
            "error_type": None,
            "message": message,
            "environment_health": "dirty_packages"
            if any("local changes" in line.lower() for line in warnings)
            else ("warning_only" if warnings else "clean"),
            "environment_warnings": warnings,
        }

    def _compile_once(
        self,
        *,
        backend: str,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        run_dir: Path,
    ) -> dict[str, str | bool | None]:
        root_dir = self._backend_root(backend)
        run_base = run_dir.resolve()
        compile_dir = run_base / "lean_compile"
        ensure_dir(compile_dir)
        stem = safe_stem(f"{sample_id}_{candidate_id}")
        log_path = compile_dir / f"{stem}_{backend}.log"

        decl = _declaration_only(theorem_decl)
        header = self._effective_header(lean_header, backend)
        code = f"{header}\n\n{decl} := by\n  sorry\n"
        tmp_dir = run_base / ".pipeline1_tmp" / "compile" / backend
        ensure_dir(tmp_dir)
        tmp_file = tmp_dir / f"{stem}.lean"
        tmp_file.write_text(code, encoding="utf-8")

        ok, stdout, stderr = self._run_lean(root_dir=root_dir, rel_file=tmp_file)
        log_path.write_text(
            f"backend={backend}\nreturncode={0 if ok else 1}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n",
            encoding="utf-8",
        )
        if ok:
            return {
                "compile_pass": True,
                "syntax_ok": True,
                "elaboration_ok": True,
                "error_type": None,
                "stderr_digest": "",
                "log_path": str(log_path),
                "backend_used": backend,
                "stderr_excerpt": None,
                "error_line": None,
                "error_message": None,
                "error_snippet": None,
                "sub_error_type": None,
            }

        syntax_ok, elaboration_ok, error_type = classify_lean_error(stderr)
        details = extract_lean_error_details(stdout, stderr)
        sub_error_type = classify_compile_sub_error(error_type, stderr)
        failure_details: dict[str, object] = {
            "stderr_excerpt": details["stderr_excerpt"],
            "error_line": details["error_line"],
            "error_message": details["error_message"],
            "error_snippet": details["error_snippet"],
        }
        if sub_error_type in {"empty_stderr_timeout", "timeout_after_warning", "timeout_or_tooling_block"}:
            failure_details.update(
                _timeout_failure_details(
                    stdout=stdout,
                    stderr=stderr,
                    timeout_s=self.timeout_s,
                    backend=backend,
                    route_fallback_used=False,
                )
            )
        return {
            "compile_pass": False,
            "syntax_ok": syntax_ok,
            "elaboration_ok": elaboration_ok,
            "error_type": error_type,
            "stderr_digest": self._stderr_digest(stdout, stderr),
            "log_path": str(log_path),
            "backend_used": backend,
            "stderr_excerpt": details["stderr_excerpt"],
            "error_line": details["error_line"],
            "error_message": details["error_message"],
            "error_snippet": details["error_snippet"],
            "sub_error_type": sub_error_type,
            "failure_summary": (
                "Lean timed out before returning diagnostics."
                if sub_error_type == "empty_stderr_timeout"
                else ("Lean timed out after emitting warnings." if sub_error_type == "timeout_after_warning" else details["error_message"])
            ),
            "failure_details": failure_details,
        }

    def _verify_once(
        self,
        *,
        backend: str,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        proof_body: str,
        run_dir: Path,
    ) -> dict[str, str | bool | None]:
        root_dir = self._backend_root(backend)
        run_base = run_dir.resolve()
        proof_dir = run_base / "lean_proof"
        ensure_dir(proof_dir)
        stem = safe_stem(f"{sample_id}_{candidate_id}")
        log_path = proof_dir / f"{stem}_{backend}.log"

        decl = _declaration_only(theorem_decl)
        header = self._effective_header(lean_header, backend)
        proof = _strip_code_fence(proof_body).replace("\r\n", "\n")
        proof = textwrap.dedent(proof).lstrip()
        if proof.startswith("by\n"):
            proof = proof[3:]
        elif proof.startswith("by "):
            proof = proof[3:].lstrip()
        elif proof == "by":
            proof = ""
        proof = proof.strip("\n")
        if not proof:
            proof = "trivial"

        code = f"{header}\n\n{decl} := by\n{_indent(proof)}\n"
        tmp_dir = run_base / ".pipeline1_tmp" / "proof" / backend
        ensure_dir(tmp_dir)
        tmp_file = tmp_dir / f"{stem}.lean"
        tmp_file.write_text(code, encoding="utf-8")

        ok, stdout, stderr = self._run_lean(root_dir=root_dir, rel_file=tmp_file)
        log_path.write_text(
            f"backend={backend}\nreturncode={0 if ok else 1}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n",
            encoding="utf-8",
        )

        strict_pass = ok and is_strict_clean(code, self.strict_blocklist)
        if ok and strict_pass:
            return {
                "compile_pass": True,
                "strict_pass": True,
                "error_type": None,
                "stderr_digest": "",
                "log_path": str(log_path),
                "backend_used": backend,
                "stderr_excerpt": None,
                "error_line": None,
                "error_message": None,
                "error_snippet": None,
            }
        if ok and not strict_pass:
            return {
                "compile_pass": True,
                "strict_pass": False,
                "error_type": "partially_correct_but_unverifiable",
                "stderr_digest": "",
                "log_path": str(log_path),
                "backend_used": backend,
                "stderr_excerpt": None,
                "error_line": None,
                "error_message": None,
                "error_snippet": None,
            }

        _syntax_ok, _elaboration_ok, error_type = classify_lean_error(stderr)
        details = extract_lean_error_details(stdout, stderr)
        sub_error_type = classify_compile_sub_error(error_type, stderr)
        failure_details: dict[str, object] = {
            "error_line": details["error_line"],
            "error_message": details["error_message"],
            "error_snippet": details["error_snippet"],
            "stderr_excerpt": details["stderr_excerpt"],
        }
        if sub_error_type in {"empty_stderr_timeout", "timeout_after_warning", "timeout_or_tooling_block"}:
            failure_details.update(
                _timeout_failure_details(
                    stdout=stdout,
                    stderr=stderr,
                    timeout_s=self.timeout_s,
                    backend=backend,
                    route_fallback_used=False,
                )
            )
        return {
            "compile_pass": False,
            "strict_pass": False,
            "error_type": error_type or "proof_search_failure",
            "stderr_digest": self._stderr_digest(stdout, stderr),
            "log_path": str(log_path),
            "backend_used": backend,
            "stderr_excerpt": details["stderr_excerpt"],
            "error_line": details["error_line"],
            "error_message": details["error_message"],
            "error_snippet": details["error_snippet"],
            "sub_error_type": sub_error_type,
            "failure_summary": (
                "Lean timed out before returning diagnostics."
                if sub_error_type == "empty_stderr_timeout"
                else ("Lean timed out after emitting warnings." if sub_error_type == "timeout_after_warning" else details["error_message"])
            ),
            "failure_details": failure_details,
        }

    def compile_statement(
        self,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        run_dir: Path,
    ) -> dict[str, str | bool | None]:
        if not self.enabled:
            compile_dir = run_dir / "lean_compile"
            ensure_dir(compile_dir)
            log_path = compile_dir / f"{safe_stem(f'{sample_id}_{candidate_id}')}.log"
            log_path.write_text("lean disabled by config\n", encoding="utf-8")
            return {
                "compile_pass": False,
                "syntax_ok": False,
                "elaboration_ok": False,
                "error_type": "lean_disabled",
                "stderr_digest": "",
                "log_path": str(log_path),
                "backend_used": None,
                "route_reason": "lean_disabled",
                "route_fallback_used": False,
                "stderr_excerpt": None,
                "error_line": None,
                "error_message": None,
                "error_snippet": None,
                "sub_error_type": "lean_disabled",
            }

        decl = _declaration_only(theorem_decl)
        validation = prevalidate_theorem_decl(theorem_decl)
        if validation is not None:
            compile_dir = run_dir / "lean_compile"
            ensure_dir(compile_dir)
            log_path = compile_dir / f"{safe_stem(f'{sample_id}_{candidate_id}')}.log"
            log_path.write_text(
                f"pre-lean declaration validation failed\nreason={validation['validation_reason']}\nexcerpt={validation['validation_excerpt']}\n",
                encoding="utf-8",
            )
            return {
                "compile_pass": False,
                "syntax_ok": False,
                "elaboration_ok": False,
                "error_type": "elaboration_failure",
                "stderr_digest": "pre-lean declaration validation failed",
                "log_path": str(log_path),
                "backend_used": None,
                "route_reason": "prelean_validation",
                "route_fallback_used": False,
                "stderr_excerpt": validation["validation_excerpt"],
                "error_line": None,
                "error_message": "pre-lean declaration validation failed",
                "error_snippet": validation["validation_excerpt"],
                "sub_error_type": "invalid_decl_shape",
                "failure_summary": "pre-lean declaration validation failed",
                "failure_details": {
                    "validation_reason": validation["validation_reason"],
                    "validation_excerpt": validation["validation_excerpt"],
                },
            }

        backend, route_reason = self._route_backend(lean_header, decl)
        if backend == "mechlib" and not self._mechlib_ready:
            backend = "physlean"
            route_reason = f"{route_reason}_fallback_physlean_mechlib_unavailable"
        first = self._compile_once(
            backend=backend,
            sample_id=sample_id,
            candidate_id=candidate_id,
            lean_header=lean_header,
            theorem_decl=decl,
            run_dir=run_dir,
        )
        first["route_reason"] = route_reason
        first["route_fallback_used"] = False
        if bool(first["compile_pass"]):
            return first

        fallback_used = False
        if self.route_fallback and self.default_backend != backend and self._backend_exists(self.default_backend):
            fallback = self._compile_once(
                backend=self.default_backend,
                sample_id=sample_id,
                candidate_id=candidate_id,
                lean_header=lean_header,
                theorem_decl=decl,
                run_dir=run_dir,
            )
            fallback_used = True
            if bool(fallback["compile_pass"]):
                fallback["route_reason"] = f"{route_reason}_fallback_{self.default_backend}"
                fallback["route_fallback_used"] = True
                return fallback
            first["stderr_digest"] = (
                f"{first.get('stderr_digest', '')}\n[FALLBACK {self.default_backend}] "
                f"{fallback.get('stderr_digest', '')}"
            ).strip()

        first["route_fallback_used"] = fallback_used
        if first.get("sub_error_type") in {"empty_stderr_timeout", "timeout_after_warning", "timeout_or_tooling_block"}:
            failure_details = dict(first.get("failure_details") or {})
            failure_details["route_fallback_used"] = fallback_used
            first["failure_details"] = failure_details
        return first

    def verify_proof(
        self,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        proof_body: str,
        run_dir: Path,
    ) -> dict[str, str | bool | None]:
        if not self.enabled:
            proof_dir = run_dir / "lean_proof"
            ensure_dir(proof_dir)
            log_path = proof_dir / f"{safe_stem(f'{sample_id}_{candidate_id}')}.log"
            log_path.write_text("lean disabled by config\n", encoding="utf-8")
            return {
                "compile_pass": False,
                "strict_pass": False,
                "error_type": "lean_disabled",
                "stderr_digest": "",
                "log_path": str(log_path),
                "backend_used": None,
                "route_reason": "lean_disabled",
                "route_fallback_used": False,
                "stderr_excerpt": None,
                "error_line": None,
                "error_message": None,
                "error_snippet": None,
                "sub_error_type": "lean_disabled",
                "failure_summary": "Lean verification disabled by config.",
                "failure_details": {},
            }

        decl = _declaration_only(theorem_decl)
        backend, route_reason = self._route_backend(lean_header, decl)
        if backend == "mechlib" and not self._mechlib_ready:
            backend = "physlean"
            route_reason = f"{route_reason}_fallback_physlean_mechlib_unavailable"

        first = self._verify_once(
            backend=backend,
            sample_id=sample_id,
            candidate_id=candidate_id,
            lean_header=lean_header,
            theorem_decl=decl,
            proof_body=proof_body,
            run_dir=run_dir,
        )
        first["route_reason"] = route_reason
        first["route_fallback_used"] = False
        if bool(first["strict_pass"]):
            return first

        fallback_used = False
        if self.route_fallback and self.default_backend != backend and self._backend_exists(self.default_backend):
            fallback = self._verify_once(
                backend=self.default_backend,
                sample_id=sample_id,
                candidate_id=candidate_id,
                lean_header=lean_header,
                theorem_decl=decl,
                proof_body=proof_body,
                run_dir=run_dir,
            )
            fallback_used = True
            if bool(fallback["strict_pass"]):
                fallback["route_reason"] = f"{route_reason}_fallback_{self.default_backend}"
                fallback["route_fallback_used"] = True
                return fallback
            first["stderr_digest"] = (
                f"{first.get('stderr_digest', '')}\n[FALLBACK {self.default_backend}] "
                f"{fallback.get('stderr_digest', '')}"
            ).strip()

        first["route_fallback_used"] = fallback_used
        if first.get("sub_error_type") in {"empty_stderr_timeout", "timeout_after_warning", "timeout_or_tooling_block"}:
            failure_details = dict(first.get("failure_details") or {})
            failure_details["route_fallback_used"] = fallback_used
            first["failure_details"] = failure_details
        return first
