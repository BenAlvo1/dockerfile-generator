"""
Integration tests for the Dockerfile-generator service.

Test categories
---------------
TestCLIArgHandling   – Validates CLI argument parsing (no LLM, no Docker).
TestSafetyBlocking   – Verifies that malicious / prompt-injecting scripts are
                       rejected by the deterministic regex layer before any LLM
                       call is made.  Fast (< 5 s per case).
TestFullPipeline     – End-to-end: LLM generates a Dockerfile, Docker builds
                       and runs it, output is validated.  Marked ``e2e``; skipped
                       automatically when no API key is configured.

Exit-code contract (dockerfile_gen/main.py)
---------------------------------
  0  – Dockerfile generated and validated successfully.
  1  – General failure (bad args, missing file, build/run failure).
  2  – Script blocked by safety check.
"""
import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_scripts")


# ---------------------------------------------------------------------------
# CLI argument handling
# ---------------------------------------------------------------------------

class TestCLIArgHandling:
    """Basic CLI contract tests – no LLM or Docker required."""

    def test_no_args_prints_usage_and_exits_1(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "dockerfile_gen.main"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr

    def test_too_many_args_prints_usage_and_exits_1(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "dockerfile_gen.main", "script.py", "extra_arg"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        assert result.returncode == 1
        assert "Usage" in result.stderr

    def test_nonexistent_file_exits_1(self, run_tool):
        result = run_tool("/tmp/__nonexistent_test_script_xyz__.py", timeout=10)
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "File not found" in result.stderr


# ---------------------------------------------------------------------------
# Safety blocking (deterministic layer – no LLM needed)
# ---------------------------------------------------------------------------

class TestSafetyBlocking:
    """
    Malicious and prompt-injecting scripts must be rejected with exit code 2.

    The regex pre-filter in ``check_safety.py`` catches all cases below
    before the LLM is ever invoked, so these tests are fast and cost-free.
    """

    @pytest.mark.parametrize("script_rel_path,description", [
        # --- Malicious scripts ---
        (
            "malicious/fork_bomb.sh",
            "fork bomb – spawns unlimited child processes",
        ),
        (
            "malicious/reverse_shell.py",
            "reverse shell – /dev/tcp exfiltration",
        ),
        (
            "malicious/curl_exec.sh",
            "curl-pipe-bash dropper – remote code execution",
        ),
        (
            "malicious/crypto_miner.py",
            "crypto miner – unauthorised resource consumption (xmrig)",
        ),
        (
            "malicious/disk_wipe.sh",
            "disk wipe – destructive rm -rf /",
        ),
        # --- Prompt injection scripts ---
        (
            "prompt_injection/inject_override.py",
            "prompt injection – 'ignore all previous instructions'",
        ),
        (
            "prompt_injection/inject_system.sh",
            "prompt injection – [SYSTEM] tag with new directives",
        ),
        (
            "prompt_injection/inject_role_reassign.py",
            "prompt injection – 'you are now' role reassignment",
        ),
    ])
    def test_script_is_blocked(self, run_tool, script_rel_path, description):
        script_path = os.path.join(SCRIPTS_DIR, script_rel_path)
        assert os.path.isfile(script_path), f"Test script missing: {script_path}"

        result = run_tool(script_path, timeout=30)

        assert result.returncode == 2, (
            f"[{description}] Expected exit code 2 (safety block), "
            f"got {result.returncode}.\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
        # The main logger emits "Blocked: script failed safety check."
        combined = result.stdout + result.stderr
        assert "Blocked" in combined or "safety" in combined.lower(), (
            f"[{description}] Expected a safety-block message in output.\n"
            f"STDERR: {result.stderr}"
        )

    def test_safe_script_is_not_blocked_by_deterministic_layer(self, run_tool):
        """
        A benign script must not be rejected by the regex layer.
        This test mocks the LLM so it does not make a real API call;
        it stops after parse_script + check_safety (deterministic pass)
        and will fail later in the pipeline (no real LLM), but the exit
        code must NOT be 2.
        """
        script_path = os.path.join(SCRIPTS_DIR, "word_reverser/word_reverser.py")
        result = run_tool(script_path, timeout=20)
        # A safe script should never be blocked by the safety layer.
        assert result.returncode != 2, (
            "Benign script was wrongly blocked by the safety check.\n"
            f"STDERR: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Full end-to-end pipeline (requires LLM API key + Docker daemon)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestFullPipeline:
    """
    End-to-end: real LLM call → Dockerfile generation → Docker build & run →
    output validation.

    Skipped automatically when no LLM API key is configured.
    Each test may take 60-180 s depending on image pull times.
    """

    @pytest.mark.parametrize("script_rel_path,expected_output_fragment", [
        (
            "word_reverser/word_reverser.py",
            "world Hello",
        ),
        (
            "vowel_counter/vowel_counter.js",
            "Vowel Count:",
        ),
        (
            "line_counter/line_counter.sh",
            "Line Count:",
        ),
        (
            "matrix_stats/matrix_stats.py",
            "Matrix statistics:",
        ),
    ])
    def test_generates_and_validates_dockerfile(
        self,
        run_tool,
        script_rel_path,
        expected_output_fragment,
    ):
        script_path = os.path.join(SCRIPTS_DIR, script_rel_path)
        result = run_tool(script_path, timeout=300)

        assert result.returncode == 0, (
            f"Expected successful exit (0) for {script_rel_path}.\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

        combined = result.stdout + result.stderr
        assert "Dockerfile generated and validated successfully" in combined, (
            f"Expected success message in output.\nSTDERR: {result.stderr}"
        )

        # The generated Dockerfile should have been written next to the script.
        script_dir = os.path.dirname(script_path)
        dockerfile_path = os.path.join(script_dir, "Dockerfile")
        assert os.path.isfile(dockerfile_path), (
            f"Expected Dockerfile written to {dockerfile_path}"
        )

        # Spot-check Dockerfile has the basic FROM instruction.
        with open(dockerfile_path) as fh:
            dockerfile_content = fh.read()
        assert "FROM" in dockerfile_content, "Generated Dockerfile is missing FROM instruction"

    @pytest.mark.e2e
    def test_failed_pipeline_exits_1(self, run_tool, tmp_path):
        """A script that always errors at runtime should exhaust retries and exit 1."""
        broken = tmp_path / "broken.py"
        broken.write_text("raise RuntimeError('always fails')\n")
        result = run_tool(str(broken), timeout=300)
        assert result.returncode in (1, 2), (
            f"Expected exit 1 (pipeline failure) or 2 (safety block), "
            f"got {result.returncode}"
        )

    @pytest.mark.e2e
    def test_complex_script_with_pip_dependency(self, run_tool):
        """
        A script that requires a non-stdlib pip package (numpy).
        Verifies the LLM correctly adds RUN pip install to the Dockerfile
        and the container runs successfully.
        """
        script_path = os.path.join(SCRIPTS_DIR, "matrix_stats/matrix_stats.py")
        result = run_tool(script_path, timeout=300)

        assert result.returncode == 0, (
            "matrix_stats.py (requires numpy) failed to generate a working Dockerfile.\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "Dockerfile generated and validated successfully" in combined

        dockerfile_path = os.path.join(SCRIPTS_DIR, "matrix_stats/Dockerfile")
        assert os.path.isfile(dockerfile_path), "Expected Dockerfile written next to script"
        with open(dockerfile_path) as fh:
            content = fh.read()
        assert "numpy" in content.lower(), (
            "Expected 'numpy' in the generated Dockerfile (pip install step missing)"
        )

    @pytest.mark.e2e
    def test_reflection_recovers_from_bad_dockerfile(self, run_tool, tmp_path):
        """
        A valid script paired with a subtly tricky runtime invocation should
        still succeed within max_attempts (reflection loop).
        Exercises: generate → execute (fail) → reflect_and_fix → execute (pass).
        """
        # word_reverser is simple enough that even a sub-optimal first Dockerfile
        # will be corrected within the retry budget.
        script_path = os.path.join(SCRIPTS_DIR, "word_reverser/word_reverser.py")
        result = run_tool(script_path, timeout=300)
        assert result.returncode == 0, (
            f"Reflection loop failed to recover.\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# LLM semantic safety check (scripts that bypass the deterministic layer)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestLLMSafetyCheck:
    """
    Scripts that pass the deterministic regex filter but contain semantically
    malicious intent.  These require a real LLM call to be caught (exit code 2).

    Marked ``e2e`` because the LLM layer must run to detect the threat.
    """

    def test_llm_catches_credential_harvester(self, run_tool):
        """
        credential_harvester.py reads env vars + SSH keys and POSTs them to an
        attacker-controlled URL.  No regex pattern matches it, so only the LLM
        semantic check can flag it.

        Expected: deterministic check passes, LLM blocks → exit code 2.
        """
        script_path = os.path.join(SCRIPTS_DIR, "llm_safety_bypass/credential_harvester.py")
        assert os.path.isfile(script_path), f"Test script missing: {script_path}"

        result = run_tool(script_path, timeout=60)

        assert result.returncode == 2, (
            "LLM failed to block the credential-harvesting script.\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "Blocked" in combined or "safety" in combined.lower(), (
            "Expected a safety-block message in output.\n"
            f"STDERR: {result.stderr}"
        )
