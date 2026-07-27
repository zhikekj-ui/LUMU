"""Bridge: expose learning tools (defined in agent/learner.py) to the tool registry scanner."""


def register(registry):
    from agent.learner import register as _learner_register
    _learner_register(registry)


# AST scanner detection: the scanner looks for register() calls
if False:
    register(None)
