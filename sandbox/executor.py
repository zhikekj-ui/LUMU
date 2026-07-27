"""Code execution sandbox — Docker-isolated code execution for Python and JavaScript."""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional


class CodeSandbox:
    """Docker-isolated code execution environment.
    
    Executes user-submitted code in a container with:
    - Resource limits (CPU, memory, time)
    - Network isolation (optional)
    - File system isolation
    - Output capture (stdout, stderr, return value)
    """

    DEFAULT_IMAGE = "python:3.11-slim"
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_MEMORY_LIMIT = "256m"
    DEFAULT_CPU_LIMIT = "1.0"

    def __init__(self, docker_socket: str = "/var/run/docker.sock",
                 default_image: str = None, default_timeout: int = 30,
                 allow_network: bool = False):
        self.docker_socket = docker_socket
        self.default_image = default_image or self.DEFAULT_IMAGE
        self.default_timeout = default_timeout
        self.allow_network = allow_network
        self._check_docker()

    def _check_docker(self):
        """Verify Docker is available."""
        try:
            import docker
            self.client = docker.from_env()
            self.client.ping()
            self.docker_available = True
        except Exception as e:
            self.docker_available = False
            self.docker_error = str(e)

    def execute_python(self, code: str, timeout: int = None, 
                       image: str = None, packages: list[str] = None) -> dict:
        """Execute Python code in a Docker container."""
        if not self.docker_available:
            return self._execute_local_python(code, timeout)
        
        timeout = timeout or self.default_timeout
        image = image or self.default_image

        # Build pip install command if packages specified
        setup_cmd = ""
        if packages:
            pkg_list = " ".join(packages)
            setup_cmd = f"pip install --quiet {pkg_list} && "

        # Create temporary directory for file I/O
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write code to file
            code_file = Path(tmpdir) / "script.py"
            code_file.write_text(code, encoding="utf-8")

            # Output file for capturing results
            output_file = Path(tmpdir) / "output.json"
            output_file.write_text("{}", encoding="utf-8")

            # Build container command
            container_cmd = f"""
import sys, json, traceback, io

_stdout_capture = io.StringIO()
_stderr_capture = io.StringIO()
_result = None
_error = None

try:
    sys.stdout = _stdout_capture
    sys.stderr = _stderr_capture
    
    # Execute user code
    exec(open('/workspace/script.py').read())
    
    # Try to capture 'result' variable if defined
    if 'result' in dir():
        _result = result
    
except Exception as e:
    _error = traceback.format_exc()
finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

# Write output
output = {{
    'stdout': _stdout_capture.getvalue(),
    'stderr': _stderr_capture.getvalue(),
    'result': repr(_result) if _result is not None else None,
    'error': _error,
}}
with open('/workspace/output.json', 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
"""
            wrapper_file = Path(tmpdir) / "wrapper.py"
            wrapper_file.write_text(container_cmd, encoding="utf-8")

            try:
                import docker

                # Run container
                container = self.client.containers.run(
                    image,
                    f"python /workspace/wrapper.py",
                    volumes={tmpdir: {"bind": "/workspace", "mode": "rw"}},
                    mem_limit=self.DEFAULT_MEMORY_LIMIT,
                    cpu_period=100000,
                    cpu_quota=int(float(self.DEFAULT_CPU_LIMIT) * 100000),
                    network_disabled=not self.allow_network,
                    detach=True,
                    working_dir="/workspace",
                )

                # Wait for completion with timeout
                result = container.wait(timeout=timeout)
                
                # Read output
                if output_file.exists():
                    output = json.loads(output_file.read_text(encoding="utf-8"))
                else:
                    output = {"stdout": "", "stderr": "", "result": None, "error": None}

                # Get container logs as fallback
                logs = container.logs().decode("utf-8", errors="replace")
                if logs and not output.get("stdout"):
                    output["stdout"] = logs

                # Clean up
                container.remove(force=True)

                exit_code = result.get("StatusCode", -1)
                return {
                    "success": exit_code == 0 and not output.get("error"),
                    "stdout": output.get("stdout", ""),
                    "stderr": output.get("stderr", ""),
                    "result": output.get("result"),
                    "error": output.get("error"),
                    "exit_code": exit_code,
                    "execution_time": 0,
                }

            except Exception as e:
                error_msg = str(e)
                if "timeout" in error_msg.lower() or "read timed out" in error_msg.lower():
                    error_msg = f"Execution timeout ({timeout}s)"
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "result": None,
                    "error": error_msg,
                    "exit_code": -1,
                }

    def _execute_local_python(self, code: str, timeout: int = None) -> dict:
        """Fallback: execute Python locally with resource limits (no Docker)."""
        timeout = timeout or self.default_timeout
        
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "script.py"
            code_file.write_text(code, encoding="utf-8")
            
            start_time = time.time()
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    asyncio.wait_for(
                        self._run_subprocess(
                            ["python3", str(code_file)],
                            cwd=tmpdir,
                            timeout=timeout,
                        ),
                        timeout=timeout + 5,
                    )
                )
                elapsed = time.time() - start_time
                return {
                    "success": result["returncode"] == 0,
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "result": None,
                    "error": None if result["returncode"] == 0 else result["stderr"],
                    "exit_code": result["returncode"],
                    "execution_time": elapsed,
                    "sandbox": "local",
                }
            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "result": None,
                    "error": f"Execution timeout ({timeout}s)",
                    "exit_code": -1,
                    "execution_time": timeout,
                    "sandbox": "local",
                }

    async def _run_subprocess(self, cmd: list, cwd: str, timeout: int) -> dict:
        """Run a subprocess asynchronously with timeout."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            proc.kill()
            raise

    def execute_javascript(self, code: str, timeout: int = None,
                           packages: list[str] = None) -> dict:
        """Execute JavaScript code in a Node.js container."""
        if not self.docker_available:
            return self._execute_local_js(code, timeout)
        
        timeout = timeout or self.default_timeout

        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "script.js"
            output_file = Path(tmpdir) / "output.json"
            output_file.write_text("{}", encoding="utf-8")

            # Setup packages
            setup_cmd = ""
            if packages:
                pkg_list = " ".join(packages)
                setup_cmd = f"npm install --silent {pkg_list} && "

            wrapper_code = f"""
const fs = require('fs');

let stdoutCapture = '';
let stderrCapture = '';
let result = null;
let error = null;

const origLog = console.log;
const origErr = console.error;

console.log = function(...args) {{
    stdoutCapture += args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ') + '\\n';
    origLog.apply(console, arguments);
}};

console.error = function(...args) {{
    stderrCapture += args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ') + '\\n';
    origErr.apply(console, arguments);
}};

try {{
    const code = fs.readFileSync('/workspace/script.js', 'utf-8');
    const fn = new Function(code);
    const r = fn();
    if (r !== undefined) result = String(r);
}} catch (e) {{
    error = e.stack || String(e);
}}

console.log = origLog;
console.error = origErr;

fs.writeFileSync('/workspace/output.json', JSON.stringify({{
    stdout: stdoutCapture,
    stderr: stderrCapture,
    result: result,
    error: error,
}}, null, 2));
"""
            wrapper_file = Path(tmpdir) / "wrapper.js"
            wrapper_file.write_text(wrapper_code, encoding="utf-8")
            code_file.write_text(code, encoding="utf-8")

            try:
                import docker

                container = self.client.containers.run(
                    "node:20-slim",
                    f"node /workspace/wrapper.js",
                    volumes={tmpdir: {"bind": "/workspace", "mode": "rw"}},
                    mem_limit=self.DEFAULT_MEMORY_LIMIT,
                    cpu_period=100000,
                    cpu_quota=int(float(self.DEFAULT_CPU_LIMIT) * 100000),
                    network_disabled=not self.allow_network,
                    detach=True,
                    working_dir="/workspace",
                )

                result = container.wait(timeout=timeout)
                
                if output_file.exists():
                    output = json.loads(output_file.read_text(encoding="utf-8"))
                else:
                    output = {"stdout": "", "stderr": "", "result": None, "error": None}

                container.remove(force=True)

                exit_code = result.get("StatusCode", -1)
                return {
                    "success": exit_code == 0 and not output.get("error"),
                    "stdout": output.get("stdout", ""),
                    "stderr": output.get("stderr", ""),
                    "result": output.get("result"),
                    "error": output.get("error"),
                    "exit_code": exit_code,
                }

            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "result": None,
                    "error": str(e),
                    "exit_code": -1,
                }

    async def _execute_local_js(self, code: str, timeout: int = None) -> dict:
        """Fallback: execute JavaScript locally with Node.js."""
        timeout = timeout or self.default_timeout
        
        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "script.js"
            code_file.write_text(code, encoding="utf-8")
            
            start_time = time.time()
            try:
                result = await asyncio.wait_for(
                    self._run_subprocess(
                        ["node", str(code_file)],
                        cwd=tmpdir,
                        timeout=timeout,
                    ),
                    timeout=timeout + 5,
                )
                elapsed = time.time() - start_time
                return {
                    "success": result["returncode"] == 0,
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "result": None,
                    "error": None if result["returncode"] == 0 else result["stderr"],
                    "exit_code": result["returncode"],
                    "execution_time": elapsed,
                    "sandbox": "local",
                }
            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "result": None,
                    "error": f"Execution timeout ({timeout}s)",
                    "exit_code": -1,
                    "execution_time": timeout,
                    "sandbox": "local",
                }

    def is_available(self) -> bool:
        """Check if Docker sandbox is available."""
        return self.docker_available

    def status(self) -> dict:
        """Get sandbox status."""
        return {
            "docker_available": self.docker_available,
            "default_image": self.default_image,
            "default_timeout": self.default_timeout,
            "allow_network": self.allow_network,
            "error": getattr(self, "docker_error", None),
        }
