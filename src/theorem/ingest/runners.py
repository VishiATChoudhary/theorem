import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class RunnerError(Exception):
    """Exception raised when a runner fails."""

    pass


class Runner(Protocol):
    """Protocol for agent runners."""

    def run(self, prompt: str) -> str:
        """Run with the given prompt and return the result."""
        ...


@dataclass
class CLIRunner:
    """Runner that executes a CLI command with the prompt as the final argument."""

    argv: list[str]
    timeout: int = 300

    def run(self, prompt: str) -> str:
        """Execute the CLI command with the prompt appended as final arg."""
        cmd = [*self.argv, prompt]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RunnerError(
                f"Command failed with return code {e.returncode}: {' '.join(cmd)}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RunnerError(
                f"Command timed out after {self.timeout}s: {' '.join(cmd)}"
            ) from e


@dataclass
class APIRunner:
    """Runner that calls the Anthropic Messages API."""

    model: str = "claude-haiku-4-5-20251001"

    def run(self, prompt: str) -> str:
        """Call the Anthropic Messages API and return the first text block."""
        api_key = os.environ.get("THEOREM_API_KEY")
        if not api_key:
            raise RunnerError("THEOREM_API_KEY environment variable not set")

        request_body = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                response_data = json.loads(response.read().decode("utf-8"))

            if "content" not in response_data or not response_data["content"]:
                raise RunnerError("No content in API response")

            first_block = response_data["content"][0]
            if first_block.get("type") != "text":
                raise RunnerError(f"Expected text block, got {first_block.get('type')}")

            return first_block.get("text", "")

        except urllib.error.URLError as e:
            raise RunnerError(f"API request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise RunnerError(f"Failed to decode API response: {e}") from e


def get_runner(name: str) -> Runner:
    """Get a runner instance by name.

    Args:
        name: Runner name. One of: "claude", "codex", "copilot", "cursor", "api".

    Returns:
        A Runner instance.

    Raises:
        RunnerError: If the runner name is unknown.
    """
    runners = {
        "claude": lambda: CLIRunner(argv=["claude", "-p"]),
        "codex": lambda: CLIRunner(argv=["codex", "exec"]),
        "copilot": lambda: CLIRunner(argv=["copilot", "-p"]),
        "cursor": lambda: CLIRunner(argv=["cursor-agent", "-p"]),
        "api": lambda: APIRunner(),
    }

    if name not in runners:
        available = ", ".join(sorted(runners.keys()))
        raise RunnerError(
            f"Unknown runner '{name}'. Available: {available}. "
            f"See 'claude' and other options."
        )

    return runners[name]()
