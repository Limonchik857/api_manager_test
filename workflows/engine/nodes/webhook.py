"""Webhook trigger node.

The trigger receives the incoming payload and exposes it to all
subsequent nodes through the execution context. The node itself does
not perform any I/O.
"""


def execute_webhook(config, context):
    return {'received': True}