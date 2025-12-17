import os

HOME_PATH = "/tmp/agent_home"


def resolve_env_vars(config):
    """
    Recursively resolves environment variables in a configuration dictionary.

    Any string value in the form "${VAR_NAME}" will be replaced by the value of
    the corresponding environment variable. Nested dictionaries and lists are supported.

    Args:
        config (dict): Configuration dictionary.

    Returns:
        dict: New dictionary with environment variables resolved.
    """

    def resolve_value(value):
        # Handle nested structures
        if isinstance(value, dict):
            return {k: resolve_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve_value(v) for v in value]
        if isinstance(value, str):
            # Detect ${VAR_NAME} syntax
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                return os.environ.get(
                    env_var, value
                )  # fallback to the original if missing
            return value
        return value

    return resolve_value(config)
