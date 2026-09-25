"""Coarse service readiness for the frontend's post-restart reload.

After a restart or update the API answers seconds before the model server has
loaded its model or the main container has started recording. The frontend
polls this summary before reloading instead of guessing with a fixed delay.

Public-safe by construction: only per-service states, never model names,
source labels or error text.
"""
import time

from core.settings_status import fresh


def model_readiness(reachable, startup_failed):
    """The model server loads its model before it starts serving, so any
    valid answer means it is loaded. A persisted startup failure ends the
    wait; the model server clears the file as each load attempt begins, so it
    always describes the current attempt.
    """
    if reachable:
        return 'ready'
    return 'failed' if startup_failed else 'starting'


def build_service_readiness(model_state, recorder, *, now=None):
    """Combine the model state with the recorder heartbeat.

    The recorder is up once this API process holds a fresh heartbeat from
    main (the status lives in the API's memory, so a restarted API starts
    empty). Source health (a camera being down, quiet hours) is deliberately
    not part of readiness: it can stay bad indefinitely and has its own UI.
    """
    now = time.time() if now is None else now
    services = {
        'model': model_state,
        'recorder': 'ready' if fresh(recorder, now) else 'starting',
    }
    return {
        'ready': all(state == 'ready' for state in services.values()),
        'services': services,
    }
