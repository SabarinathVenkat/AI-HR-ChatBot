"""Resource Management (RMG): a second assistant in the same application.

Everything specific to resource management lives in this folder. It reuses the shared parts of the app
(guardrail, verifier, fallback, the tool registry, the audit log, the model factory) and adds only its own
prompt, its tool allowlist and its own small graph. The HR agent does not import anything from here.
"""
