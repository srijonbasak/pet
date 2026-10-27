def _field(value, max_length):
    """Return a display-safe ASCII field without protocol separators."""
    if value is None:
        return "--"
    value = str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")
    return value.encode("ascii", "replace").decode("ascii")[:max_length]


def state_to_payload(state):
    """Encode display data as one compact newline-terminated record."""
    fields = (
        "CD2",
        _field(state.project, 40),
        _field(state.chat, 40),
        _field(state.context_left, 3),
        _field(state.context_used, 10),
        _field(state.context_max, 10),
        _field(state.limit_5h_left, 3),
        _field(state.limit_5h_reset, 24),
        _field(state.limit_7d_left, 3),
        _field(state.limit_7d_reset, 24),
    )
    return ("|".join(fields) + "\n").encode("ascii")
