import math
import re

# Global state
variables = {}
functions = {}
history = []


def is_valid_var_name(name):
    """Check if a variable name is valid (starts with letter, contains only letters/numbers/underscore)"""
    return re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name) is not None


def is_valid_func_name(name):
    """Check if a function name is valid"""
    return re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name) is not None


def handle_assignment(line):
    """Handle variable assignment: x = 5"""
    if "=" not in line:
        return False

    parts = line.split("=", 1)
    if len(parts) != 2:
        return False

    var_name = parts[0].strip()
    expression = parts[1].strip()

    if not is_valid_var_name(var_name):
        print("Invalid variable name")
        exit(1)

    try:
        # Evaluate the expression with current variables
        value = evaluate_expression(expression)
        variables[var_name] = value
        return True
    except Exception as e:
        print(f"Error in assignment: {e}")
        exit(3)


def handle_function_definition(line):
    """Handle function definition: def square(x): return x * x"""
    if not line.startswith("def "):
        return False

    # Parse function definition
    match = re.match(
        r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\):\s*return\s+(.+)", line
    )
    if not match:
        print("Invalid function definition")
        exit(1)

    func_name = match.group(1)
    params = [p.strip() for p in match.group(2).split(",") if p.strip()]
    body = match.group(3).strip()

    # Validate parameter names
    for param in params:
        if not is_valid_var_name(param):
            print("Invalid parameter name")
            exit(1)

    functions[func_name] = {"params": params, "body": body}
    return True


def handle_function_call(line):
    """Handle function call: square(5)"""
    # Check if this looks like a function call
    match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)$", line.strip())
    if not match:
        return None  # Not a function call format

    func_name = match.group(1)
    if func_name not in functions:
        return None  # Not a defined function, might be a built-in

    args_str = match.group(2).strip()
    args = []

    if args_str:
        # Parse arguments
        for arg in args_str.split(","):
            arg = arg.strip()
            try:
                args.append(evaluate_expression(arg))
            except Exception as e:
                print(f"Error in function argument: {e}")
                exit(2)

    # Execute function
    func = functions[func_name]
    if len(args) != len(func["params"]):
        print(
            f"Function {func_name} expects {len(func['params'])} arguments, got {len(args)}"
        )
        exit(2)

    # Create local variable context
    old_vars = variables.copy()
    for param, arg in zip(func["params"], args):
        variables[param] = arg

    try:
        result = evaluate_expression(func["body"])
        variables.clear()
        variables.update(old_vars)  # Restore global variables
        return result
    except Exception as e:
        variables.clear()
        variables.update(old_vars)  # Restore global variables
        print(f"Error in function execution: {e}")
        exit(2)


def evaluate_expression(expr):
    """Evaluate an expression with variables and functions"""
    # Replace variables with their values
    for var_name, var_value in variables.items():
        expr = re.sub(r"\b" + re.escape(var_name) + r"\b", str(var_value), expr)

    # Add math functions to the evaluation context
    safe_dict = {
        "__builtins__": {},
        "sqrt": math.sqrt,
        "pow": math.pow,
        "abs": abs,
        "max": max,
        "min": min,
        "round": round,
        "len": len,
    }

    # Add current variables to safe dict
    safe_dict.update(variables)

    try:
        return eval(expr, safe_dict)
    except NameError as e:
        if "undefined variable" in str(e).lower():
            print("Undefined variable")
            exit(2)
        raise
    except Exception:
        raise


def handle_history():
    """Show calculation history"""
    for i, entry in enumerate(history, 1):
        print(f"{i}. {entry}")
    return len(history)  # Return number of entries


def handle_clear():
    """Clear history"""
    global history
    history.clear()
    return 0  # Return success


def main():
    import sys

    # Check if running in evaluation mode
    eval_mode = "--eval" in sys.argv
    prompt = "" if eval_mode else "Enter an equation: "

    while True:
        try:
            line = input(prompt).strip()

            if line == "exit":
                break
            if line == "history":
                result = handle_history()
                if result > 0:  # Only add to history if there were entries
                    history.append(f"history -> {result} entries")
            elif line == "clear":
                result = handle_clear()
                history.append("clear -> history cleared")
            elif handle_assignment(line):
                # Variable assignment handled
                continue
            elif handle_function_definition(line):
                # Function definition handled
                continue
            else:
                # Try to evaluate as expression or function call
                try:
                    # First try function call
                    result = handle_function_call(line)
                    if result is None:
                        # Not a function call, try regular expression
                        result = evaluate_expression(line)

                    print(result)
                    history.append(f"{line} = {result}")
                except SystemExit:
                    raise  # Re-raise exit calls
                except Exception as e:
                    print(f"Error: {e}")
                    exit(3)

        except EOFError:
            break
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
