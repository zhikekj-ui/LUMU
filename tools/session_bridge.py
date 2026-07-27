"""Bridge: expose session tools (defined in agent/session_manager.py) to the tool registry scanner."""


def register(registry):
    from agent.session_manager import register as _session_register
    _session_register(registry)


# AST scanner detection: the scanner looks for register() calls
if False:
    register(None)
