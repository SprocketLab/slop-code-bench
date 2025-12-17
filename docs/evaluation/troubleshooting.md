---
version: 1.3
last_updated: 2025-12-10
---

# Troubleshooting Guide

This guide covers common issues, error messages, debugging techniques, and performance optimization for the evaluation system.

## Quick Diagnostics Checklist

When something goes wrong, check:

1. **Configuration**: Are all required fields present and valid?
2. **File paths**: Do all referenced files exist?
3. **Timeouts**: Is execution timing out?
4. **Logs**: What do the logs say?
5. **Permissions**: Can the system access necessary files/ports?

## Common Issues

### Configuration Problems

#### Error: "Field 'name' is required in ProblemConfig"

**Cause**: Missing required field in configuration YAML

**Solution**: Add the required field
```yaml
# config.yaml
name: my_problem  # ← Add this
version: "1.0"
description: Problem description
```

**Prevention**: Use schema validation
```python
from slop_code.evaluation.config import ProblemConfig

# Validates on load
config = ProblemConfig.from_yaml("config.yaml")
```

#### Error: "Unknown environment type 'kubernetes'"

**Cause**: Invalid environment type

**Solution**: Use supported types
```yaml
environment:
  type: docker  # or "local"
```

#### Error: "Invalid timeout value"

**Cause**: Timeout is not a number or is negative

**Solution**: Use positive integer
```yaml
timeout: 60  # Not "60" or -1
```

### Case Loading Issues

#### Error: "No cases found for group 'my_group'"

**Cause**: Case files don't match pattern or directory doesn't exist

**Solution 1**: Check pattern matches your files
```yaml
groups:
  - name: my_group
    pattern: "*.yaml"  # Make sure files end with .yaml not .yml
```

**Solution 2**: Verify directory exists
```bash
ls checkpoint_1/my_group/  # Should show case files
```

**Solution 3**: Check file exclusions
```yaml
groups:
  - name: my_group
    exclude:  # Remove if accidentally excluding
      - "*.yaml"  # ← This would exclude everything!
```

#### Error: "Loader script not found: custom_loader.py"

**Cause**: Loader script doesn't exist in expected location

**Solution**: Ensure loader is in checkpoint directory
```bash
# Should exist
checkpoint_1/custom_loader.py
```

#### Error: "Loader function 'load_cases' not found"

**Cause**: Loader script missing required function

**Solution**: Implement the function
```python
# custom_loader.py
def load_cases(group_name, checkpoint_config):
    """Required function."""
    return [...]  # Return list of cases
```

### Execution Problems

#### Error: "Execution timed out"

**Cause**: Submission took longer than allowed timeout

**Solution 1**: Increase timeout
```yaml
# In checkpoint config
timeout: 120  # Increase from 60 to 120
```

**Solution 2**: Optimize submission code

**Solution 3**: Check for infinite loops in submission

**Debug**: Enable timeout logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### Error: "Submission failed to start"

**Cause**: Entry point command is invalid or submission has errors

**Solution 1**: Test entry point manually
```bash
# Try running the command
python main.py --test
```

**Solution 2**: Check logs
```python
# In verifier or custom code
print(f"Error: {case_result.error}")
```

**Solution 3**: Verify environment
```yaml
environment:
  type: docker
  image: python:3.11-slim  # Ensure Python version matches submission
```

#### Error: "Port already in use" (API Adapter)

**Cause**: Another process is using the port

**Solution 1**: Kill existing process
```bash
# Find process using port 8000
lsof -i :8000
kill <PID>
```

**Solution 2**: Use different port
```yaml
adapter:
  type: api
  port: 8001  # Use different port
```

### Verification Issues

#### Error: "Verifier module not found"

**Cause**: `verifier.py` not in problem directory

**Solution**: Create verifier in correct location
```bash
# Should be at:
my_problem/verifier.py
```

#### Error: "Verifier class not found"

**Cause**: Verifier doesn't implement expected interface

**Solution**: Implement required class
```python
# verifier.py
class Verifier:
    def __init__(self, checkpoint_config):
        self.config = checkpoint_config

    def __call__(self, group_name, case_name, actual, expected):
        # Return VerifierReport
        ...
```

#### All Cases Fail Verification

**Cause**: Verifier logic is incorrect

**Solution**: Debug verifier
```python
def __call__(self, group_name, case_name, actual, expected):
    # Add debug output
    print(f"Actual: {actual}")
    print(f"Expected: {expected}")

    # ... rest of verification
```

**Common mistakes:**
- Comparing strings with extra whitespace
- Wrong expected value format
- Case-sensitive comparisons when should be insensitive

### Adapter-Specific Issues

#### CLI Adapter: "Command not found"

**Cause**: Entry point command doesn't exist in environment

**Solution**: Check environment has required tools
```yaml
environment:
  type: docker
  image: python:3.11-slim  # Ensure image has Python
```

**Debug**: Test in container
```bash
docker run -it python:3.11-slim bash
python main.py  # Test if command works
```

#### API Adapter: "Health check failed"

**Cause**: Server didn't start or health endpoint doesn't exist

**Solution 1**: Increase startup timeout
```yaml
adapter:
  type: api
  startup_timeout: 60  # Give more time to start
```

**Solution 2**: Fix health check path
```yaml
adapter:
  type: api
  health_check:
    path: /health  # Ensure this endpoint exists
```

**Solution 3**: Remove health check if not needed
```yaml
adapter:
  type: api
  # Don't include health_check
```

#### Playwright Adapter: "Element not found"

**Cause**: Selector is wrong or element hasn't loaded

**Solution 1**: Increase wait timeout
```yaml
- type: wait
  selector: '.slow-element'
  timeout: 10000  # 10 seconds
```

**Solution 2**: Fix selector
```python
# Debug: check what's on page
- type: evaluate
  script: console.log(document.body.innerHTML)
```

**Solution 3**: Wait for different condition
```yaml
- type: wait
  url: /expected-page  # Wait for URL instead
```

## Exception Reference

### EvaluationException

Base exception for all evaluation errors.

**Common subclasses:**
- `ConfigurationError`: Invalid configuration
- `LoaderError`: Case loading failed
- `AdapterError`: Adapter execution failed
- `VerificationError`: Verification failed
- `TimeoutError`: Execution timeout

### Handling Exceptions

```python
from slop_code.evaluation import run_checkpoint
from slop_code.evaluation.exceptions import (
    ConfigurationError,
    TimeoutError,
    AdapterError
)

try:
    report = run_checkpoint(...)
except ConfigurationError as e:
    print(f"Configuration error: {e}")
    # Fix configuration and retry
except TimeoutError as e:
    print(f"Timeout: {e}")
    # Increase timeout or optimize code
except AdapterError as e:
    print(f"Adapter error: {e}")
    # Check adapter configuration
except Exception as e:
    print(f"Unexpected error: {e}")
    raise
```

## Debugging Techniques

### Enable Debug Logging

```python
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Run evaluation
report = run_checkpoint(...)
```

### Inspect Intermediate Results

```python
# In verifier
def __call__(self, group_name, case_name, actual, expected):
    # Log everything
    print(f"\n{'='*60}")
    print(f"Group: {group_name}, Case: {case_name}")
    print(f"Actual output: {actual.output!r}")
    print(f"Expected output: {expected.get('output')!r}")
    print(f"Status code: {actual.status_code}")
    print(f"{'='*60}\n")

    # ... rest of verification
```

### Run Single Case

Test a single case in isolation:

```python
from slop_code.evaluation import run_checkpoint

# Run only specific group
report = run_checkpoint(
    groups_filter=["specific_group"],  # If supported
    ...
)
```

**Or modify config temporarily:**
```yaml
# checkpoint/config.yaml
groups:
  - name: test_group
    pattern: "debug_case.yaml"  # Only one case
```

### Test Verifier Separately

```python
# test_verifier.py
from verifier import Verifier
from slop_code.evaluation.adapters import CaseResult
from slop_code.evaluation.config import GroupType

config = {...}  # CheckpointConfig
verifier = Verifier(config)

# Mock data
actual = CaseResult(
    id="test_case",
    group="test_group",
    group_type=GroupType.CORE,
    output="test output",
    status_code=0,
    elapsed=0.1,
)

expected = CaseResult(
    id="test_case",
    group="test_group",
    group_type=GroupType.CORE,
    output="test output",
    status_code=0,
)

# Test
results = verifier("test_group", "test_case", actual, expected)
# Returns dict[str, VerificationResult]
for attr, result in results.items():
    print(f"{attr}: {'PASS' if result.is_correct else 'FAIL'}")
```

### Check Adapter Output

```python
# Manually run adapter
from slop_code.evaluation.adapters import CLIAdapter

adapter_config = {...}
with CLIAdapter(adapter_config) as adapter:
    result = adapter.run_case(case_data)
    print(f"Output: {result.output}")
    print(f"Status: {result.status_code}")
    print(f"Elapsed: {result.elapsed}s")
    if result.adapter_error:
        print(f"Error: {result.stderr}")
    if result.timed_out:
        print("Timed out!")
```

## Performance Issues

### Slow Execution

**Symptom**: Evaluation takes too long

**Solutions:**

1. **Reduce case count**
```python
# In loader
def load_cases(group_name, checkpoint_config):
    all_cases = generate_all_cases()
    # Sample subset
    return random.sample(all_cases, 100)
```

2. **Parallelize execution** (if supported)
```yaml
# Future feature
execution:
  parallel: true
  max_workers: 4
```

3. **Optimize submission**
- Profile submission code
- Remove unnecessary computations
- Use caching

4. **Increase timeout to prevent premature kills**
```yaml
timeout: 300  # Give more time
```

### High Memory Usage

**Symptom**: System runs out of memory

**Solutions:**

1. **Limit case size**
```python
# Avoid loading huge files in cases
# Use references instead of inline data
```

2. **Process in batches**
```python
# In loader
def load_cases(group_name, checkpoint_config):
    # Return iterator instead of list
    for case in case_generator():
        yield case
```

3. **Clean up resources**
```python
# In custom code
import gc

def __call__(self, group_name, case_name, actual, expected):
    result = verify(actual, expected)
    gc.collect()  # Force garbage collection
    return result
```

### Slow Startup (API/Playwright)

**Symptom**: Server/browser takes long to start

**Solutions:**

1. **Increase startup timeout**
```yaml
adapter:
  type: api
  startup_timeout: 60
```

2. **Optimize submission startup**
- Reduce imports
- Lazy load modules
- Minimize initialization

3. **Use faster base image**
```yaml
environment:
  image: python:3.11-slim  # Smaller/faster than full image
```

## Log Locations

### System Logs

```bash
# Evaluation system logs
~/.slop_code/logs/evaluation.log

# Adapter-specific logs
~/.slop_code/logs/cli_adapter.log
~/.slop_code/logs/api_adapter.log
~/.slop_code/logs/playwright_adapter.log
```

### Submission Logs

```bash
# Stdout/stderr from submission (if captured)
/tmp/slop_code/runs/<run_id>/output.log
/tmp/slop_code/runs/<run_id>/error.log
```

### Docker Logs (if using Docker environment)

```bash
# Find container
docker ps -a | grep slop_code

# View logs
docker logs <container_id>
```

## Debugging Flags

### Environment Variables

```bash
# Enable debug mode
export SLOP_CODE_DEBUG=1

# Verbose logging
export SLOP_CODE_LOG_LEVEL=DEBUG

# Keep temporary files
export SLOP_CODE_KEEP_TEMP=1

# Disable timeout (for debugging)
export SLOP_CODE_NO_TIMEOUT=1

# Run evaluation
python run_evaluation.py
```

### Configuration Options

```yaml
# checkpoint/config.yaml
debug:
  enabled: true
  verbose: true
  keep_temp_files: true
  log_level: DEBUG
```

## Common Error Messages

### "Unable to load configuration"

**Full error**: `Unable to load configuration from <path>: [Errno 2] No such file or directory`

**Fix**: Check file path is correct
```python
# Use absolute path
config = ProblemConfig.from_yaml("/full/path/to/config.yaml")
```

### "Invalid YAML syntax"

**Full error**: `yaml.scanner.ScannerError: while scanning...`

**Fix**: Check YAML formatting
```yaml
# Bad (mixing tabs and spaces)
groups:
	- name: test

# Good (consistent indentation)
groups:
  - name: test
```

### "Adapter timeout exceeded"

**Full error**: `AdapterError: Execution timeout after 60 seconds`

**Fix**: Increase timeout or optimize code
```yaml
timeout: 120  # Double the timeout
```

### "Verification failed with exception"

**Full error**: `VerificationError: Exception in verifier: <details>`

**Fix**: Debug verifier
```python
# Add try-except in verifier
def __call__(self, group_name, case_name, actual, expected):
    try:
        # Verification logic
        ...
    except Exception as e:
        print(f"Error in verification: {e}")
        import traceback
        traceback.print_exc()
        raise
```

## Best Practices for Avoiding Issues

### 1. Validate Early

```python
# Validate config before running
from slop_code.evaluation.config import ProblemConfig

try:
    config = ProblemConfig.from_yaml("config.yaml")
    print("✓ Configuration valid")
except Exception as e:
    print(f"✗ Configuration invalid: {e}")
    exit(1)
```

### 2. Test Incrementally

1. Start with one simple case
2. Verify it works
3. Add more cases gradually
4. Test each addition

### 3. Use Version Control

```bash
git init
git add config.yaml checkpoint_1/ verifier.py
git commit -m "Initial evaluation setup"

# Before making changes
git checkout -b experiment
# Make changes, test
# If it works: merge
# If it breaks: git checkout main
```

### 4. Document Configuration

```yaml
# config.yaml
name: my_problem
# Why: This is the unique identifier used in reports

version: "1.0"
# Note: Update when making breaking changes

timeout: 120
# Reasoning: Most cases complete in <60s, but some take up to 100s
# Added 20s buffer for safety
```

### 5. Monitor Resource Usage

```python
import psutil
import time

start_time = time.time()
start_mem = psutil.Process().memory_info().rss / 1024 / 1024  # MB

report = run_checkpoint(...)

end_time = time.time()
end_mem = psutil.Process().memory_info().rss / 1024 / 1024

print(f"Time: {end_time - start_time:.2f}s")
print(f"Memory: {end_mem - start_mem:.2f}MB")
```

## Getting Help

### Information to Include

When asking for help, include:

1. **Configuration files**: Problem and checkpoint configs
2. **Error message**: Full traceback
3. **Logs**: Relevant log excerpts
4. **Environment**: Python version, OS, Docker version
5. **Reproduction steps**: How to reproduce the issue
6. **Expected vs actual**: What you expected vs what happened

### Example Help Request

```
Issue: Verification failing for all cases

Environment:
- Python 3.11
- macOS 14.0
- Docker 24.0.6

Configuration:
<paste config.yaml>

Error:
<paste full traceback>

Expected: Cases should pass with correct output
Actual: All cases failing with diff errors

Reproduction:
1. Run: python run_evaluation.py
2. See all cases fail

Additional context:
- Works fine when running submission manually
- Only fails in evaluation framework
```

## Next Steps

- **Review architecture**: [Architecture Guide](architecture.md)
- **Check configuration**: [Configuration Guide](configuration.md)
- **Debug verification**: [Verification Guide](verification.md)
- **Examine adapters**: [Adapters Guide](adapters.md)
