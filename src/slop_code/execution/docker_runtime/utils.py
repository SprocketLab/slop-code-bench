def network_mode_for_address(address: str) -> str:
    """Determine the appropriate Docker network mode for a given bind address.

    Args:
        address: The address the server will bind to (e.g., "127.0.0.1", "0.0.0.0")

    Returns:
        The appropriate Docker network mode ("host" or "bridge")

    Note:
        - "127.0.0.1" and "localhost" require "host" mode to be accessible from the host
        - "0.0.0.0" can use "bridge" mode with port mapping
        - Other addresses default to "host" mode for simplicity
    """
    if address in ("127.0.0.1", "localhost"):
        return "host"
    return "bridge"
