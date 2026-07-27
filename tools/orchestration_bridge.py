"""Bridge: expose orchestration tools (defined in orchestration/collaboration.py) to the tool registry scanner."""


def register(registry):
    from orchestration.collaboration import register as _collab_register
    _collab_register(registry)


# AST scanner detection: the scanner looks for register() calls
if False:
    register(None)
